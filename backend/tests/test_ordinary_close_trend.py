"""Issue 8: MA20 / 20-day return / close-over-MA20 read from the issue 7 saved-close bundle.

Every bundle here is synthetic test data written under a temporary root; it proves the
arithmetic, gates and failure isolation only, never a real source or the real private root.
The bundle writer follows the section 52 contract with independent literals and does not
reuse the product's save path or the standalone ``test_ordinary_close_source.py``.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, getcontext
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import ordinary_close_source as source
from app import ordinary_close_trend as trend

ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV = "STOCK_ORDINARY_CLOSE_PRIVATE_ROOT"
POLICY_VERSION = "issue7-ordinary-close-saved-seven-v1"
POLICY_SHA = "f7659362cd3056413545d48a40a2e89bc97b810dc9c5535a4c8bdca41fcb9968"
POLICY_BYTES = 5173
NAMESPACE = "issue7-ordinary-close-saved-seven-v1/qa1"
TRADING_VERSION = "finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue7-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFF = "2026-10-06"
START, END = "2026-07-01", "2026-10-06"
CLOSED = ("2026-09-25", "2026-09-28")
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
LIMITATIONS = [
    "date_is_asia_taipei_trading_calendar_date_not_utc",
    "identity_and_unit_anchored_only_at_2026-10-06",
    "publication_time_first_availability_revision_time_unknown",
    "closes_only_no_open_high_low_volume_amount",
    "raw_body_not_stored_hashes_only",
    "personal_noncommercial_local_use_no_redistribution",
]
RIGHTS = "synthetic test rights text"
ATTRIBUTION = "synthetic test attribution"
RECEIPT_FIELDS = ("source_id", "source_version", "method", "url", "status", "request_started_utc", "observed_utc",
                  "body_bytes", "body_sha256", "full_eof", "content_type", "content_encoding", "namespace", "policy_sha256")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def trading_dates() -> list[str]:
    value, days = date.fromisoformat(START), []
    while value <= date.fromisoformat(END):
        if value.weekday() < 5 and value.isoformat() not in CLOSED:
            days.append(value.isoformat())
        value += timedelta(days=1)
    return days


CALENDAR = trading_dates()
WINDOW = CALENDAR[-60:]


def close_text(stock: int, day: int) -> str:
    """Canonical positive decimal text, at most four decimals, different for every stock and day."""
    ticks = 100000 + 9000 * stock + (day * day * 37 + day * 11) % 6007
    return format(Decimal(ticks).scaleb(-4).normalize(), "f")


def closes_document() -> dict:
    return {"schema": "ordinary-close-saved/v1", "cutoff": CUTOFF, "count": 60, "symbols": list(SYMBOLS),
            "trading_dates": list(WINDOW), "counts": {symbol: 60 for symbol in SYMBOLS},
            "closes": {symbol: [[day, close_text(stock, index)] for index, day in enumerate(WINDOW)]
                       for stock, symbol in enumerate(SYMBOLS)}}


def receipt_document(closes_bytes: bytes) -> dict:
    base = datetime(2026, 10, 6, 23, 32, 0, tzinfo=timezone.utc)
    gets = []
    for index in range(8):
        started = base + timedelta(seconds=4 * index)
        entry = {
            "source_id": "finmind_trading_dates" if index == 0 else "finmind_nominal_ohlcv/" + SYMBOLS[index - 1],
            "source_version": TRADING_VERSION if index == 0 else POLICY_VERSION, "method": "GET",
            "url": (ENDPOINT + f"?dataset=TaiwanStockTradingDate&start_date={START}&end_date={END}" if index == 0 else
                    ENDPOINT + f"?dataset=TaiwanStockPrice&data_id={SYMBOLS[index - 1]}&start_date={START}&end_date={END}"),
            "status": 200, "request_started_utc": started.isoformat(), "observed_utc": (started + timedelta(seconds=2)).isoformat(),
            "body_bytes": 1000 + index, "body_sha256": sha(f"synthetic-body-{index}".encode()), "full_eof": True,
            "content_type": "application/json", "content_encoding": "identity", "namespace": NAMESPACE, "policy_sha256": POLICY_SHA}
        entry["receipt_sha256"] = sha(canonical({name: entry[name] for name in RECEIPT_FIELDS}))
        gets.append(entry)
    return {
        "schema": "ordinary-close-receipt/v1", "storage": "private_local", "storage_schema": "ordinary-close-saved/v1",
        "namespace": NAMESPACE, "purpose": "local_personal_noncommercial_private_derived_close_window",
        "consumer_version": "ordinary-close-saved-window-v1",
        "source_policy": {"version": POLICY_VERSION, "sha256": POLICY_SHA, "bytes": POLICY_BYTES},
        "trading_date_source_version": TRADING_VERSION, "market": "TW/TPEx", "instrument_type": "ordinary_stock",
        "identity_as_of": CUTOFF, "cutoff": CUTOFF, "window": {"start_date": START, "end_date": END},
        "calendar_rows": len(CALENDAR), "gets": gets,
        "adapter": {"ordinary_close_source_sha256": sha(b"adapter-one"), "ohlcv_history_source_sha256": sha(b"adapter-two")},
        "closes": {"file": "closes.json", "sha256": sha(closes_bytes), "bytes": len(closes_bytes)},
        "saved_at": (base + timedelta(seconds=40)).isoformat(), "attribution": ATTRIBUTION,
        "rights": {"price_source": RIGHTS, "trading_date_source": RIGHTS},
        "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
        "limitations": list(LIMITATIONS)}


def write_bundle(root: str, closes_fn=None, receipt_fn=None, restamp: bool = True, cutoff: str = CUTOFF) -> tuple[bytes, bytes]:
    closes = closes_document()
    if closes_fn:
        closes_fn(closes)
    closes_bytes = canonical(closes)
    receipt = receipt_document(closes_bytes if restamp else canonical(closes_document()))
    if receipt_fn:
        receipt_fn(receipt)
    receipt_bytes = canonical(receipt)
    final = os.path.join(root, POLICY_VERSION, cutoff)
    os.makedirs(final)
    for name, data in (("closes.json", closes_bytes), ("receipt.json", receipt_bytes)):
        with open(os.path.join(final, name), "wb") as handle:
            handle.write(data)
    return closes_bytes, receipt_bytes


def oracle(texts: list[str]) -> dict:
    """Independent Decimal / scaled-integer arithmetic; rounds only for display."""
    getcontext().prec = 100
    numbers = [Decimal(text) for text in texts]
    average = sum(numbers[-20:]) / 20

    def show(value: Decimal, places: int) -> str:
        text = str(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))
        return text[1:] if text.startswith("-") and Decimal(text) == 0 else text

    ticks = [int(number.scaleb(6)) for number in numbers]
    window = sum(ticks[-20:])
    exact = {"ma20": Fraction(window, 20 * 10 ** 6), "return_20d": Fraction(ticks[-1], ticks[0]) - 1,
             "close_over_ma20": Fraction(ticks[-1] * 20, window)}
    return {"exact": {name: f"{value.numerator}/{value.denominator}" for name, value in exact.items()},
            "display": {"ma20": show(average, 2), "return_20d": show((numbers[-1] / numbers[0] - 1) * 100, 2),
                        "close_over_ma20": show(numbers[-1] / average, 4)}}


def tree(root: str) -> list:
    rows = []
    for folder, names, files in os.walk(root):
        for name in sorted(names + files):
            path = os.path.join(folder, name)
            info = os.stat(path)
            rows.append((os.path.relpath(path, root), os.path.isdir(path), info.st_size, info.st_mtime_ns,
                         sha(open(path, "rb").read()) if os.path.isfile(path) else None))
    return sorted(rows)


def instrument(symbol="6488", exchange="TPEx", market="TW", kind="stock", category=None):
    return SimpleNamespace(exchange=exchange, symbol=symbol, market=market, instrument_type=kind, etf_category=category)


def policy_unsupported() -> list:
    """The ``unsupported`` list of policy v1, read as data from the pinned literal in the source test."""
    text = (ROOT / "backend/tests/test_ordinary_close_source.py").read_text(encoding="utf-8")
    match = re.search(r"^V1_POLICY = (b'.*')$", text, re.M)
    raw = ast.literal_eval(match.group(1))
    assert sha(raw) == POLICY_SHA and len(raw) == POLICY_BYTES
    return json.loads(raw)["unsupported"]


class TempRoot(unittest.TestCase):
    def new_root(self) -> str:
        root = tempfile.mkdtemp(prefix="oct")
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def read(self, root, symbol="6488", as_of=date(2026, 10, 6), **kwargs):
        return trend.read_ordinary_close_trend(instrument(symbol, **kwargs), as_of, environment={ROOT_ENV: root})


class RoundingAndArithmetic(unittest.TestCase):
    def test_half_up_away_from_zero_and_unsigned_zero(self):
        cases = [(Fraction(1, 8), 2, "0.13"), (Fraction(-1, 8), 2, "-0.13"), (Fraction(5, 2), 0, "3"), (Fraction(-5, 2), 0, "-3"),
                 (Fraction(-1, 1000), 2, "0.00"), (Fraction(1, 3), 4, "0.3333"), (Fraction(2, 3), 4, "0.6667"),
                 (Fraction(203, 2), 2, "101.50"), (Fraction(0), 2, "0.00"), (Fraction(99995, 1000), 2, "100.00"),
                 (Fraction(-99995, 1000), 2, "-100.00"), (Fraction(1, 800) * 100, 2, "0.13"), (Fraction(-1, 800) * 100, 2, "-0.13")]
        for value, places, expected in cases:
            with self.subTest(value=value, places=places):
                self.assertEqual(trend.round_half_up(value, places), expected)

    def rows(self, texts):
        return [source.Close(f"2026-09-{index + 1:02d}", text, Fraction(text)) for index, text in enumerate(texts)]

    def test_hand_computed_window(self):
        rows = self.rows(["100"] + ["101"] * 10 + ["102"] * 10)
        values = trend.derive_values(rows)
        self.assertEqual((values["ma20"]["exact"], values["ma20"]["display"]), ("203/2", "101.50"))
        self.assertEqual((values["return_20d"]["exact"], values["return_20d"]["display"]), ("1/50", "2.00"))
        self.assertEqual((values["close_over_ma20"]["exact"], values["close_over_ma20"]["display"]), ("204/203", "1.0049"))
        self.assertEqual(values["ma20"]["window_start"], rows[1].date)
        self.assertEqual((values["return_20d"]["base_date"], values["return_20d"]["latest_date"]), (rows[0].date, rows[-1].date))
        self.assertEqual(values["latest"], {"date": rows[-1].date, "close": "102"})

    def test_ties_use_exact_values_not_rounded_closes(self):
        values = trend.derive_values(self.rows(["100"] * 2 + ["100"] * 18 + ["102.5"]))
        self.assertEqual((values["ma20"]["exact"], values["ma20"]["display"]), ("801/8", "100.13"))
        up = trend.derive_values(self.rows(["800"] + ["800"] * 19 + ["801"]))
        down = trend.derive_values(self.rows(["800"] + ["800"] * 19 + ["799"]))
        self.assertEqual((up["return_20d"]["exact"], up["return_20d"]["display"]), ("1/800", "0.13"))
        self.assertEqual((down["return_20d"]["exact"], down["return_20d"]["display"]), ("-1/800", "-0.13"))

    def test_short_windows_are_data_insufficient_and_never_filled(self):
        texts = [close_text(1, index) for index in range(21)]
        for count in (0, 1, 19):
            with self.subTest(count=count):
                values = trend.derive_values(self.rows(texts[-count:] if count else []))
                for name in ("ma20", "return_20d", "close_over_ma20"):
                    self.assertEqual(values[name]["status"], "data_insufficient")
                    self.assertEqual((values[name]["exact"], values[name]["display"]), (None, None))
                    self.assertEqual(values[name]["reasons"], ["ordinary_close_window_insufficient"])
        twenty = trend.derive_values(self.rows(texts[-20:]))
        self.assertEqual(twenty["ma20"]["status"], "available")
        self.assertEqual(twenty["close_over_ma20"]["status"], "available")
        self.assertEqual(twenty["return_20d"]["status"], "data_insufficient")
        self.assertEqual(trend.derive_values(self.rows(texts))["return_20d"]["status"], "available")

    def test_trend_is_never_inferred(self):
        for count in (0, 20, 21):
            trend_entry = trend.derive_values(self.rows([close_text(2, index) for index in range(count)]))["trend"]
            self.assertEqual(trend_entry, {"status": "formula_not_defined", "reasons": ["trend_formula_not_defined"],
                                           "exact": None, "display": None})

    def test_policy_unsupported_list_is_the_pinned_one(self):
        self.assertEqual(list(trend.UNSUPPORTED), policy_unsupported())
        self.assertTrue(set(source.REQUIRED_UNSUPPORTED) <= set(trend.UNSUPPORTED))


class SavedBundleRead(TempRoot):
    def test_all_seven_stocks_match_the_independent_oracle_and_trace_to_the_files(self):
        root = self.new_root()
        closes_bytes, receipt_bytes = write_bundle(root)
        before = tree(root)
        document = json.loads(closes_bytes)
        for stock, symbol in enumerate(SYMBOLS):
            with self.subTest(symbol=symbol):
                result = self.read(root, symbol)
                self.assertEqual((result["version"], result["status"], result["reasons"]), ("ordinary-close-trend/m1-v1", "available", []))
                self.assertEqual((result["exchange"], result["symbol"], result["as_of"]), ("TPEx", symbol, CUTOFF))
                rows = document["closes"][symbol][-21:]
                self.assertEqual(result["closes"], [{"date": day, "close": text} for day, text in rows])
                expected = oracle([text for _, text in rows])
                values = result["values"]
                for name in ("ma20", "return_20d", "close_over_ma20"):
                    self.assertEqual(values[name]["status"], "available")
                    self.assertEqual(values[name]["exact"], expected["exact"][name])
                    self.assertEqual(values[name]["display"], expected["display"][name])
                self.assertEqual(values["latest"], {"date": CUTOFF, "close": rows[-1][1]})
                self.assertEqual((values["ma20"]["window_start"], values["ma20"]["window_end"]), (rows[1][0], CUTOFF))
                self.assertEqual((values["return_20d"]["base_date"], values["return_20d"]["base_close"]), tuple(rows[0]))
                self.assertEqual(values["trend"]["status"], "formula_not_defined")
                self.assertEqual((result["read_state"]["verified"], result["read_state"]["network_requests"], result["read_state"]["writes"]),
                                 (True, 0, 0))
                provenance = result["provenance"]
                self.assertEqual((provenance["closes_sha256"], provenance["receipt_sha256"]), (sha(closes_bytes), sha(receipt_bytes)))
                self.assertEqual(provenance["closes_bytes"], len(closes_bytes))
                self.assertEqual(provenance["source_policy"], {"version": POLICY_VERSION, "sha256": POLICY_SHA, "bytes": POLICY_BYTES})
                self.assertEqual(provenance["saved_at"], json.loads(receipt_bytes)["saved_at"])
                self.assertEqual((provenance["cutoff"], provenance["storage"], provenance["historical_pit"]), (CUTOFF, "private_local", "unsupported"))
                self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]),
                                 ("unknown", "unknown", "unknown"))
                self.assertEqual(provenance["calendar"]["rows"], len(CALENDAR))
                self.assertEqual(provenance["calendar"]["window"], {"start_date": START, "end_date": END})
                self.assertEqual(result["unsupported"], policy_unsupported())
                self.assertEqual(result["limitations"][:6], LIMITATIONS)
                self.assertEqual(result["supported_scope"]["cutoff"], CUTOFF)
                self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertEqual(tree(root), before)  # read-only: bytes, sizes and mtimes unchanged

    def test_stocks_have_distinct_values_and_the_window_is_the_trailing_one(self):
        root = self.new_root()
        write_bundle(root)
        shown = {symbol: self.read(root, symbol)["values"]["ma20"]["display"] for symbol in SYMBOLS}
        self.assertEqual(len(set(shown.values())), 7)
        first = self.read(root, "3105")
        self.assertEqual(first["closes"][0]["date"], WINDOW[-21])
        self.assertEqual(first["values"]["ma20"]["window_start"], WINDOW[-20])

    def test_unsupported_cutoff_or_instrument_never_touches_environment_or_disk(self):
        root = self.new_root()
        write_bundle(root)
        with patch.object(source, "configured_root", side_effect=AssertionError("root read")), \
                patch.object(source, "load_saved_closes", side_effect=AssertionError("file read")):
            for as_of in (None, date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 3)):
                with self.subTest(as_of=as_of):
                    result = self.read(root, "6488", as_of)
                    self.assertEqual((result["status"], result["reasons"]), ("unavailable", ["ordinary_close_cutoff_not_supported"]))
                    self.assertEqual((result["values"], result["closes"], result["provenance"]), (None, [], None))
                    self.assertEqual(result["as_of"], as_of.isoformat() if as_of else None)
                    self.assertFalse(result["read_state"]["verified"])
            for label, changes in (("twse", {"exchange": "TWSE"}), ("etf", {"kind": "etf"}), ("market", {"market": "US"}),
                                   ("category", {"category": "domestic"})):
                with self.subTest(case=label):
                    self.assertEqual(self.read(root, "6488", **changes)["reasons"], ["ordinary_close_instrument_not_supported"])
            for symbol in ("9999", "2330", "3105 ", "00620"):
                with self.subTest(symbol=symbol):
                    self.assertEqual(self.read(root, symbol)["reasons"], ["ordinary_close_instrument_not_supported"])

    def test_root_is_read_per_request_and_unset_or_invalid_fails_closed(self):
        root = self.new_root()
        write_bundle(root)
        empty = self.new_root()
        self.assertEqual(self.read(root)["status"], "available")
        self.assertEqual(self.read(empty)["reasons"], ["ordinary_close_saved_missing"])
        self.assertEqual(self.read(root)["status"], "available")
        subject = instrument()
        for env, reason in (({}, "ordinary_close_root_unset"), ({ROOT_ENV: ""}, "ordinary_close_root_unset"),
                            ({ROOT_ENV: "relative/dir"}, "ordinary_close_root_invalid"),
                            ({ROOT_ENV: os.path.join(root, "..", "x")}, "ordinary_close_root_invalid")):
            with self.subTest(env=env):
                result = trend.read_ordinary_close_trend(subject, date(2026, 10, 6), environment=env)
                self.assertEqual((result["status"], result["reasons"], result["values"]), ("unavailable", [reason], None))
        with patch.dict(os.environ, {ROOT_ENV: root}):
            self.assertEqual(trend.read_ordinary_close_trend(subject, date(2026, 10, 6))["status"], "available")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ROOT_ENV, None)
            self.assertEqual(trend.read_ordinary_close_trend(subject, date(2026, 10, 6))["reasons"], ["ordinary_close_root_unset"])

    def test_other_cutoff_bundle_is_never_used_as_a_fallback(self):
        root = self.new_root()
        write_bundle(root, cutoff="2026-10-05")
        result = self.read(root)
        self.assertEqual((result["status"], result["reasons"], result["values"]), ("unavailable", ["ordinary_close_saved_missing"], None))

    def test_damaged_bundles_fail_closed_with_a_source_reason_and_no_values(self):
        def tamper_close(document):
            document["closes"]["6488"][-1][1] = "999"

        def drop_date(document):
            document["trading_dates"].pop(30)
            for symbol in SYMBOLS:
                document["closes"][symbol].pop(30)
            document["count"] = 59

        def skewed_stock_dates(document):
            document["closes"]["6488"][10][0] = "2026-07-12"

        def wrong_pin(receipt):
            receipt["source_policy"]["sha256"] = "0" * 64

        cases = [
            ("close_changed_after_receipt", dict(closes_fn=tamper_close, restamp=False), "ordinary_close_saved_closes_reference"),
            ("missing_date_in_all_stocks", dict(closes_fn=drop_date), "ordinary_close_saved_shape"),
            ("one_stock_date_differs", dict(closes_fn=skewed_stock_dates), "ordinary_close_saved_dates"),
            ("policy_pin_mismatch", dict(receipt_fn=wrong_pin), "ordinary_close_saved_pin_or_scope"),
        ]
        for label, kwargs, reason in cases:
            with self.subTest(case=label):
                root = self.new_root()
                write_bundle(root, **kwargs)
                result = self.read(root)
                self.assertEqual((result["status"], result["reasons"]), ("unavailable", [reason]))
                self.assertEqual((result["values"], result["closes"], result["provenance"]), (None, [], None))
                self.assertFalse(result["read_state"]["verified"])
        root = self.new_root()
        write_bundle(root)
        final = os.path.join(root, POLICY_VERSION, CUTOFF)
        with open(os.path.join(final, "receipt.json"), "r+b") as handle:
            handle.truncate(100)
        self.assertEqual(self.read(root)["reasons"], ["ordinary_close_saved_parse"])
        shutil.rmtree(root)
        write_bundle(root)
        with open(os.path.join(root, POLICY_VERSION, CUTOFF, "extra.txt"), "wb") as handle:
            handle.write(b"x")
        self.assertEqual(self.read(root)["reasons"], ["ordinary_close_saved_entries"])

    def test_window_that_does_not_end_at_the_cutoff_is_rejected_after_a_valid_load(self):
        root = self.new_root()
        write_bundle(root)
        loaded = source.load_saved_closes(root, POLICY_VERSION, CUTOFF)
        import dataclasses
        shifted = dataclasses.replace(loaded, trading_dates=(("2026-07-10",) + loaded.trading_dates[:-1]))
        with patch.object(source, "load_saved_closes", return_value=shifted):
            result = self.read(root)
        self.assertEqual((result["status"], result["reasons"], result["values"]), ("unavailable", ["ordinary_close_window_mismatch"], None))

    def test_unexpected_io_error_is_a_reason_not_a_value(self):
        root = self.new_root()
        write_bundle(root)
        with patch.object(source, "load_saved_closes", side_effect=PermissionError("denied")):
            result = self.read(root)
        self.assertEqual((result["status"], result["reasons"], result["values"]), ("unavailable", ["ordinary_close_storage_io_failed"], None))

    def test_a_read_opens_no_network_connection(self):
        root = self.new_root()
        write_bundle(root)
        with patch("socket.socket.connect", side_effect=AssertionError("network")), \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            self.assertEqual(self.read(root)["status"], "available")


class RouteTests(TempRoot):
    def setUp(self):
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app import api
        from app.db import Base
        from app.models import Instrument
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            for symbol in SYMBOLS:
                db.add(Instrument(exchange="TPEx", symbol=symbol, name="synthetic " + symbol, instrument_type="stock", market="TW"))
            db.add(Instrument(exchange="TWSE", symbol="3105", name="synthetic twse", instrument_type="stock", market="TW"))
            db.add(Instrument(exchange="TPEx", symbol="9998", name="synthetic other", instrument_type="stock", market="TW"))
            db.commit()
        self.app = FastAPI()
        self.app.include_router(api.router)

        def database():
            with Session(self.engine) as db:
                yield db
        self.app.dependency_overrides[api.get_db] = database
        self.api_routes = api.router.routes

    def snapshot(self):
        with self.engine.connect() as connection:
            names = [row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: [tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{name}" ORDER BY rowid')] for name in names}

    def test_get_matches_the_direct_read_and_changes_nothing(self):
        from fastapi.testclient import TestClient
        root = self.new_root()
        write_bundle(root)
        before, files = self.snapshot(), tree(root)
        with patch.dict(os.environ, {ROOT_ENV: root}), TestClient(self.app) as client:
            for symbol in SYMBOLS:
                response = client.get(f"/api/stocks/TPEx/{symbol}/ordinary-close-trend?as_of=2026-10-06")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), json.loads(json.dumps(self.read(root, symbol))))
                self.assertEqual(response.json()["status"], "available")
            unsupported = [client.get("/api/stocks/TPEx/6488/ordinary-close-trend"),
                           client.get("/api/stocks/TPEx/6488/ordinary-close-trend?as_of=2026-10-05"),
                           client.get("/api/stocks/TPEx/6488/ordinary-close-trend?as_of=2026-10-07")]
            for response in unsupported:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["reasons"], ["ordinary_close_cutoff_not_supported"])
                self.assertIsNone(response.json()["values"])
            twse = client.get("/api/stocks/TWSE/3105/ordinary-close-trend?as_of=2026-10-06")
            self.assertEqual((twse.status_code, twse.json()["reasons"]), (200, ["ordinary_close_instrument_not_supported"]))
            other = client.get("/api/stocks/TPEx/9998/ordinary-close-trend?as_of=2026-10-06")
            self.assertEqual((other.status_code, other.json()["reasons"]), (200, ["ordinary_close_instrument_not_supported"]))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(tree(root), files)

    def test_request_shape_and_method_gates(self):
        from fastapi.testclient import TestClient
        root = self.new_root()
        write_bundle(root)
        path = "/api/stocks/TPEx/6488/ordinary-close-trend"
        with patch.dict(os.environ, {ROOT_ENV: root}), patch.object(source, "load_saved_closes", side_effect=AssertionError("read")), \
                TestClient(self.app) as client:
            for query in ("?as_of=2026-10-06&as_of=2026-10-06", "?as_of=2026-10-06&x=1", "?x=1", "?as_of=not-a-date",
                          "?as_of=", "?as_of=2026-13-40"):
                with self.subTest(query=query):
                    self.assertEqual(client.get(path + query).status_code, 422)
            self.assertEqual(client.get("/api/stocks/TPEx/0000/ordinary-close-trend?as_of=2026-10-06").status_code, 404)
            self.assertEqual(client.get("/api/stocks/TWSE/6488/ordinary-close-trend?as_of=2026-10-06").status_code, 404)
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(method=method):
                    self.assertEqual(getattr(client, method)(path + "?as_of=2026-10-06").status_code, 405)
        routes = [route for route in self.api_routes if getattr(route, "path", "").endswith("/ordinary-close-trend")]
        self.assertEqual([sorted(route.methods) for route in routes], [["GET"]])


if __name__ == "__main__":
    unittest.main()
