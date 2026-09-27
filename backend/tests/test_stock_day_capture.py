from datetime import date, datetime, timezone
import hashlib
import json
import zipfile

import httpx
import pytest
from sqlalchemy import select

from worker import source_registry as registry, source_runtime as runtime, sources, pipeline, stock_day_capture
from worker.stock_day_capture import load_stock_day_capture, StockDayCaptureError, MAX_ZIP_BYTES
from app.models import Instrument, MarketBar, RawPayload, IngestionRun
from app.coverage import verified_taiex_sessions
from test_pipeline_integration import pipeline_env
from test_sources import FixtureFetcher

DAY = date(2026, 9, 4)


class CollectionFetcher(FixtureFetcher):
    def __call__(self, url, **kwargs):
        payload = super().__call__(url, **kwargs)
        if url == sources.TPEX_SUSPEND_ENDPOINT:
            # Isolate capture success/reuse from unrelated notice warnings.
            return []
        if url == sources.TWSE_LISTED_ENDPOINT:
            for item in payload:
                item["Industry"] = "24"
        return payload


def row(code="1101", **changes):
    return {"Code": code, "Date": "1150904", "OpeningPrice": "200", "HighestPrice": "205",
            "LowestPrice": "198", "ClosingPrice": "203", "TradeVolume": "1,234",
            "TradeValue": "250,000", **changes}


@pytest.fixture
def bundle_factory(tmp_path):
    counter = 0
    def make(rows=None, *, body=None, mutate=None):
        nonlocal counter
        counter += 1
        root = tmp_path / str(counter)
        root.mkdir()
        manifest = registry.load_manifest()
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        body = body if body is not None else (json.dumps(rows if rows is not None else [row()], indent=2) + "\n").encode()
        args = dict(manifest=manifest_path, profile="free_public_local",
                    expected_registry_version=manifest["registry_version"], expected_digest=manifest["content_digest"])
        response = runtime.capture(**args, source_id="twse_stock_day_all", output_dir=root / "capture",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=httpx.ByteStream(body))))
        assert response["status"] == "capture_complete"
        receipt = response.copy()
        receipt["request_started_at"] = "2026-09-05T08:00:00+08:00"
        receipt["captured_at"] = "2026-09-05T08:00:01+08:00"
        if mutate:
            mutate(receipt)
        path = root / "input.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("body.bin", body)
            archive.writestr("receipt.json", json.dumps(receipt))
        return path, dict(**args, expected_market_date=DAY, output_dir=root / "materialized"), body
    return make


def test_exact_bytes_dates_units_and_selected_only_validation(bundle_factory):
    path, args, body = bundle_factory([row("00400A"), row("BAD", OpeningPrice="", TradeVolume="")])
    capture = load_stock_day_capture(path, **args)
    bars, raw, unavailable = capture.select(["00400A", "BAD", "ABSENT"], DAY)
    assert [b.symbol for b in bars] == ["00400A"]
    assert bars[0].volume == 1234 and bars[0].turnover == 250000
    assert (bars[0].turnover_status, bars[0].turnover_reason) == ("available", None)
    assert bars[0].adj_close is None and not bars[0].is_suspended
    assert bars[0].data_as_of == "2026-09-04"
    assert raw.collected_at == datetime(2026, 9, 5, 0, 0, 1, tzinfo=timezone.utc)
    assert raw.payload_path.read_bytes() == body
    assert raw.sha256 == hashlib.sha256(body).hexdigest() == bars[0].payload_sha256
    assert unavailable == [{"symbol": "BAD", "reason": "invalid_or_missing_OpeningPrice"}, {"symbol": "ABSENT", "reason": "missing_symbol"}]
    assert capture.select(["00400A"], DAY)[2] == []
    with pytest.raises(StockDayCaptureError, match="date_mismatch"):
        capture.select(["00400A"], date(2026, 9, 3))


@pytest.mark.parametrize("field,value", [
    ("OpeningPrice", ""), ("OpeningPrice", "NaN"), ("HighestPrice", "Infinity"),
    ("ClosingPrice", "0"), ("LowestPrice", "-1"), ("TradeVolume", "1.5"),
    ("TradeVolume", True), ("TradeVolume", "-1"), ("TradeVolume", "9223372036854775808"),
    ("HighestPrice", "199")])
def test_selected_bad_ohlcv_values_unavailable_without_zero_fill(bundle_factory, field, value):
    path, args, _ = bundle_factory([row(**{field: value}), row("GOOD")])
    capture = load_stock_day_capture(path, **args)
    bars, _, reasons = capture.select(["1101", "GOOD"], DAY)
    assert [b.symbol for b in bars] == ["GOOD"]
    assert len(reasons) == 1 and reasons[0]["symbol"] == "1101"


@pytest.mark.parametrize("case,expected_status,expected_reason,expected_amount", [
    ("omitted", "unavailable", "missing", 0),
    ("empty", "unavailable", "missing", 0),
    ("none", "unavailable", "missing", 0),
    ("negative", "unavailable", "invalid", 0),
    ("malformed", "unavailable", "invalid", 0),
    ("bad_commas", "unavailable", "invalid", 0),
    ("zero", "available", None, 0),
    ("positive", "available", None, 250000),
])
def test_selected_turnover_memory_contract(case, expected_status, expected_reason, expected_amount):
    selected = row()
    values = {
        "empty": "", "none": None, "negative": "-1", "malformed": "12xyz",
        "bad_commas": "12,34", "zero": "0", "positive": "250,000",
    }
    if case == "omitted":
        selected.pop("TradeValue")
    else:
        selected["TradeValue"] = values[case]
    rows, day = stock_day_capture._rows(json.dumps([selected]).encode())
    bars, unavailable = stock_day_capture._select_validated_rows(rows, day, ["1101"], "memory-sha")
    assert unavailable == []
    assert len(bars) == 1
    bar = bars[0]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (200, 205, 198, 203, 1234)
    assert (bar.turnover, bar.turnover_status, bar.turnover_reason) == (
        expected_amount, expected_status, expected_reason
    )
    assert bar.payload_sha256 == "memory-sha"


@pytest.mark.parametrize("field,value", [
    ("OpeningPrice", ""), ("ClosingPrice", "0"), ("TradeVolume", "1.5"),
    ("TradeVolume", True), ("HighestPrice", "199"),
])
def test_selected_ohlcv_invalid_still_rejects_whole_row_in_memory(field, value):
    rows, day = stock_day_capture._rows(json.dumps([row(**{field: value})]).encode())
    bars, unavailable = stock_day_capture._select_validated_rows(rows, day, ["1101"], "memory-sha")
    assert bars == []
    assert unavailable == [{"symbol": "1101", "reason": (
        "inconsistent_ohlc_range" if field == "HighestPrice" else "invalid_or_missing_" + field
    )}]


@pytest.mark.parametrize("date_value", ["1150904", "20260904", "115/09/04", "2026-09-04"])
def test_market_date_formats(bundle_factory, date_value):
    path, args, _ = bundle_factory([row(Date=date_value)])
    assert load_stock_day_capture(path, **args).market_date == DAY


@pytest.mark.parametrize("rows", [[], [1], [row(Code="")], [row(Date="")], [row(Date="1150230")],
                                  [row(), row()], [row(), row("X", Date="1150903")]])
def test_global_ambiguity_no_output(bundle_factory, rows):
    path, args, _ = bundle_factory(rows)
    with pytest.raises(StockDayCaptureError):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("key,value", [
    ("schema_version", "other"), ("status", "capture_failed"), ("source_id", "twse_twt48u_all"),
    ("endpoint", "https://invalid/"), ("method", "POST"), ("source_version", "wrong"),
    ("body_bytes", 0), ("body_sha256", "bad"), ("profile", "other"), ("request_count", True),
    ("executed_purposes", []), ("attribution", {}), ("policy_decisions", {}), ("condition_receipts", {}),
    ("captured_at", "2026-09-05T00:00:00"), ("captured_at", "2026-09-01T00:00:00Z"),
    ("http_status", 500), ("rate_limit_verified", True)])
def test_receipt_rejection_no_mutation(bundle_factory, key, value):
    path, args, _ = bundle_factory(mutate=lambda r: r.update({key: value}))
    with pytest.raises(StockDayCaptureError):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("pin", ["manifest", "profile", "expected_digest", "expected_registry_version"])
def test_explicit_pins_required(bundle_factory, pin):
    path, args, _ = bundle_factory()
    args[pin] = ""
    with pytest.raises(ValueError):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


def test_wrong_expected_day_no_output(bundle_factory):
    path, args, _ = bundle_factory()
    args["expected_market_date"] = date(2026, 9, 3)
    with pytest.raises(StockDayCaptureError, match="date_mismatch"):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("literal,expected", [("9007199254740993.0", 9007199254740993),
    ("9223372036854775807.0", 9223372036854775807), ("9223372036854775807", 9223372036854775807),
    ('"9223372036854775807"', 9223372036854775807), ("9007199254740993.1", None), ("1.5", None)])
def test_json_volume_exact_precision(bundle_factory, literal, expected):
    body = json.dumps([row(TradeVolume="REPLACE")]).replace('"REPLACE"', literal).encode()
    path, args, _ = bundle_factory(body=body)
    bars, _, reasons = load_stock_day_capture(path, **args).select(["1101"], DAY)
    if expected is None:
        assert not bars and reasons
    else:
        assert bars[0].volume == expected and not reasons


def test_replaced_metadata_is_rejected(bundle_factory):
    from dataclasses import replace
    path, args, _ = bundle_factory()
    capture = load_stock_day_capture(path, **args)
    for changed in (replace(capture, captured_at=datetime(2026, 9, 6, tzinfo=timezone.utc)),
                    replace(capture, captured_at=datetime(2026, 9, 5)), replace(capture, sha256="bad")):
        with pytest.raises(StockDayCaptureError):
            changed.select(["1101"], DAY)


@pytest.mark.parametrize("case", ["duplicate", "traversal", "compressed", "oversize", "nonfinite", "duplicate_json", "overflow_json"])
def test_invalid_archive_or_json_no_output(bundle_factory, case):
    path, args, body = bundle_factory()
    with zipfile.ZipFile(path) as archive:
        receipt = archive.read("receipt.json")
    if case == "oversize":
        path.write_bytes(b"x" * (MAX_ZIP_BYTES + 1))
    else:
        if case == "nonfinite": body = b'[NaN]'
        if case == "overflow_json": body = b'[1e999]'
        if case == "duplicate_json": body = b'[{"Code":"A","Code":"B"}]'
        meta = json.loads(receipt)
        meta.update(body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest())
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED if case == "compressed" else zipfile.ZIP_STORED) as archive:
            archive.writestr("../body.bin" if case == "traversal" else "body.bin", body)
            archive.writestr("receipt.json", json.dumps(meta))
            if case == "duplicate":
                with pytest.warns(UserWarning): archive.writestr("body.bin", body)
    with pytest.raises(StockDayCaptureError):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


def test_exclusive_output_and_changed_materialized_evidence(bundle_factory):
    path, args, _ = bundle_factory()
    args["output_dir"].mkdir()
    capture = load_stock_day_capture(path, **args)
    with pytest.raises(StockDayCaptureError, match="not_empty"):
        load_stock_day_capture(path, **args)
    capture.body_path.write_bytes(b"[]")
    with pytest.raises(StockDayCaptureError, match="materialized_body_changed"):
        capture.select(["1101"], DAY)


def test_publication_race_never_overwrites(bundle_factory, monkeypatch):
    from pathlib import Path
    path, args, _ = bundle_factory()
    original = Path.open
    raced = False
    def racing_open(self, mode="r", *a, **kw):
        nonlocal raced
        if self == args["output_dir"] / "receipt.json" and mode == "xb" and not raced:
            raced = True
            with original(self, "wb") as handle:
                handle.write(b"external owner")
        return original(self, mode, *a, **kw)
    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(FileExistsError):
        load_stock_day_capture(path, **args)
    assert (args["output_dir"] / "receipt.json").read_bytes() == b"external owner"
    assert not (args["output_dir"] / "body.bin").exists()
    assert not (args["output_dir"] / ".stock-day.lock").exists()


def test_policy_denied_before_output(bundle_factory):
    path, args, _ = bundle_factory()
    manifest = json.loads(args["manifest"].read_text())
    source = next(s for s in manifest["sources"] if s["source_id"] == "twse_stock_day_all")
    source["purposes"]["raw_store"]["status"] = "denied"
    manifest["content_digest"] = registry.manifest_digest(manifest)
    args["manifest"].write_text(json.dumps(manifest))
    args["expected_digest"] = manifest["content_digest"]
    with pytest.raises(ValueError):
        load_stock_day_capture(path, **args)
    assert not args["output_dir"].exists()


def test_history_never_overwrites_or_backfills_capture_day(bundle_factory):
    path, args, _ = bundle_factory([row("1101"), row("0050", TradeValue="")])
    capture = load_stock_day_capture(path, **args)
    fetcher = FixtureFetcher()
    adapter = sources.TwseAdapter(fetcher, stock_day_capture=capture)
    bars, payloads = adapter.fetch_bars(["1101", "0050", "MISSING"], DAY, DAY)
    assert sources.TWSE_DAILY_ENDPOINT not in fetcher.calls
    assert [(b.symbol, b.close) for b in bars] == [("1101", 203), ("0050", 203), ("TAIEX", 24000)]
    selected_etf = next(bar for bar in bars if bar.symbol == "0050")
    assert (selected_etf.volume, selected_etf.turnover, selected_etf.turnover_status, selected_etf.turnover_reason) == (
        1234, 0, "unavailable", "missing"
    )
    assert adapter.stock_day_unavailable == [{"symbol": "MISSING", "reason": "missing_symbol"}]
    assert len(adapter.fetch_warnings) == 2
    assert any("stock_day_capture_turnover_unavailable" in warning and "0050" in warning for warning in adapter.fetch_warnings)
    assert any("stock_day_capture_unavailable" in warning and "MISSING" in warning for warning in adapter.fetch_warnings)
    assert payloads[0].sha256 == capture.sha256


def test_other_history_days_unchanged(bundle_factory):
    path, args, _ = bundle_factory()
    capture = load_stock_day_capture(path, **args)
    original = FixtureFetcher()
    def fetcher(url, **kwargs):
        if url == sources.TWSE_HOLIDAY_ENDPOINT: return []
        payload = original(url, **kwargs)
        if "date=20260903" in url:
            payload["date"] = "20260903"
        return payload
    bars, _ = sources.TwseAdapter(fetcher, stock_day_capture=capture).fetch_bars(["1101"], date(2026, 9, 3), DAY)
    assert {(b.trading_date, b.close) for b in bars if b.symbol == "1101"} == {(date(2026, 9, 3), 100), (DAY, 203)}


def test_real_collect_force_reuse_partial_and_stale_row(pipeline_env, bundle_factory):
    # Full legacy adapters, with local fixture fetchers for every HTTP request.
    first = sources.OfficialMarketDataAdapter(sources.TwseAdapter(CollectionFetcher()), sources.TpexAdapter(CollectionFetcher()))
    baseline = pipeline.collect(DAY, adapter=first, force=True)
    assert baseline["status"] == "success", baseline
    with pipeline_env() as db:
        old = db.scalar(select(MarketBar).join(Instrument).where(Instrument.symbol == "9999"))
        old_id, old_raw, old_close = old.id, old.raw_payload_id, old.close
        prior_sessions = verified_taiex_sessions(db)
    path, args, body = bundle_factory([row("1101"), row("0050")])
    capture = load_stock_day_capture(path, **args)
    fetcher = CollectionFetcher()
    twse = sources.TwseAdapter(fetcher, stock_day_capture=capture)
    combined = sources.OfficialMarketDataAdapter(twse, sources.TpexAdapter(CollectionFetcher()))
    reused = pipeline.collect(DAY, adapter=combined)
    assert reused["idempotent_reuse"] and not fetcher.calls
    result = pipeline.collect(DAY, adapter=combined, force=True)
    assert result["status"] == "partial", result
    assert any("missing_symbol" in w and "9999" in w for w in result["warnings"])
    assert sources.TWSE_DAILY_ENDPOINT not in fetcher.calls
    with pipeline_env() as db:
        bar = db.scalar(select(MarketBar).join(Instrument).where(Instrument.symbol == "1101"))
        raw = db.get(RawPayload, bar.raw_payload_id)
        assert bar.close == 203 and bar.volume == 1234
        assert raw.sha256 == capture.sha256 == hashlib.sha256(body).hexdigest()
        assert raw.endpoint == sources.TWSE_DAILY_ENDPOINT
        assert raw.collected_at == datetime(2026, 9, 5, 0, 0, 1)
        assert raw.data_as_of == "2026-09-04"
        assert raw.payload_path == str(capture.body_path)
        assert verified_taiex_sessions(db) == prior_sessions
        stale = db.get(MarketBar, old_id)
        assert (stale.raw_payload_id, stale.close) == (old_raw, old_close)
        assert db.get(IngestionRun, result["run_id"]).status == "partial"


def test_capture_alone_cannot_create_session(pipeline_env, bundle_factory):
    path, args, _ = bundle_factory([row("1101"), row("0050"), row("9999")])
    capture = load_stock_day_capture(path, **args)
    fixture = FixtureFetcher()
    def no_index(url, **kwargs):
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            raise sources.OfficialDataError("fixture MI_INDEX unavailable")
        if url == sources.TWSE_INDEX_ENDPOINT: return []
        return fixture(url, **kwargs)
    combined = sources.OfficialMarketDataAdapter(sources.TwseAdapter(no_index, stock_day_capture=capture), sources.TpexAdapter(FixtureFetcher()))
    result = pipeline.collect(DAY, adapter=combined, force=True)
    # The existing full adapter rejects an empty index response. Capture bars
    # must not relax that gate; raw evidence survives the failed collection.
    assert result["status"] == "failed", result
    with pipeline_env() as db:
        assert verified_taiex_sessions(db) == []
        assert db.scalar(select(MarketBar).join(Instrument).where(Instrument.symbol == "1101")) is None
        assert db.scalar(select(RawPayload).where(RawPayload.sha256 == capture.sha256)) is not None
