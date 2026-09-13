from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
from urllib.parse import parse_qs, urlparse
import zipfile

import httpx
import pytest
from sqlalchemy import select, text

from worker import source_registry as registry, source_runtime as runtime, sources, pipeline
from worker.holiday_capture import load_holiday_capture, HolidayCaptureError, MAX_ZIP_BYTES
from worker.stock_day_capture import load_stock_day_capture
from app.models import RawPayload, MarketBar, Instrument
from app.coverage import verified_taiex_sessions
from test_pipeline_integration import pipeline_env
from test_sources import FixtureFetcher

DAY = date(2026, 9, 4)
CLOSED = date(2026, 9, 3)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("holiday tests must never access the network")
    monkeypatch.setattr(socket.socket, "connect", blocked)


def row(day=CLOSED, **changes):
    return {"Date": day.isoformat(), "Weekday": "一二三四五六日"[day.weekday()],
            "Name": "端午節", "Description": "依規定放假1日。", **changes}


@pytest.fixture
def bundle_factory(tmp_path):
    count = 0
    def make(rows=None, *, body=None, mutate=None, source_id="twse_holiday_schedule"):
        nonlocal count
        count += 1
        root = tmp_path / str(count)
        root.mkdir()
        manifest = registry.load_manifest()
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        body = body if body is not None else (json.dumps([row()] if rows is None else rows, ensure_ascii=False, indent=2) + "\n").encode()
        args = dict(manifest=manifest_path, profile="free_public_local", expected_registry_version=manifest["registry_version"], expected_digest=manifest["content_digest"])
        receipt = runtime.capture(**args, source_id=source_id, output_dir=root / "captured",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=httpx.ByteStream(body))))
        assert receipt["status"] == "capture_complete", receipt
        receipt["request_started_at"] = "2026-09-05T08:00:00+08:00"
        receipt["captured_at"] = "2026-09-05T08:00:01+08:00"
        if mutate:
            mutate(receipt)
        path = root / "input.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("body.bin", body)
            archive.writestr("receipt.json", json.dumps(receipt))
        return path, dict(**args, expected_schedule_year=2026, output_dir=root / "materialized"), body
    return make


def test_exact_evidence_and_repeated_selection(bundle_factory):
    path, args, body = bundle_factory([row(), row(DAY, Name="開始交易", Description="不休市，照常交易。")])
    capture = load_holiday_capture(path, **args)
    closed, raw, unknown = capture.select(CLOSED, DAY)
    assert closed == {CLOSED}
    assert unknown == [{"date": DAY.isoformat(), "name": "開始交易", "reason": "unrecognized_or_nonclosing_name"}]
    assert raw.payload_path.read_bytes() == body
    assert raw.sha256 == capture.sha256 == hashlib.sha256(body).hexdigest()
    assert raw.collected_at == datetime(2026, 9, 5, 0, 0, 1, tzinfo=timezone.utc)
    assert raw.endpoint == sources.TWSE_HOLIDAY_ENDPOINT and raw.data_as_of == "2026"
    assert capture.select(CLOSED, DAY) == (closed, raw, unknown)
    assert capture.select(date(2025, 12, 31), date(2027, 1, 2))[0] == {CLOSED}


@pytest.mark.parametrize("day,name,description", [
    (date(2026, 2, 12), "市場無交易，僅辦理結算交割作業", ""),
    (date(2026, 6, 19), "端午節", " 依規定放假 1 日。< br >"),
    (date(2026, 2, 27), "和平紀念日", "和平紀念日為2月28日適逢星期六，於2月27日（星期五）補假。"),
    (date(2026, 4, 3), "兒童節及民族掃墓節", "兒童節為4月4日適逢星期六，於4月3日（星期五）補假。"),
    (date(2026, 4, 6), "兒童節及民族掃墓節", "民族掃墓節為4月5日適逢星期日，於4月6日（星期一）補假。"),
    (date(2026, 10, 9), "國慶日", "國慶日為10月10日適逢星期六，於10月9日（星期五）補假。"),
    (date(2026, 10, 26), "臺灣光復暨金門古寧頭大捷紀念日", "臺灣光復暨金門古寧頭大捷紀念日為10月25日適逢星期日，於10月26日（星期一）補假。"),
    (date(2026, 2, 17), "農曆除夕及春節", "依規定於2月15日至2月19日放假5日。2月15日適逢星期日，於2月20日（星期五）補假。<br><br>"),
    (date(2026, 2, 20), "農曆除夕及春節", "依規定於2月15日至2月19日放假5日。2月15日適逢星期日，於2月20日（星期五）補假。"),
])
def test_complete_grammar_only_excludes_its_own_row(bundle_factory, day, name, description):
    path, args, _ = bundle_factory([row(day, Name=name, Description=description)])
    closed, _, unknown = load_holiday_capture(path, **args).select(date(2026, 1, 1), date(2026, 12, 31))
    assert closed == {day} and unknown == []


@pytest.mark.parametrize("changes", [
    {"Description": "不休市，照常交易。"}, {"Description": "不放假。"},
    {"Description": "依規定放假1日。但本日照常交易。"},
    {"Description": "<b>依規定放假1日。</b>"},
    {"Name": "農曆春節前最後交易日", "Description": "依規定放假1日。"},
    {"Name": "市場無交易，僅辦理結算交割作業", "Description": "照常交易。"},
    {"Name": "和平紀念日", "Description": "和平紀念日為2月28日適逢星期六，於2月27日（星期四）補假。"},
    {"Name": "和平紀念日", "Description": "和平紀念日為2月28日適逢星期六，於2月27日（星期五）補假。"},
    {"Name": "農曆除夕及春節", "Description": "依規定於2月15日至2月19日放假6日。2月15日適逢星期日，於2月20日（星期五）補假。"},
    {"Name": "農曆除夕及春節", "Description": "依規定於2月15日至2月19日放假5日。2月15日適逢星期日，於2月20日（星期五）補假。"},
    {"Name": "和平紀念日", "Description": "和平紀念日為2月30日適逢星期六，於2月27日（星期五）補假。"},
])
def test_unknown_and_contradictory_text_never_excludes(bundle_factory, changes):
    path, args, _ = bundle_factory([row(**changes)])
    closed, _, unknown = load_holiday_capture(path, **args).select(CLOSED, DAY)
    assert closed == set() and len(unknown) == 1


@pytest.mark.parametrize("rows", [[], [1], [row(), row()], [row(Weekday="五")],
    [row(Date="1150230")], [row(date(2025, 9, 3))], [row(Name=None)], [row(Description=1)],
    [row(Date="09/03")], [row(Weekday="")]])
def test_global_invalid_before_publish(bundle_factory, rows):
    path, args, _ = bundle_factory(rows)
    with pytest.raises(HolidayCaptureError):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("value", [True, "2026", 2025, 0, 10000])
def test_expected_year_is_explicit_integer(bundle_factory, value):
    path, args, _ = bundle_factory()
    args["expected_schedule_year"] = value
    with pytest.raises(HolidayCaptureError):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("field,value", [
    ("source_id", "twse_stock_day_all"), ("endpoint", "https://invalid.example"),
    ("method", "POST"), ("body_sha256", "bad"), ("body_bytes", 0), ("http_status", True),
    ("profile", "other"), ("source_version", "wrong"), ("manifest_digest", "wrong"),
    ("registry_version", "wrong"), ("request_count", True), ("executed_purposes", []),
    ("historical_pit", "supported"), ("policy_decisions", {}), ("attribution", {}),
    ("condition_receipts", {}), ("captured_at", "2026-09-05T08:00:01"),
    ("captured_at", "2026-09-01T00:00:00+00:00"), ("rate_limit_verified", True),
])
def test_receipt_rejected_before_publish(bundle_factory, field, value):
    path, args, _ = bundle_factory(mutate=lambda receipt: receipt.update({field: value}))
    with pytest.raises(HolidayCaptureError):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("condition,key,value", [
    ("bounded_requests", "max_requests", True), ("bounded_requests", "max_body_bytes", 5),
    ("respect_endpoint_limits", "retries", False), ("respect_endpoint_limits", "redirects", 1),
    ("respect_endpoint_limits", "numeric_quota_verified", 0),
    ("preserve_source_integrity", "encoding", "reencoded"),
])
def test_conditions_are_rechecked(bundle_factory, condition, key, value):
    path, args, _ = bundle_factory(mutate=lambda r: r["condition_receipts"][condition].update({key: value}))
    with pytest.raises(HolidayCaptureError):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


def test_nested_policy_boolean_not_integer_alias(bundle_factory):
    path, args, _ = bundle_factory(mutate=lambda r: r["policy_decisions"]["local_fetch"].update(allowed=1))
    with pytest.raises(HolidayCaptureError, match="policy_decisions"):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("case", ["duplicate", "traversal", "compressed", "oversize", "nonfinite", "overflow", "jsonduplicate", "receiptduplicate"])
def test_zip_json_limits(bundle_factory, case):
    path, args, body = bundle_factory()
    with zipfile.ZipFile(path) as archive:
        receipt = json.loads(archive.read("receipt.json"))
    if case == "oversize":
        path.write_bytes(b"x" * (MAX_ZIP_BYTES + 1))
    else:
        if case == "nonfinite": body = b'[NaN]'
        if case == "overflow": body = b'[1e999]'
        if case == "jsonduplicate": body = b'[{"Date":"1150903","Date":"1150904"}]'
        receipt.update(body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest())
        receipt_bytes = json.dumps(receipt).encode()
        if case == "receiptduplicate": receipt_bytes = b'{"status":"a",' + receipt_bytes[1:]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED if case == "compressed" else zipfile.ZIP_STORED) as archive:
            archive.writestr("../body.bin" if case == "traversal" else "body.bin", body)
            archive.writestr("receipt.json", receipt_bytes)
            if case == "duplicate":
                with pytest.warns(UserWarning): archive.writestr("body.bin", body)
    with pytest.raises(HolidayCaptureError):
        load_holiday_capture(path, **args)
    assert not args["output_dir"].exists()


def test_pins_policy_and_exclusive_output(bundle_factory):
    path, args, _ = bundle_factory()
    with pytest.raises(ValueError): load_holiday_capture(path, **{**args, "expected_digest": "bad"})
    assert not args["output_dir"].exists()
    manifest = json.loads(args["manifest"].read_text())
    source = next(s for s in manifest["sources"] if s["source_id"] == "twse_holiday_schedule")
    source["purposes"]["raw_store"]["status"] = "denied"
    manifest["content_digest"] = registry.manifest_digest(manifest)
    args["manifest"].write_text(json.dumps(manifest))
    with pytest.raises(ValueError): load_holiday_capture(path, **{**args, "expected_digest": manifest["content_digest"]})
    assert not args["output_dir"].exists()
    path, args, _ = bundle_factory()
    args["output_dir"].mkdir()
    load_holiday_capture(path, **args)
    with pytest.raises(HolidayCaptureError, match="not_empty"): load_holiday_capture(path, **args)


@pytest.mark.parametrize("mutation", ["body", "receipt", "year", "timestamp", "sha"])
def test_use_revalidates_materialized_and_object_evidence(bundle_factory, mutation):
    path, args, _ = bundle_factory()
    capture = load_holiday_capture(path, **args)
    if mutation == "body": capture.body_path.write_bytes(b"[]")
    if mutation == "receipt": capture.body_path.with_name("receipt.json").write_bytes(b"{}")
    if mutation == "year": capture = replace(capture, schedule_year=2025)
    if mutation == "timestamp": capture = replace(capture, captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    if mutation == "sha": capture = replace(capture, sha256="bad")
    with pytest.raises(HolidayCaptureError): capture.select(CLOSED, DAY)


class CalendarFetcher(FixtureFetcher):
    def __init__(self, calendar=None):
        super().__init__()
        self.calendar = [row()] if calendar is None else calendar

    def __call__(self, url, **kwargs):
        if url == sources.TWSE_HOLIDAY_ENDPOINT:
            self.calls.append(url)
            return self.calendar
        payload = super().__call__(url, **kwargs)
        if url == sources.TPEX_SUSPEND_ENDPOINT:
            # Isolate calendar success/reuse from unrelated notice warnings.
            return []
        if url == sources.TWSE_LISTED_ENDPOINT:
            for item in payload: item["Industry"] = "24"
        requested = parse_qs(urlparse(url).query).get("date", [None])[0]
        if requested is None and isinstance(kwargs.get("data"), dict):
            requested = kwargs["data"].get("date", "").replace("/", "") or None
        if requested and isinstance(payload, dict):
            payload["date"] = requested
        return payload


def test_adapter_positive_unknown_missing_and_legacy(bundle_factory):
    path, args, _ = bundle_factory([row(), row(date(2026, 9, 2), Description="不休市。")])
    capture = load_holiday_capture(path, **args)
    fetcher = CalendarFetcher()
    adapter = sources.TwseAdapter(fetcher, holiday_capture=capture)
    bars, payloads = adapter.fetch_bars(["1101"], date(2026, 9, 1), DAY)
    assert sources.TWSE_HOLIDAY_ENDPOINT not in fetcher.calls
    assert not any("date=20260903" in url for url in fetcher.calls)
    assert any("date=20260901" in url for url in fetcher.calls)
    assert any("date=20260902" in url for url in fetcher.calls)
    assert {b.trading_date for b in bars} == {date(2026, 9, 1), date(2026, 9, 2), DAY}
    assert adapter.holiday_unknown[0]["date"] == "2026-09-02"
    assert any(p.sha256 == capture.sha256 for p in payloads)
    legacy = CalendarFetcher()
    sources.TwseAdapter(legacy).fetch_bars(["1101"], CLOSED, DAY)
    assert sources.TWSE_HOLIDAY_ENDPOINT in legacy.calls


def test_single_day_does_not_consume_and_multi_day_bad_capture_no_fallback(bundle_factory):
    path, args, _ = bundle_factory()
    capture = load_holiday_capture(path, **args)
    capture.body_path.write_bytes(b"changed")
    fetcher = CalendarFetcher()
    adapter = sources.TwseAdapter(fetcher, holiday_capture=capture)
    adapter.fetch_bars(["1101"], DAY, DAY)
    assert adapter.holiday_closed_dates == set() and adapter.holiday_unknown == []
    with pytest.raises(HolidayCaptureError): adapter.fetch_bars(["1101"], CLOSED, DAY)
    assert sources.TWSE_HOLIDAY_ENDPOINT not in fetcher.calls


def test_visible_daily_or_later_index_conflicts_preserve_raw(bundle_factory):
    path, args, _ = bundle_factory([row(DAY)])
    capture = load_holiday_capture(path, **args)
    adapter = sources.TwseAdapter(CalendarFetcher(), holiday_capture=capture)
    with pytest.raises(sources.OfficialDataError, match="trading_conflict"):
        adapter.fetch_bars(["UNSELECTED"], CLOSED, DAY)
    assert any(p.sha256 == capture.sha256 for p in adapter.captured_payloads)
    fixture = CalendarFetcher()
    def no_daily(url, **kwargs):
        return [] if url == sources.TWSE_DAILY_ENDPOINT else fixture(url, **kwargs)
    adapter = sources.TwseAdapter(no_daily, holiday_capture=capture)
    with pytest.raises(sources.OfficialDataError, match="trading_conflict.*TAIEX"):
        adapter.fetch(CLOSED, DAY)
    assert any(p.endpoint == sources.TWSE_INDEX_ENDPOINT for p in adapter.captured_payloads)
    assert any(p.sha256 == capture.sha256 for p in adapter.captured_payloads)


@pytest.mark.parametrize("bad", ["wrongdate", "missingindex", "nodata"])
def test_calendar_does_not_establish_taiex_session(bundle_factory, bad):
    path, args, _ = bundle_factory()
    capture = load_holiday_capture(path, **args)
    fixture = CalendarFetcher()
    def broken(url, **kwargs):
        payload = fixture(url, **kwargs)
        if url.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT):
            if bad == "wrongdate": payload["date"] = "20260901"
            if bad == "missingindex": payload["tables"] = payload["tables"][1:]
            if bad == "nodata": return {"stat": "沒有符合條件的資料"}
        return payload
    adapter = sources.TwseAdapter(broken, holiday_capture=capture)
    if bad == "nodata":
        bars, _ = adapter.fetch_bars(["1101"], CLOSED, DAY)
        assert not any(bar.symbol == "TAIEX" for bar in bars)
    else:
        with pytest.raises(sources.OfficialDataError): adapter.fetch_bars(["1101"], CLOSED, DAY)


def test_combines_with_stock_capture(bundle_factory):
    path, args, _ = bundle_factory()
    calendar = load_holiday_capture(path, **args)
    daily = [{"Code": "1101", "Date": "20260904", "OpeningPrice": "100", "HighestPrice": "105", "LowestPrice": "98", "ClosingPrice": "103", "TradeVolume": "1000", "TradeValue": "103000"}]
    path, args, _ = bundle_factory(daily, source_id="twse_stock_day_all")
    args.pop("expected_schedule_year")
    stock = load_stock_day_capture(path, **args, expected_market_date=DAY)
    fetcher = CalendarFetcher()
    bars, _ = sources.TwseAdapter(fetcher, stock_day_capture=stock, holiday_capture=calendar).fetch_bars(["1101"], CLOSED, DAY)
    assert sources.TWSE_DAILY_ENDPOINT not in fetcher.calls and sources.TWSE_HOLIDAY_ENDPOINT not in fetcher.calls
    assert {b.symbol for b in bars} == {"1101", "TAIEX"}


@pytest.mark.parametrize("preexisting_closed", [False, True])
def test_actual_collect_force_and_reuse_local_only(pipeline_env, bundle_factory, preexisting_closed):
    path, args, body = bundle_factory()
    capture = load_holiday_capture(path, **args)
    baseline_adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(CalendarFetcher([] if preexisting_closed else None)), sources.TpexAdapter(CalendarFetcher()))
    baseline = pipeline.collect(DAY, months_back=1, adapter=baseline_adapter, force=True)
    assert baseline["status"] == "success", baseline
    with pipeline_env() as db:
        old = db.scalar(select(MarketBar).join(Instrument).where(Instrument.symbol == "TAIEX", MarketBar.trading_date == CLOSED))
        old_state = (old.id, old.raw_payload_id, old.close) if old else None
        assert (old is not None) == preexisting_closed
    fetcher = CalendarFetcher()
    adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(fetcher, holiday_capture=capture), sources.TpexAdapter(CalendarFetcher()))
    reused = pipeline.collect(DAY, months_back=1, adapter=adapter)
    assert reused["idempotent_reuse"] and fetcher.calls == []
    result = pipeline.collect(DAY, months_back=1, adapter=adapter, force=True)
    assert result["status"] == "success", result
    assert result["run_id"] == baseline["run_id"]
    assert sources.TWSE_HOLIDAY_ENDPOINT not in fetcher.calls
    assert not any("date=20260903" in url for url in fetcher.calls)
    with pipeline_env() as db:
        raw = db.scalar(select(RawPayload).where(RawPayload.sha256 == capture.sha256))
        assert raw.payload_path == str(capture.body_path) and raw.sha256 == hashlib.sha256(body).hexdigest()
        assert raw.collected_at == datetime(2026, 9, 5, 0, 0, 1) and raw.endpoint == sources.TWSE_HOLIDAY_ENDPOINT
        assert (CLOSED in verified_taiex_sessions(db)) == preexisting_closed
        retained = db.scalar(select(MarketBar).join(Instrument).where(Instrument.symbol == "TAIEX", MarketBar.trading_date == CLOSED))
        assert ((retained.id, retained.raw_payload_id, retained.close) if retained else None) == old_state
        assert db.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    repeated = pipeline.collect(DAY, months_back=1, adapter=adapter, force=True)
    assert repeated["status"] == "success" and repeated["run_id"] == result["run_id"]


def test_publication_race_and_inside_project_rejected(bundle_factory, monkeypatch):
    path, args, _ = bundle_factory()
    with pytest.raises(HolidayCaptureError, match="output_inside_project"):
        load_holiday_capture(path, **{**args, "output_dir": Path(__file__).resolve().parents[2] / "holiday-output"})
    original = Path.open
    raced = False
    def racing_open(self, mode="r", *a, **kw):
        nonlocal raced
        if self == args["output_dir"] / "receipt.json" and mode == "xb" and not raced:
            raced = True
            with original(self, "wb") as handle: handle.write(b"external owner")
        return original(self, mode, *a, **kw)
    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(FileExistsError): load_holiday_capture(path, **args)
    assert (args["output_dir"] / "receipt.json").read_bytes() == b"external owner"
    assert not (args["output_dir"] / "body.bin").exists()
    assert not (args["output_dir"] / ".holiday.lock").exists()


def test_cross_year_requests_outside_calendar_year_remain(bundle_factory):
    path, args, _ = bundle_factory([row(date(2026, 1, 1), Name="中華民國開國紀念日")])
    capture = load_holiday_capture(path, **args)
    fetcher = CalendarFetcher()
    bars, _ = sources.TwseAdapter(fetcher, holiday_capture=capture).fetch_bars(["1101"], date(2025, 12, 31), date(2026, 1, 2))
    assert any("date=20251231" in url for url in fetcher.calls)
    assert any("date=20260102" in url for url in fetcher.calls)
    assert not any("date=20260101" in url for url in fetcher.calls)
    assert {b.trading_date for b in bars if b.symbol == "TAIEX"} == {date(2025, 12, 31), date(2026, 1, 2)}


def test_collect_index_conflict_fails_and_preserves_both_raw_payloads(pipeline_env, bundle_factory):
    path, args, _ = bundle_factory([row(DAY)])
    capture = load_holiday_capture(path, **args)
    fixture = CalendarFetcher()
    def no_daily(url, **kwargs):
        return [] if url == sources.TWSE_DAILY_ENDPOINT else fixture(url, **kwargs)
    adapter = sources.OfficialMarketDataAdapter(sources.TwseAdapter(no_daily, holiday_capture=capture), sources.TpexAdapter(CalendarFetcher()))
    result = pipeline.collect(DAY, months_back=1, adapter=adapter, force=True)
    assert result["status"] == "failed" and "holiday_capture_trading_conflict" in result["error"]
    with pipeline_env() as db:
        assert db.scalar(select(RawPayload).where(RawPayload.sha256 == capture.sha256)) is not None
        assert db.scalar(select(RawPayload).where(RawPayload.endpoint == sources.TWSE_INDEX_ENDPOINT)) is not None
        assert verified_taiex_sessions(db) == []
