"""Standalone synthetic runner for issue 98's calendar / corporate-action source, saved bundle and reader.

Run from the repository root with TMPDIR/TEMP/TMP pointing at a short isolated directory:
  python -I -B -X utf8 backend/tests/test_tpex_calendar_actions_source.py

No source request, no database, no service, no seal, no write to the real private root. Before the
module under test is even imported an audit hook forbids sockets and every write outside this
process's single temporary session directory; subprocesses are allowed only for the fixed
``python -I -B`` reader child. The pinned formal blob d8918bc... is read once with ``git cat-file``
before the hook exists (never the working-tree registry). Every calendar, price and event value
below is synthetic boundary data, not source truth. The policy under test is built here as an
independent literal; the module's real pins are still unset (policy v1 is not yet published), so
every acquiring test names its own pins computed here, never taken from the module.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import http.client
import io
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FORMAL_OBJECT = "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"
FORMAL_SHA = "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"


def _read_pinned_formal_blob():
    """Read the pinned formal blob from git, once, before the audit hook forbids subprocess."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("cannot read pinned formal blob %s: git executable not found" % FORMAL_OBJECT)
    try:
        done = subprocess.run([git, "cat-file", "blob", FORMAL_OBJECT], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("cannot read pinned formal blob %s: git cat-file failed to run (%r)" % (FORMAL_OBJECT, error)) from error
    if done.returncode != 0:
        raise RuntimeError("pinned formal blob %s is unavailable (git cat-file exit %d: %s)"
                           % (FORMAL_OBJECT, done.returncode, done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the runner does not permit bytecode artifacts")
FORMAL = _read_pinned_formal_blob()
assert hashlib.sha256(FORMAL).hexdigest() == FORMAL_SHA
SESSION = tempfile.mkdtemp(prefix="o")  # the only place this process may write
if len(SESSION) > 190:  # final bundle paths add ~70 characters; Windows MAX_PATH is 260
    shutil.rmtree(SESSION)
    raise RuntimeError("point TMPDIR/TEMP/TMP at a shorter directory (session path %d chars)" % len(SESSION))
PYTHON = sys.executable
_CHILD_PREFIX = subprocess.list2cmdline([PYTHON, "-I", "-B"]) + " "
BLOCKED = []
CHILD_ALLOWED = [False]
_APPROVED = os.path.normcase(os.path.abspath(SESSION))
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_APPEND", 0)
_PATH_EVENTS = ("os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.chmod", "os.truncate", "os.utime",
                "os.link", "os.symlink", "os.chown", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
                "shutil.copytree", "shutil.move", "shutil.rmtree")


def _inside(path):
    if isinstance(path, int):
        return True
    try:
        text = os.fsdecode(path)
    except TypeError:
        return False
    full = os.path.normcase(os.path.abspath(text))
    return full == _APPROVED or full.startswith(_APPROVED + os.sep)


def _audit(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname"):
        BLOCKED.append(event)
        raise AssertionError("runner forbids network")
    if event == "subprocess.Popen":
        command = args[1] if len(args) > 1 else None  # Windows hands the audit hook the joined command line
        isolated = (command.startswith(_CHILD_PREFIX) if isinstance(command, str)
                    else isinstance(command, (list, tuple)) and list(command[:3]) == [PYTHON, "-I", "-B"])
        if CHILD_ALLOWED[0] and isolated:
            return
        BLOCKED.append(event)
        raise AssertionError("runner forbids process launch")
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing and not (isinstance(path, str) and os.path.normcase(path) in (os.devnull, "nul")) and not _inside(path):
            BLOCKED.append(event)
            raise AssertionError("runner forbids writes outside its session directory")
    elif event in _PATH_EVENTS:
        for item in args[:2]:
            if isinstance(item, (str, bytes, os.PathLike)) and not _inside(item):
                BLOCKED.append(event)
                raise AssertionError("runner forbids writes outside its session directory")


sys.addaudithook(_audit)
sys.path.insert(0, str(ROOT / "backend"))
from app import ohlcv_history_source as base  # noqa: E402  (imported under the hook: no import-time I/O)
from app import tpex_calendar_actions_source as tca  # noqa: E402

IMPORT_BLOCKED = tuple(BLOCKED)
TCA_FILE = ROOT / "backend/app/tpex_calendar_actions_source.py"
BASE_FILE = ROOT / "backend/app/ohlcv_history_source.py"

NAMESPACE = "issue98-tpex-seven-calendar-actions-v1/qa1"
POLICY_VERSION = "issue98-tpex-seven-calendar-actions-v1"
PURPOSE = "local_personal_noncommercial_private_derived_calendar_actions"
CONSUMER = "tpex-calendar-actions-read-v1"
STORAGE_SCHEMA = "tpex-calendar-actions-saved/v1"
RECEIPT_SCHEMA = "tpex-calendar-actions-receipt/v1"
DATA_PREFIX = "tpex-calendar-actions-data/v1:"
REAL_ROOT = "C:/Users/YiCheng/AppData/Local/taiwan-stock-research/tpex-calendar-actions-issue98"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
CALENDAR_VERSION = "finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue98-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
START, END, DIV_END, IDENTITY = "2026-07-01", "2026-10-12", "2026-12-31", "2026-10-06"
FORMAL_CLOSED = ("2026-09-25", "2026-09-28")
BEYOND = ("2026-10-07", "2026-10-08", "2026-10-12")
ANCHORS = {
    "3105": (615, 623, 588, 592, 19731700, 11863581093),
    "3293": (794, 794, 772, 780, 1495462, 1164617657),
    "5274": (19520, 19895, 18855, 18985, 188693, 3627465565),
    "5347": (184.5, 195, 184.5, 191, 34637793, 6615109776),
    "6488": (1175, 1260, 1145, 1205, 13913614, 16835605385),
    "6510": (3125, 3140, 3050, 3055, 560518, 1729347985),
    "8069": (147, 151.5, 145, 149, 10796741, 1607943663),
}
KINDS = ("price", "dividend_result", "dividend", "capital_reduction", "split", "par_value")
EVENT_KINDS = KINDS[1:]
DATASETS = {"calendar": "TaiwanStockTradingDate", "price": "TaiwanStockPrice",
            "dividend_result": "TaiwanStockDividendResult", "dividend": "TaiwanStockDividend",
            "capital_reduction": "TaiwanStockCapitalReductionReferencePrice", "split": "TaiwanStockSplitPrice",
            "par_value": "TaiwanStockParValueChange", "info": "TaiwanStockInfo"}
SOURCE_IDS = {"calendar": "finmind_trading_dates", "price": "finmind_price", "dividend_result": "finmind_dividend_result",
              "dividend": "finmind_dividend", "capital_reduction": "finmind_capital_reduction",
              "split": "finmind_split_price", "par_value": "finmind_par_value_change", "info": "finmind_stock_info"}
LIMITATIONS = [
    "date_is_asia_taipei_trading_calendar_date_not_utc",
    "july_and_after_2026-10-06_calendar_days_not_independently_verified",
    "no_event_evidence_is_same_provider_internal_consistency_only",
    "suspension_is_indirect_evidence_only_never_a_positive_fact",
    "spread_semantics_inferred_from_data_not_documented",
    "stock_dividend_par_value_10_twd_is_an_inference",
    "reference_price_rounding_unspecified_cross_check_tolerance_is_strictly_less_than_one_tick",
    "stock_info_type_value_form_unverified_until_a_real_response",
    "publication_time_first_availability_revision_time_unknown",
    "raw_body_and_raw_prices_not_stored_derived_values_only",
    "personal_noncommercial_local_use_no_redistribution",
]
UNSUPPORTED = [
    "historical_pit", "publication_time", "first_availability", "revision_guarantee", "positive_suspension_fact",
    "paid_subscription", "provider_adjusted_prices", "other_symbols", "other_markets", "other_dates",
    "raw_body_storage", "redistribution", "actionable_strategy", "plan", "trading", "historical_simulation",
]
RIGHTS = ("FinMind personal noncommercial local private derived calendar and corporate actions; attribution; "
          "no raw body storage, redistribution or mirror")
ATTRIBUTION = ("Source: FinMind (finmindtrade.com) trading dates, daily prices, dividend results, dividends, capital reductions, "
               "split and par-value reference prices and stock info; provider-reported values kept as private local derived "
               "facts; raw bodies not stored or redistributed")

# Synthetic financial-start identities (pure guard only; never passed to an acquiring constructor).
SEAL_ISSUER = "f0000000-0000-0000-0000-0000000000a1"
SEAL_COORDINATORS = ("f0000000-0000-0000-0000-0000000000b1", "f0000000-0000-0000-0000-0000000000b2")
SEAL_IMPLEMENTERS = ("f0000000-0000-0000-0000-0000000000c1", "f0000000-0000-0000-0000-0000000000c2")
QA_HOLDER = "5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d"
SEAL_FLOOR = 6139122796  # the policy v1 publication comment (issue 98): a seal must be newer
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-9999999999"


def canonical(value):
    """Independent stdlib serialization, never the product's helper."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def weekdays(start, stop):
    value, end = date.fromisoformat(start), date.fromisoformat(stop)
    result = []
    while value <= end:
        if value.weekday() < 5:
            result.append(value.isoformat())
        value += timedelta(days=1)
    return tuple(result)


DATES = tuple(day for day in weekdays(START, IDENTITY) if day not in FORMAL_CLOSED) + BEYOND
JULY = weekdays("2026-07-01", "2026-07-31")
PRIOR = tuple(day for day in DATES if "2026-08-01" <= day <= IDENTITY)
assert len(DATES) == 71 and len(JULY) == 23 and len(PRIOR) == 45


def ft(value):
    value = Fraction(value)
    return "%d/%d" % (value.numerator, value.denominator)


def tick_of(price):
    """Independent restatement of the #97 tick ladder (lower bound inclusive)."""
    price = Fraction(price)
    if price < 10:
        return Fraction(1, 100)
    if price < 50:
        return Fraction(1, 20)
    if price < 100:
        return Fraction(1, 10)
    if price < 500:
        return Fraction(1, 2)
    if price < 1000:
        return Fraction(1)
    return Fraction(5)


def nearest(price):
    """The price rounded to the nearest tick-grid value, as a float for a JSON body."""
    price = Fraction(price)
    tick = tick_of(price)
    return float(round(price / tick) * tick)


# --- policy: an independent literal of what the module implements ------------------------------------

def _source(dataset, data_id, start, end, gets, required, optional, per_symbol=True):
    query = "dataset=" + dataset + ("&data_id={symbol}" if data_id else "")
    if start:
        query += "&start_date=" + start
    if end:
        query += "&end_date=" + end
    return {"dataset": dataset, "data_id": data_id, "start_date": start, "end_date": end, "gets": gets,
            "url": ENDPOINT + "?" + query, "required_fields": required, "optional_fields": optional}


def policy_dict():
    return {
        "version": POLICY_VERSION, "profile": "free_public_local", "source_use": PURPOSE, "consumer_version": CONSUMER,
        "market": "TW/TPEx", "instrument_type": "ordinary_stock", "symbols": list(SYMBOLS), "identity_as_of": IDENTITY,
        "window": {"start_date": START, "end_date": END, "dividend_end_date": DIV_END},
        "sources": {
            "calendar": _source("TaiwanStockTradingDate", False, START, END, 1, ["date"], []),
            "price": _source("TaiwanStockPrice", True, START, END, 7,
                             ["date", "stock_id", "open", "max", "min", "close", "Trading_Volume", "Trading_money"],
                             ["spread", "Trading_turnover"]),
            "dividend_result": _source("TaiwanStockDividendResult", True, START, END, 7,
                                       ["date", "stock_id", "before_price", "after_price", "reference_price"],
                                       ["stock_and_cache_dividend", "stock_or_cache_dividend", "max_price", "min_price", "open_price"]),
            "dividend": _source("TaiwanStockDividend", True, START, DIV_END, 7, ["date", "stock_id"],
                                ["StockExDividendTradingDate", "CashExDividendTradingDate", "StockEarningsDistribution",
                                 "StockStatutorySurplus", "CashEarningsDistribution", "CashStatutorySurplus",
                                 "TotalNumberOfCashCapitalIncrease", "CashIncreaseSubscriptionRate",
                                 "CashIncreaseSubscriptionpRrice", "AnnouncementDate", "AnnouncementTime"]),
            "capital_reduction": _source("TaiwanStockCapitalReductionReferencePrice", True, START, END, 7,
                                         ["date", "stock_id", "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice"],
                                         ["LimitUp", "LimitDown", "OpeningReferencePrice", "ExrightReferencePrice",
                                          "ReasonforCapitalReduction"]),
            "split": _source("TaiwanStockSplitPrice", True, START, END, 7, ["date", "stock_id", "before_price", "after_price"],
                             ["type", "max_price", "min_price", "open_price"]),
            "par_value": _source("TaiwanStockParValueChange", True, START, END, 7,
                                 ["date", "stock_id", "before_close", "after_ref_close"],
                                 ["stock_name", "after_ref_max", "after_ref_min", "after_ref_open"]),
            "info": _source("TaiwanStockInfo", False, "", "", 1, ["stock_id", "type", "date"],
                            ["industry_category", "stock_name"]),
        },
        "calendar": {
            "version": CALENDAR_VERSION, "prior_calendar_formal_blob": FORMAL_OBJECT, "prior_calendar_formal_sha256": FORMAL_SHA,
            "prior_verified_counts": {"August": 21, "September": 20, "October_through_6": 4},
            "expected_scope": "observed FinMind trading dates; every returned row structurally valid, unique and ascending; "
                              "rows outside the window are discarded only after structural validation; in-window dates must be "
                              "weekdays, include 2026-10-06 and equal the formal Aug-Oct 45 dates exactly within that span; July "
                              "and days after 2026-10-06 are accepted as returned; no fixed count; no closure inference",
        },
        "checks": {
            "spread_min_matched_days": 20, "stock_dividend_par_twd": 10, "info_accepted_types": ["tpex"],
            "spread_reference": "implied reference = close - spread must equal the previous comparable close unless an event "
                                "dated that day explains the difference; unexplained difference refuses the adjusted basis",
            "spread_semantics_demonstration": "at least one event day across the seven symbols whose implied reference differs "
                                              "from the previous comparable close; otherwise every symbol is semantics_unverified",
            "zero_price_rows": "a missing row or zero OHLC makes the day incomparable; it never fails the batch and is never "
                               "asserted to be a suspension",
            "identity_anchor": "2026-10-06 six-field anchors of SOURCE_REGISTRY 32.2 must equal the price row, else the symbol "
                               "is refused",
            "dividend_factor": "(P-C)/P*1/(1+Rf) with P=before_price, C and Rf from the matching TaiwanStockDividend row; exact "
                               "rationals; Rf = stock dividend per share / 10 TWD par",
            "reference_ratio_factor": "after_reference/before_close for capital reduction, split and par-value change",
            "paid_subscription": "a positive capital-increase field makes the event unsupported; no parameter is estimated",
            "same_day_events": "more than one event on one date makes all of them unsupported",
            "reference_tick_ladder": ["0=1/100", "10=1/20", "50=1/10", "100=1/2", "500=1", "1000=5"],
            "reference_tick_source": "tick ladder of SOURCE_REGISTRY #97 (tpex-static-rules/2026-10-12/v1, business rules article 55 "
                                     "paragraph 2, lower bound inclusive); the tolerance is the tick at the observed reference price",
            "reference_cross_check": "an ex-dividend factor implies R=(P-C)/(1+Rf); R must be strictly less than one tick from the "
                                     "TaiwanStockDividendResult reference_price and, when the event day has a comparable price row with "
                                     "spread, from close-spread; capital reduction, split and par-value after_reference must be strictly "
                                     "less than one tick from close-spread (no such row: factor_reference_unverified); a miss makes the "
                                     "event unsupported with factor_reference_mismatch and never fails the batch; official rounding of "
                                     "reference prices is not stated by the sources, hence strictly less than one tick, not equality",
        },
        "storage": {
            "kind": "private_local_derived_calendar_actions", "schema": STORAGE_SCHEMA, "root": REAL_ROOT,
            "layout": "<policy_version>/<window_end>/{data.json,receipt.json}", "raw_body": "not_stored",
            "stored": "calendar, per-symbol day states, events, factors, traces and check results; no raw prices",
            "max_data_bytes": 131072, "max_receipt_bytes": 65536, "max_bundles": 1, "max_files": 2, "max_total_bytes": 196608,
        },
        "acquisition": {
            "namespace": NAMESPACE,
            "order": "calendar, then per dataset the seven symbols ascending (price, dividend_result, dividend, "
                     "capital_reduction, split, par_value), then stock info",
            "max_gets": 44, "per_source_max_gets": 1, "body_cap_bytes": 1048576, "total_raw_cap_bytes": 16777216,
            "retained_roots_estimate_cap_bytes": 33554432, "request_seconds": 20, "batch_seconds": 600,
            "deadline": "cooperative", "accept_encoding": "identity", "accept": "application/json",
            "user_agent": "stock-lab-issue32-local-ram/1", "redirects": 0, "retries": 0, "stop_on_first_failure": True,
        },
        "response_shape": {
            "status": "200 only; 401/402/403 or any paid/login response is first failure",
            "content_type": "application/json with or without charset=utf-8; anything else rejects",
            "framing": "content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked "
                       "together rejects; cap reached without EOF rejects",
            "content_encoding": "identity or absent; gzip/br rejects (accepted risk)",
            "duplicate_identity_headers": "content-length, content-encoding, transfer-encoding, content-type duplicates reject; "
                                          "other duplicate headers accepted and ignored",
            "set_cookie": "accepted, never stored or sent", "encoding": "strict UTF-8 without BOM",
            "empty_data": "data [] is not a failure; the dataset simply has no rows",
            "structure": "status/msg/data document; required fields present with the stated types; unknown extra fields tolerated "
                         "and only their names recorded",
        },
        "attribution": ATTRIBUTION, "rights": RIGHTS,
        "documentation": "https://finmind.github.io/tutor/TaiwanMarket/ (doc GET receipt issue98 comment 6135101980); free tokenless "
                         "use is inferred, 401/402/403 is first failure; TaiwanStockSuspended and TaiwanStockPriceAdj are "
                         "member-only and not used; TaiwanStockDividend amount field names (StockEarningsDistribution, "
                         "StockStatutorySurplus, CashEarningsDistribution, CashStatutorySurplus) are schema names on the Fundamental "
                         "page (SHA-256 801b4f41573ac3388c4c684fd6fe4939bb15427b332234a741a79e0e6d9977c7); the TaiwanStockInfo type "
                         "tpex follows the Technical page note that the table keeps both emerging and twse / tpex rows (SHA-256 "
                         "6f8747b5fbaa9ba13708bf1a546f7368e460fc59ccd86bd5c78690c10aa52ea5), the real value form is unverified",
        "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
        "unsupported": list(UNSUPPORTED),
    }


def policy_pack(document=None):
    blob = canonical(policy_dict() if document is None else document)
    return blob, tca.Pins(hashlib.sha256(blob).hexdigest(), len(blob))


# Policy v1 exactly as published in issue 98 comment 6139122796 (10,257 bytes; sorted keys, compact, no trailing LF).
PUBLISHED_POLICY = b'{"acquisition":{"accept":"application/json","accept_encoding":"identity","batch_seconds":600,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":44,"namespace":"issue98-tpex-seven-calendar-actions-v1/qa1","order":"calendar, then per dataset the seven symbols ascending (price, dividend_result, dividend, capital_reduction, split, par_value), then stock info","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":16777216,"user_agent":"stock-lab-issue32-local-ram/1"},"attribution":"Source: FinMind (finmindtrade.com) trading dates, daily prices, dividend results, dividends, capital reductions, split and par-value reference prices and stock info; provider-reported values kept as private local derived facts; raw bodies not stored or redistributed","calendar":{"expected_scope":"observed FinMind trading dates; every returned row structurally valid, unique and ascending; rows outside the window are discarded only after structural validation; in-window dates must be weekdays, include 2026-10-06 and equal the formal Aug-Oct 45 dates exactly within that span; July and days after 2026-10-06 are accepted as returned; no fixed count; no closure inference","prior_calendar_formal_blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","prior_calendar_formal_sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde","prior_verified_counts":{"August":21,"October_through_6":4,"September":20},"version":"finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue98-v1"},"checks":{"dividend_factor":"(P-C)/P*1/(1+Rf) with P=before_price, C and Rf from the matching TaiwanStockDividend row; exact rationals; Rf = stock dividend per share / 10 TWD par","identity_anchor":"2026-10-06 six-field anchors of SOURCE_REGISTRY 32.2 must equal the price row, else the symbol is refused","info_accepted_types":["tpex"],"paid_subscription":"a positive capital-increase field makes the event unsupported; no parameter is estimated","reference_cross_check":"an ex-dividend factor implies R=(P-C)/(1+Rf); R must be strictly less than one tick from the TaiwanStockDividendResult reference_price and, when the event day has a comparable price row with spread, from close-spread; capital reduction, split and par-value after_reference must be strictly less than one tick from close-spread (no such row: factor_reference_unverified); a miss makes the event unsupported with factor_reference_mismatch and never fails the batch; official rounding of reference prices is not stated by the sources, hence strictly less than one tick, not equality","reference_ratio_factor":"after_reference/before_close for capital reduction, split and par-value change","reference_tick_ladder":["0=1/100","10=1/20","50=1/10","100=1/2","500=1","1000=5"],"reference_tick_source":"tick ladder of SOURCE_REGISTRY #97 (tpex-static-rules/2026-10-12/v1, business rules article 55 paragraph 2, lower bound inclusive); the tolerance is the tick at the observed reference price","same_day_events":"more than one event on one date makes all of them unsupported","spread_min_matched_days":20,"spread_reference":"implied reference = close - spread must equal the previous comparable close unless an event dated that day explains the difference; unexplained difference refuses the adjusted basis","spread_semantics_demonstration":"at least one event day across the seven symbols whose implied reference differs from the previous comparable close; otherwise every symbol is semantics_unverified","stock_dividend_par_twd":10,"zero_price_rows":"a missing row or zero OHLC makes the day incomparable; it never fails the batch and is never asserted to be a suspension"},"consumer_version":"tpex-calendar-actions-read-v1","documentation":"https://finmind.github.io/tutor/TaiwanMarket/ (doc GET receipt issue98 comment 6135101980); free tokenless use is inferred, 401/402/403 is first failure; TaiwanStockSuspended and TaiwanStockPriceAdj are member-only and not used; TaiwanStockDividend amount field names (StockEarningsDistribution, StockStatutorySurplus, CashEarningsDistribution, CashStatutorySurplus) are schema names on the Fundamental page (SHA-256 801b4f41573ac3388c4c684fd6fe4939bb15427b332234a741a79e0e6d9977c7); the TaiwanStockInfo type tpex follows the Technical page note that the table keeps both emerging and twse / tpex rows (SHA-256 6f8747b5fbaa9ba13708bf1a546f7368e460fc59ccd86bd5c78690c10aa52ea5), the real value form is unverified","first_availability":"unknown","identity_as_of":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","profile":"free_public_local","publication_time":"unknown","response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","empty_data":"data [] is not a failure; the dataset simply has no rows","encoding":"strict UTF-8 without BOM","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure","structure":"status/msg/data document; required fields present with the stated types; unknown extra fields tolerated and only their names recorded"},"revision_time":"unknown","rights":"FinMind personal noncommercial local private derived calendar and corporate actions; attribution; no raw body storage, redistribution or mirror","source_use":"local_personal_noncommercial_private_derived_calendar_actions","sources":{"calendar":{"data_id":false,"dataset":"TaiwanStockTradingDate","end_date":"2026-10-12","gets":1,"optional_fields":[],"required_fields":["date"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate&start_date=2026-07-01&end_date=2026-10-12"},"capital_reduction":{"data_id":true,"dataset":"TaiwanStockCapitalReductionReferencePrice","end_date":"2026-10-12","gets":7,"optional_fields":["LimitUp","LimitDown","OpeningReferencePrice","ExrightReferencePrice","ReasonforCapitalReduction"],"required_fields":["date","stock_id","ClosingPriceonTheLastTradingDay","PostReductionReferencePrice"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockCapitalReductionReferencePrice&data_id={symbol}&start_date=2026-07-01&end_date=2026-10-12"},"dividend":{"data_id":true,"dataset":"TaiwanStockDividend","end_date":"2026-12-31","gets":7,"optional_fields":["StockExDividendTradingDate","CashExDividendTradingDate","StockEarningsDistribution","StockStatutorySurplus","CashEarningsDistribution","CashStatutorySurplus","TotalNumberOfCashCapitalIncrease","CashIncreaseSubscriptionRate","CashIncreaseSubscriptionpRrice","AnnouncementDate","AnnouncementTime"],"required_fields":["date","stock_id"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDividend&data_id={symbol}&start_date=2026-07-01&end_date=2026-12-31"},"dividend_result":{"data_id":true,"dataset":"TaiwanStockDividendResult","end_date":"2026-10-12","gets":7,"optional_fields":["stock_and_cache_dividend","stock_or_cache_dividend","max_price","min_price","open_price"],"required_fields":["date","stock_id","before_price","after_price","reference_price"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDividendResult&data_id={symbol}&start_date=2026-07-01&end_date=2026-10-12"},"info":{"data_id":false,"dataset":"TaiwanStockInfo","end_date":"","gets":1,"optional_fields":["industry_category","stock_name"],"required_fields":["stock_id","type","date"],"start_date":"","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"},"par_value":{"data_id":true,"dataset":"TaiwanStockParValueChange","end_date":"2026-10-12","gets":7,"optional_fields":["stock_name","after_ref_max","after_ref_min","after_ref_open"],"required_fields":["date","stock_id","before_close","after_ref_close"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockParValueChange&data_id={symbol}&start_date=2026-07-01&end_date=2026-10-12"},"price":{"data_id":true,"dataset":"TaiwanStockPrice","end_date":"2026-10-12","gets":7,"optional_fields":["spread","Trading_turnover"],"required_fields":["date","stock_id","open","max","min","close","Trading_Volume","Trading_money"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={symbol}&start_date=2026-07-01&end_date=2026-10-12"},"split":{"data_id":true,"dataset":"TaiwanStockSplitPrice","end_date":"2026-10-12","gets":7,"optional_fields":["type","max_price","min_price","open_price"],"required_fields":["date","stock_id","before_price","after_price"],"start_date":"2026-07-01","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockSplitPrice&data_id={symbol}&start_date=2026-07-01&end_date=2026-10-12"}},"storage":{"kind":"private_local_derived_calendar_actions","layout":"<policy_version>/<window_end>/{data.json,receipt.json}","max_bundles":1,"max_data_bytes":131072,"max_files":2,"max_receipt_bytes":65536,"max_total_bytes":196608,"raw_body":"not_stored","root":"C:/Users/YiCheng/AppData/Local/taiwan-stock-research/tpex-calendar-actions-issue98","schema":"tpex-calendar-actions-saved/v1","stored":"calendar, per-symbol day states, events, factors, traces and check results; no raw prices"},"symbols":["3105","3293","5274","5347","6488","6510","8069"],"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","positive_suspension_fact","paid_subscription","provider_adjusted_prices","other_symbols","other_markets","other_dates","raw_body_storage","redistribution","actionable_strategy","plan","trading","historical_simulation"],"version":"issue98-tpex-seven-calendar-actions-v1","window":{"dividend_end_date":"2026-12-31","end_date":"2026-10-12","start_date":"2026-07-01"}}'
PUBLISHED_SHA = "fcdc77c4dd0c752da9a75bc3f5fe334d9ab61edfe8c903849af6466db55d2724"  # as quoted in that comment
PUBLISHED_BYTES = 10257
PUBLISHED_COMMENT = 6139122796
assert len(PUBLISHED_POLICY) == PUBLISHED_BYTES and hashlib.sha256(PUBLISHED_POLICY).hexdigest() == PUBLISHED_SHA
assert canonical(policy_dict()) == PUBLISHED_POLICY


# --- synthetic corpus ---------------------------------------------------------------------------------

def step_index(kind, symbol=None):
    if kind == "calendar":
        return 0
    if kind == "info":
        return 43
    return 1 + KINDS.index(kind) * 7 + SYMBOLS.index(symbol)


def step_url(kind, symbol=None):
    if kind == "calendar":
        return f"{ENDPOINT}?dataset=TaiwanStockTradingDate&start_date={START}&end_date={END}"
    if kind == "info":
        return f"{ENDPOINT}?dataset=TaiwanStockInfo"
    end = DIV_END if kind == "dividend" else END
    return f"{ENDPOINT}?dataset={DATASETS[kind]}&data_id={symbol}&start_date={START}&end_date={end}"


def body_of(document):
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf8")


def ok(rows):
    return {"status": 200, "msg": "success", "data": rows}


class Corpus:
    """Seven coherent price series (spread = close - reference), one cash ex-dividend per symbol, TPEx info rows."""

    def __init__(self, adjust=True):
        self.dates = DATES
        self.event_day = {symbol: DATES[20 + 3 * index] for index, symbol in enumerate(SYMBOLS)}
        self.cash = {symbol: 1.5 + index for index, symbol in enumerate(SYMBOLS)}
        self.rows, self.prior = {}, {}
        for index, symbol in enumerate(SYMBOLS):
            rows, prior = [], None
            for position, day in enumerate(self.dates):
                close = 100 + index * 10 + (position % 7) * 0.5
                values = {"open": close, "max": close + 2, "min": close - 2, "close": close,
                          "Trading_Volume": 1000 + position * 3, "Trading_money": 100000 + position * 13}
                if day == IDENTITY:
                    o, h, l, c, v, a = ANCHORS[symbol]
                    values.update(open=o, max=h, min=l, close=c, Trading_Volume=v, Trading_money=a)
                    close = c
                if prior is None:
                    reference = close
                elif day == self.event_day[symbol]:
                    self.prior[symbol] = prior
                    reference = prior - self.cash[symbol] if adjust else prior  # adjust=False: raw previous-close spread
                else:
                    reference = prior
                rows.append({"date": day, "stock_id": symbol, **values, "spread": close - reference, "Trading_turnover": 2})
                prior = close
            self.rows[symbol] = rows
        self.docs = [None] * 44
        self.docs[0] = ok([{"date": day} for day in self.dates])
        for symbol in SYMBOLS:
            self.docs[step_index("price", symbol)] = ok(self.rows[symbol])
            day, cash, prior = self.event_day[symbol], self.cash[symbol], self.prior[symbol]
            self.docs[step_index("dividend_result", symbol)] = ok([{
                "date": day, "stock_id": symbol, "before_price": prior, "after_price": prior - cash,
                "stock_and_cache_dividend": cash, "stock_or_cache_dividend": "息", "max_price": prior * 1.1,
                "min_price": prior * 0.9, "open_price": prior - cash, "reference_price": prior - cash}])
            self.docs[step_index("dividend", symbol)] = ok([{
                "date": DATES[24 + 3 * SYMBOLS.index(symbol)], "stock_id": symbol, "year": "2026",
                "StockExDividendTradingDate": "", "CashExDividendTradingDate": day,
                "StockEarningsDistribution": 0, "StockStatutorySurplus": 0, "CashEarningsDistribution": cash,
                "CashStatutorySurplus": 0, "TotalNumberOfCashCapitalIncrease": 0, "CashIncreaseSubscriptionRate": 0,
                "CashIncreaseSubscriptionpRrice": 0, "AnnouncementDate": "2026-07-20", "AnnouncementTime": "15:30:00"}])
            for kind in ("capital_reduction", "split", "par_value"):
                self.docs[step_index(kind, symbol)] = ok([])
        info = [{"industry_category": "電子", "stock_id": symbol, "stock_name": "N" + symbol, "type": "tpex",
                 "date": "2026-09-30"} for symbol in SYMBOLS]
        info += [{"industry_category": "金融", "stock_id": "2330", "stock_name": "X", "type": "twse", "date": "2026-09-30"},
                 {"industry_category": "電子", "stock_id": "3105", "stock_name": "N3105", "type": "emerging", "date": "2020-01-01"}]
        self.docs[43] = ok(info)

    @property
    def bodies(self):
        return [body_of(document) for document in self.docs]

    def edit(self, kind, symbol, function):
        function(self.docs[step_index(kind, symbol)])
        return self

    def event_dict(self, symbol):
        day, cash, prior = self.event_day[symbol], Fraction(str(self.cash[symbol])), Fraction(str(self.prior[symbol]))
        factor = (prior - cash) / prior
        reference, tick = prior - cash, ft(tick_of(prior - cash))
        return {"kind": "ex_dividend", "date": day, "dataset": "dividend_result", "announced_date": "2026-07-20",
                "announced_time": "15:30:00", "before": ft(prior), "reference": ft(prior - cash), "factor": ft(factor),
                "formula": "(P-C)/P*1/(1+Rf)",
                "trace": {"P": ft(prior), "C": ft(cash), "Rf": "0/1", "par_twd": "10", "reference_ratio": ft(factor),
                          "R": ft(reference), "f3_reference": ft(reference), "f3_diff": "0/1", "f3_tick": tick,
                          "spread_reference": ft(reference), "spread_diff": "0/1", "spread_tick": tick},
                "supported": True, "reasons": []}

    def expected_symbol(self, symbol):
        day = self.event_day[symbol]
        checked = len(self.dates) - 1
        return {"status": "usable", "refusal_reasons": [], "info": {"type": "tpex", "date": "2026-09-30"},
                "incomparable_days": [],
                "spread_check": {"status": "consistent", "checked": checked, "matched": checked - 1,
                                 "mismatch_dates": [day], "unexplained_dates": [], "demonstrating_dates": [day]},
                "events": [self.event_dict(symbol)], "adjusted": {"supported_from": self.dates[0], "reasons": []},
                "foreign_rows": {kind: 0 for kind in EVENT_KINDS}}

    def observed(self):
        result = {}
        for kind in (kind for kind in DATASETS if kind != "calendar"):
            seen = set()
            indexes = [step_index(kind)] if kind == "info" else [step_index(kind, symbol) for symbol in SYMBOLS]
            for index in indexes:
                for row in self.docs[index]["data"]:
                    seen.update(row)
            result[kind] = sorted(seen)
        return result

    def expected_data(self):
        symbols = {symbol: self.expected_symbol(symbol) for symbol in SYMBOLS}
        return {"schema": STORAGE_SCHEMA, "window": {"start_date": START, "end_date": END, "dividend_end_date": DIV_END},
                "calendar": list(self.dates), "calendar_after_formal": list(BEYOND),
                "spread_semantics": {"demonstrated": True,
                                     "evidence": sorted([symbol, self.event_day[symbol]] for symbol in SYMBOLS)},
                "observed_fields": self.observed(), "symbols": symbols}

    def data_sha(self):
        return hashlib.sha256(canonical(self.expected_data())).hexdigest()


# --- harness -------------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


JSON_TYPE = (("Content-Type", "application/json"),)


class Response:
    def __init__(self, body, *, declared=True, eof=True, clock=None, read_delay=0, status=200, headers=None,
                 close_raises=False):
        self.body = body
        self.offset = 0
        self.status = status
        self.headers = headers if headers is not None else (
            ((("Content-Length", str(len(body))),) if declared else ()) + JSON_TYPE)
        self.closed = False
        self.eof_enabled = eof
        self.clock = clock
        self.read_delay = read_delay
        self.read_calls = []
        self.close_raises = close_raises
        self.close_calls = 0

    @property
    def known_eof(self):
        return self.eof_enabled and self.offset == len(self.body)

    def read(self, count, timeout):
        self.read_calls.append((count, timeout))
        assert count > 0
        if self.clock:
            self.clock.now += self.read_delay
        chunk = self.body[self.offset:self.offset + count]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True
        self.close_calls += 1
        if self.close_raises:
            raise OSError("DO_NOT_RETAIN_RAW" * 1000)


class Transport:
    def __init__(self, bodies, *, response_options=None, clock=None, open_delay=0, fail_at=None):
        self.bodies = bodies
        self.response_options = response_options or {}
        self.clock, self.open_delay, self.fail_at = clock, open_delay, fail_at
        self.opens = []
        self.responses = []

    def open(self, url, timeout):
        index = len(self.opens)
        self.opens.append((url, timeout))
        if self.clock:
            self.clock.now += self.open_delay
        if index == self.fail_at:
            raise OSError("synthetic transport failure")
        response = Response(self.bodies[index], **self.response_options.get(index, {}))
        self.responses.append(response)
        return response


def build(*, corpus=None, bodies=None, transport=None, clock=None, ledger=None, blob_pins=None, **kwargs):
    corpus = corpus or Corpus()
    blob, pins = blob_pins or policy_pack()
    transport = transport or Transport(bodies if bodies is not None else corpus.bodies)
    clock = clock or Clock()
    source = tca.CalendarActionsSource(policy_canonical=blob, policy_sha256=pins.sha256, pins=pins, formal_blob=FORMAL,
                                       transport=transport, ledger=ledger or tca.AttemptLedger(NAMESPACE), clock=clock, **kwargs)
    return source, transport, clock


def receipt_hash(receipt):
    return hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest()


def admission(source, corpus, **changes):
    proof = tca.OracleAdmission(
        NAMESPACE, source._pins.sha256, "synthetic-boundary-oracle", "a" * 40, "b" * 64,
        tuple(receipt_hash(capture.receipt) for capture in source.inspection()["captures"]),
        len(DATES), 7 * len(DATES), 7, corpus.data_sha(), True)
    return replace(proof, **changes) if changes else proof


def acquired(**kwargs):
    source, transport, clock = build(**kwargs)
    source.acquire()
    return source, transport, clock


def available(**kwargs):
    corpus = kwargs.setdefault("corpus", Corpus())
    source, transport, clock = acquired(**kwargs)
    source.admit_independent_verification(admission(source, corpus))
    return source, transport, clock


def data_of(source):
    return json.loads(source.inspection()["data_bytes"])


def declaration(holder=QA_HOLDER, model="claude-sonnet-5-5", url=SEAL_URL):
    binding = tca.ExecutionBinding(holder, holder, None, model, "xhigh", "a" * 40, "b" * 64, "c" * 64,
                                   "NOAUTH RAM pure guard; no financial execution")
    start = tca.FinancialStart("issue98-financial-start-v1", SEAL_ISSUER, SEAL_COORDINATORS, SEAL_IMPLEMENTERS,
                               NAMESPACE, policy_pack()[1].sha256, url, binding, True, True)
    return start, binding


# Response-shape replay: canned wire bytes -> real http.client parsing -> the real _HTTPSTransport.open /
# _HTTPSResponse / this module's _capture. Only socket and TLS are replaced.
class ReplayFile(io.BytesIO):
    """Response file whose .raw._sock mirrors socket.SocketIO as in the stdlib path."""


class ReplaySocket:
    def __init__(self, wire):
        self.wire = wire
        self.timeouts = []

    def makefile(self, mode="rb", *args, **kwargs):
        stream = ReplayFile(self.wire)
        stream.raw = types.SimpleNamespace(_sock=self)
        return stream

    def settimeout(self, value):
        self.timeouts.append(value)


class ReplayTransport:
    def __init__(self, wires):
        self.wires = list(wires)
        self.opens = []
        self.requests = []

    def open(self, url, timeout):
        wire = self.wires[len(self.opens)]
        self.opens.append(url)
        owner = self

        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.sock = host, ReplaySocket(wire)

            def connect(self):
                pass

            def request(self, method, target, headers):
                owner.requests.append((self.host, method, target, dict(headers)))

            def getresponse(self):
                response = http.client.HTTPResponse(self.sock, method="GET")
                response.begin()
                if response.will_close:  # stdlib hands the socket to the response
                    self.sock = None
                return response

            def close(self):
                self.sock = None

        with patch.object(base.http.client, "HTTPSConnection", Connection), \
                patch.object(base.ssl, "create_default_context", lambda: object()):
            return base._HTTPSTransport().open(url, timeout)


def chunk_encode(body, size=61):
    out = b""
    for offset in range(0, len(body), size):
        part = body[offset:offset + size]
        out += b"%x\r\n" % len(part) + part + b"\r\n"
    return out + b"0\r\n\r\n"


def finmind_wire(body, *, framing="length", content_type="application/json", extra=(), status=200, reason="OK",
                 content_encoding=None):
    headers = [("Date", "Mon, 12 Oct 2026 00:00:00 GMT"), ("Server", "synthetic"), ("Vary", "Accept-Encoding")]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    wire = body
    if framing == "length":
        headers.append(("Content-Length", str(len(body))))
    elif framing == "chunked":
        headers.append(("Transfer-Encoding", "chunked"))
        wire = chunk_encode(body)
    elif framing == "both":
        headers += [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")]
        wire = chunk_encode(body)
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    head = f"HTTP/1.1 {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers + list(extra)) + "\r\n"
    return head.encode("utf-8") + wire


_counter = [0]
EXPECTED_BLOCKED = [0]


def _cheap_roots(self, *stage_roots):
    """Stand-in outside the roots tests: the real per-row walk of the whole object graph costs seconds per acquisition."""
    self._roots_estimate = 0


class Case(unittest.TestCase):
    real_roots_tests = ()  # test methods that run the product's real retained-roots accounting

    def setUp(self):
        self.addCleanup(self._assert_no_residue)  # registered first, so it runs last
        if self._testMethodName not in self.real_roots_tests:
            patcher = patch.object(tca.CalendarActionsSource, "_check_roots", _cheap_roots)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _assert_no_residue(self):
        self.assertEqual(os.listdir(SESSION), [], "session directory must be empty after each test")

    def new_dir(self):
        _counter[0] += 1
        path = os.path.join(SESSION, "t%d" % _counter[0])
        os.mkdir(path)
        self.addCleanup(self._remove, path)
        return path

    def new_root(self):
        """A not-yet-existing private root below a fresh session subdirectory."""
        return os.path.join(self.new_dir(), "r")

    @staticmethod
    def _remove(path):
        if os.path.lexists(path):
            shutil.rmtree(path)

    def assertFailure(self, expected, function, *args, **kwargs):
        with self.assertRaises(tca.SourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def tree(self, root):
        """Sorted (relative path, size) listing of every file and directory below ``root``."""
        found = []
        for folder, names, files in os.walk(root):
            for name in names:
                found.append((os.path.relpath(os.path.join(folder, name), root), None))
            for name in files:
                full = os.path.join(folder, name)
                found.append((os.path.relpath(full, root), os.path.getsize(full)))
        return sorted(found)



# --- policy, constructor and seal guards -----------------------------------------------------------------

TEXT_LEAVES = {
    ("calendar", "version"), ("calendar", "expected_scope"), ("attribution",), ("rights",), ("documentation",),
    ("checks", "spread_reference"), ("checks", "spread_semantics_demonstration"), ("checks", "zero_price_rows"),
    ("checks", "identity_anchor"), ("checks", "dividend_factor"), ("checks", "reference_ratio_factor"),
    ("checks", "paid_subscription"), ("checks", "same_day_events"), ("checks", "reference_tick_source"),
    ("checks", "reference_cross_check"),
} | {("response_shape", key) for key in policy_dict()["response_shape"]}


def leaf_paths(node, prefix=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaf_paths(value, prefix + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from leaf_paths(value, prefix + (index,))
    else:
        yield prefix


def get_path(document, path):
    for key in path:
        document = document[key]
    return document


def set_path(document, path, value):
    get_path(document, path[:-1])[path[-1]] = value


class PolicyAndGates(Case):
    def test_import_is_inert_and_the_module_constants_are_the_independent_literals(self):
        self.assertEqual(IMPORT_BLOCKED, ())
        self.assertEqual((tca.POLICY_SHA256, tca.POLICY_BYTES, tca.SEAL_COMMENT_FLOOR),
                         (PUBLISHED_SHA, PUBLISHED_BYTES, PUBLISHED_COMMENT))
        self.assertEqual((tca.NAMESPACE, tca.POLICY_VERSION, tca.PURPOSE, tca.CONSUMER_VERSION),
                         (NAMESPACE, POLICY_VERSION, PURPOSE, CONSUMER))
        self.assertEqual((tca.STORAGE_SCHEMA, tca.RECEIPT_SCHEMA, tca.DATA_VERSION_PREFIX), (STORAGE_SCHEMA, RECEIPT_SCHEMA, DATA_PREFIX))
        self.assertEqual(tca.PRIVATE_ROOT, REAL_ROOT)
        self.assertEqual((tca.WINDOW_START, tca.WINDOW_END, tca.DIVIDEND_END, tca.IDENTITY_AS_OF), (START, END, DIV_END, IDENTITY))
        self.assertEqual((tca.BODY_CAP, tca.RAW_CAP, tca.ROOTS_CAP, tca.REQUEST_SECONDS, tca.BATCH_SECONDS, tca.MAX_GETS),
                         (1048576, 16777216, 33554432, 20, 600, 44))
        self.assertEqual((tca.DATA_CAP, tca.RECEIPT_CAP, tca.MAX_BUNDLES, tca.MAX_FILES, tca.MAX_TOTAL_BYTES),
                         (131072, 65536, 1, 2, 196608))
        self.assertEqual((tca.SPREAD_MIN_MATCHED_DAYS, tca.STOCK_DIVIDEND_PAR_TWD, tca.INFO_ACCEPTED_TYPES), (20, 10, ("tpex",)))
        self.assertEqual(list(tca.LIMITATIONS), LIMITATIONS)
        self.assertEqual(list(tca.UNSUPPORTED), UNSUPPORTED)
        self.assertEqual(tca.SYMBOLS, SYMBOLS)

    def test_the_44_steps_are_the_independent_ordered_url_list(self):
        expected = [step_url("calendar")] + [step_url(kind, symbol) for kind in KINDS for symbol in SYMBOLS] + [step_url("info")]
        self.assertEqual([step.url for step in tca.STEPS], expected)
        self.assertEqual(len(set(expected)), 44)
        self.assertEqual([step.index for step in tca.STEPS], list(range(44)))
        ids = [SOURCE_IDS["calendar"]] + [f"{SOURCE_IDS[kind]}/{symbol}" for kind in KINDS for symbol in SYMBOLS] + [SOURCE_IDS["info"]]
        self.assertEqual([step.source_id for step in tca.STEPS], ids)
        self.assertEqual([step.dataset for step in tca.STEPS],
                         [DATASETS["calendar"]] + [DATASETS[kind] for kind in KINDS for _ in SYMBOLS] + [DATASETS["info"]])
        for index, step in enumerate(tca.STEPS):  # query order is dataset, data_id, start_date, end_date; no token
            names = [part.split("=")[0] for part in step.url.split("?")[1].split("&")]
            self.assertIn(names, (["dataset", "start_date", "end_date"], ["dataset", "data_id", "start_date", "end_date"], ["dataset"]))
            self.assertNotIn("token", step.url)
        self.assertEqual(sum(url.endswith("end_date=" + DIV_END) for url in expected), 7)
        self.assertEqual(sum(url.endswith("end_date=" + END) for url in expected), 1 + 5 * 7)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            tca.STEPS[0].url = "x"

    def test_the_published_policy_literal_is_what_the_module_implements(self):
        self.assertEqual((len(PUBLISHED_POLICY), hashlib.sha256(PUBLISHED_POLICY).hexdigest()), (10257, PUBLISHED_SHA))
        self.assertEqual(canonical(policy_dict()), PUBLISHED_POLICY)
        self.assertEqual(canonical(json.loads(PUBLISHED_POLICY)), PUBLISHED_POLICY)
        self.assertFalse(PUBLISHED_POLICY.endswith(b"\n"))
        frozen = tca.validate_policy(PUBLISHED_POLICY, PUBLISHED_SHA)  # no pins argument: the module's own pins
        self.assertEqual((frozen["version"], frozen["acquisition"]["max_gets"], frozen["acquisition"]["namespace"]), (POLICY_VERSION, 44, NAMESPACE))
        self.assertFailure("policy_pin", tca.validate_policy, PUBLISHED_POLICY, "0" * 64)
        changed = PUBLISHED_POLICY.replace(b"issue98", b"issue99", 1)
        self.assertFailure("policy_pin", tca.validate_policy, changed, hashlib.sha256(changed).hexdigest())  # self-consistent but not published
        self.assertFailure("policy_pin", tca.validate_policy, PUBLISHED_POLICY + b"\n", hashlib.sha256(PUBLISHED_POLICY + b"\n").hexdigest())
        self.assertEqual(tca._real_pins(), tca.Pins(PUBLISHED_SHA, PUBLISHED_BYTES))

    def test_default_path_is_bound_to_the_published_policy_and_still_needs_a_valid_seal(self):
        pins = tca.Pins(PUBLISHED_SHA, PUBLISHED_BYTES)
        common = dict(policy_canonical=PUBLISHED_POLICY, policy_sha256=PUBLISHED_SHA, formal_blob=FORMAL)
        self.assertFailure("pins_with_default_transport", tca.CalendarActionsSource, **common, pins=pins)
        self.assertFailure("financial_start_required", tca.CalendarActionsSource, **common)
        self.assertFailure("policy_pin", tca.CalendarActionsSource, **{**common, "policy_sha256": "0" * 64})
        other = policy_dict()
        other["documentation"] += " x"  # a self-consistent policy that is not the published one
        blob, other_pins = policy_pack(other)
        self.assertFailure("policy_pin", tca.CalendarActionsSource, policy_canonical=blob, policy_sha256=other_pins.sha256, formal_blob=FORMAL)
        start, binding = declaration()
        source = tca.CalendarActionsSource(**common, financial_start=start, execution_binding=binding)
        self.assertEqual((source.state, source._real, source._pins), ("new", True, pins))  # constructed, never acquired: no GET
        self.assertFailure("default_transport_required_for_financial", tca.CalendarActionsSource, **common, financial_start=start,
                           execution_binding=binding, ledger=tca.AttemptLedger(NAMESPACE))
        at_floor = declaration(url=SEAL_URL.replace("9999999999", str(PUBLISHED_COMMENT)))
        self.assertFailure("financial_new_explicit_seal_required", tca.CalendarActionsSource, **common,
                           financial_start=at_floor[0], execution_binding=at_floor[1])
        above_floor = declaration(url=SEAL_URL.replace("9999999999", str(PUBLISHED_COMMENT + 1)))
        self.assertEqual(tca.CalendarActionsSource(**common, financial_start=above_floor[0], execution_binding=above_floor[1]).state, "new")
        self.assertFailure("saved_missing", tca.load_saved, self.new_root())  # default pins are set: only the missing root fails
        for name in ("POLICY_SHA256", "POLICY_BYTES"):  # were a pin ever unset, the default path would fail closed again
            with patch.object(tca, name, None):
                self.assertFailure("real_pins_unset", tca.CalendarActionsSource, **common)
                self.assertFailure("real_pins_unset", tca.load_saved, self.new_root())
        with patch.object(tca, "SEAL_COMMENT_FLOOR", None):
            self.assertFailure("seal_floor_unset", tca.CalendarActionsSource, **common, financial_start=start, execution_binding=binding)

    def test_full_synthetic_run_under_the_published_policy_uses_only_the_modules_own_pins(self):
        pins = tca.Pins(tca.POLICY_SHA256, tca.POLICY_BYTES)
        corpus = Corpus()
        source, _, _ = build(corpus=corpus, blob_pins=(PUBLISHED_POLICY, pins))
        source.acquire()
        self.assertEqual(source._pins, pins)
        source.admit_independent_verification(admission(source, corpus))
        self.assertEqual({capture.receipt.policy_sha256 for capture in source.inspection()["captures"]}, {PUBLISHED_SHA})
        root = self.new_root()
        source.save(root=root)
        saved = tca.load_saved(root)  # no pins argument: the module's own pins
        self.assertEqual(saved.receipt["source_policy"], {"version": POLICY_VERSION, "sha256": PUBLISHED_SHA, "bytes": PUBLISHED_BYTES})
        self.assertEqual(saved.data_version, DATA_PREFIX + corpus.data_sha())

    def test_policy_accepts_the_literal_and_every_non_text_leaf_is_pinned(self):
        blob, pins = policy_pack()
        frozen = tca.validate_policy(blob, pins.sha256, pins)
        self.assertIsInstance(frozen, types.MappingProxyType)
        self.assertEqual(frozen["version"], POLICY_VERSION)
        count = 0
        for path in leaf_paths(policy_dict()):
            document = policy_dict()
            value = get_path(document, path)
            changed = (not value) if isinstance(value, bool) else (value + 1 if isinstance(value, int) else value + "x")
            set_path(document, path, changed)
            mutated, mutated_pins = policy_pack(document)
            with self.subTest(path=".".join(map(str, path))):
                if path in TEXT_LEAVES:
                    tca.validate_policy(mutated, mutated_pins.sha256, mutated_pins)
                else:
                    error = self.assertFailure("policy_value", tca.validate_policy, mutated, mutated_pins.sha256, mutated_pins)
                    self.assertTrue(error.diagnostics["field"])
            count += 1
        self.assertGreater(count, 150)
        for path in sorted(TEXT_LEAVES - {("calendar", "version")}):
            for bad in ("", "x" * 1025):
                document = policy_dict()
                set_path(document, path, bad)
                mutated, mutated_pins = policy_pack(document)
                with self.subTest(path=".".join(path), length=len(bad)):
                    self.assertFailure("policy_value", tca.validate_policy, mutated, mutated_pins.sha256, mutated_pins)
        document = policy_dict()
        document["calendar"]["version"] = "bad version!"
        mutated, mutated_pins = policy_pack(document)
        self.assertFailure("policy_value", tca.validate_policy, mutated, mutated_pins.sha256, mutated_pins)

    def test_policy_shape_pin_and_canonical_errors(self):
        blob, pins = policy_pack()
        self.assertFailure("policy_input_type", tca.validate_policy, "text", pins.sha256, pins)
        self.assertFailure("policy_input_type", tca.validate_policy, blob, None, pins)
        self.assertFailure("policy_pin", tca.validate_policy, blob, "0" * 64, pins)
        self.assertFailure("pins_type", tca.validate_policy, blob, pins.sha256, tca.Pins("g" * 64, 1))
        self.assertFailure("pins_type", tca.validate_policy, blob, pins.sha256, tca.Pins(pins.sha256, 0))
        self.assertFailure("pins_type", tca.validate_policy, blob, pins.sha256, "pins")
        self.assertFailure("policy_canonical_mismatch", tca.validate_policy, blob, pins.sha256, tca.Pins(pins.sha256, pins.nbytes + 1))
        pretty = json.dumps(policy_dict(), indent=1, sort_keys=True).encode("utf8")
        pretty_pins = tca.Pins(hashlib.sha256(pretty).hexdigest(), len(pretty))
        self.assertFailure("policy_canonical_mismatch", tca.validate_policy, pretty, pretty_pins.sha256, pretty_pins)
        trailing = blob + b"\n"
        trailing_pins = tca.Pins(hashlib.sha256(trailing).hexdigest(), len(trailing))
        self.assertFailure("policy_canonical_mismatch", tca.validate_policy, trailing, trailing_pins.sha256, trailing_pins)
        document = policy_dict()
        document["extra"] = 1
        self.assertFailure("policy_keys", tca.validate_policy, *(lambda b, p: (b, p.sha256, p))(*policy_pack(document)))
        document = policy_dict()
        del document["checks"]["same_day_events"]
        self.assertFailure("policy_keys", tca.validate_policy, *(lambda b, p: (b, p.sha256, p))(*policy_pack(document)))
        document = policy_dict()
        document["window"]["start_date"] = 20260701
        self.assertFailure("policy_type", tca.validate_policy, *(lambda b, p: (b, p.sha256, p))(*policy_pack(document)))
        document = policy_dict()
        document["symbols"].append("2330")
        self.assertFailure("policy_list", tca.validate_policy, *(lambda b, p: (b, p.sha256, p))(*policy_pack(document)))
        document = policy_dict()
        document["unsupported"][0] = 1
        self.assertFailure("policy_type", tca.validate_policy, *(lambda b, p: (b, p.sha256, p))(*policy_pack(document)))
        duplicate = blob.replace(b'{"acquisition"', b'{"version":"x","acquisition"', 1)
        self.assertFailure("duplicate_json_key", tca.validate_policy, duplicate, hashlib.sha256(duplicate).hexdigest(),
                           tca.Pins(hashlib.sha256(duplicate).hexdigest(), len(duplicate)))
        garbage = b"\xff\xfe{}"
        self.assertFailure("policy_encoding", tca.validate_policy, garbage, hashlib.sha256(garbage).hexdigest(),
                           tca.Pins(hashlib.sha256(garbage).hexdigest(), len(garbage)))

    def test_financial_start_pure_guards(self):
        pins = policy_pack()[1]
        start, binding = declaration()
        self.assertIsNone(tca._financial_start(start, binding, pins))
        cases = [
            ("financial_start_required", lambda s, b: (None, b)), ("financial_start_required", lambda s, b: (s, None)),
            ("financial_binding_type", lambda s, b: (replace(s, binding="x"), b)),
            ("financial_binding_mismatch", lambda s, b: (s, replace(b, model="claude-opus-5-5"))),
            ("financial_qa_not_top_level", lambda s, b: (replace(s, binding=replace(b, parent_thread_id="p")), replace(b, parent_thread_id="p"))),
            ("financial_start_not_authorized", lambda s, b: (replace(s, authorized=False), b)),
            ("financial_start_not_authorized", lambda s, b: (replace(s, whole_batch=False), b)),
            ("financial_start_type", lambda s, b: (replace(s, coordinator_session_ids=[]), b)),
            ("financial_start_type", lambda s, b: (replace(s, issuer_thread_id=7), b)),
            ("financial_start_scope", lambda s, b: (replace(s, namespace="issue98-other/qa1"), b)),
            ("financial_start_scope", lambda s, b: (replace(s, version="issue32-financial-start-v1"), b)),
            ("financial_start_scope", lambda s, b: (replace(s, policy_sha256="0" * 64), b)),
            ("financial_start_scope", lambda s, b: (replace(s, issuer_thread_id="not-a-session"), b)),
            ("financial_start_scope", lambda s, b: (replace(s, implementer_session_ids=(SEAL_ISSUER,)), b)),
            ("financial_qa_identity", lambda s, b: (replace(s, binding=replace(b, reasoning_effort="high")), replace(b, reasoning_effort="high"))),
            ("financial_qa_identity", lambda s, b: (replace(s, binding=replace(b, holder_session_id="a" * 8)), replace(b, holder_session_id="a" * 8))),
            ("financial_qa_identity", lambda s, b: (replace(s, binding=replace(b, model="bad model!")), replace(b, model="bad model!"))),
            ("financial_candidate", lambda s, b: (replace(s, binding=replace(b, candidate_sha="A" * 40)), replace(b, candidate_sha="A" * 40))),
            ("financial_script_binding", lambda s, b: (replace(s, binding=replace(b, script_sha256="z" * 64)), replace(b, script_sha256="z" * 64))),
            ("financial_new_explicit_seal_required", lambda s, b: (replace(s, seal_comment_url=SEAL_URL.replace("issues/98", "issues/7")), b)),
            ("financial_new_explicit_seal_required", lambda s, b: (replace(s, seal_comment_url=SEAL_URL.replace("9999999999", str(SEAL_FLOOR))), b)),
            ("financial_new_explicit_seal_required", lambda s, b: (replace(s, seal_comment_url="https://example.invalid/x"), b)),
        ]
        for code, edit in cases:
            with self.subTest(code=code):
                self.assertFailure(code, tca._financial_start, *edit(start, binding), pins)
        holder_in_roles = declaration(holder=SEAL_COORDINATORS[0])
        self.assertFailure("financial_qa_identity", tca._financial_start, *holder_in_roles, pins)
        with patch.object(tca, "SEAL_COMMENT_FLOOR", None):
            self.assertFailure("seal_floor_unset", tca._financial_start, start, binding, pins)
        self.assertIsNone(tca._financial_start(declaration(url=SEAL_URL.replace("9999999999", str(SEAL_FLOOR + 1)))[0], binding, pins))

    def test_constructor_arguments_are_checked_before_any_transport_use(self):
        blob, pins = policy_pack()
        common = dict(policy_canonical=blob, policy_sha256=pins.sha256, formal_blob=FORMAL, pins=pins, ledger=tca.AttemptLedger(NAMESPACE))
        transport = Transport([])
        self.assertFailure("unsupported_purpose", tca.CalendarActionsSource, **common, transport=transport, purpose="strategy")
        for lease in (0, -1, 181, math.nan, math.inf, "180", True):
            self.assertFailure("lease_seconds", tca.CalendarActionsSource, **common, transport=transport, lease_seconds=lease)
        self.assertFailure("clock_or_roots_type", tca.CalendarActionsSource, **common, transport=transport, clock=5)
        self.assertFailure("clock_or_roots_type", tca.CalendarActionsSource, **common, transport=transport, observer_roots=5)
        self.assertFailure("boundary_pins_required", tca.CalendarActionsSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL, transport=transport, ledger=tca.AttemptLedger(NAMESPACE))
        self.assertFailure("boundary_ledger_required", tca.CalendarActionsSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL, pins=pins, transport=transport)
        self.assertFailure("boundary_ledger_required", tca.CalendarActionsSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL, pins=pins, transport=transport, ledger=base.AttemptLedger(base.NAMESPACE))
        start, binding = declaration()
        self.assertFailure("financial_start_with_boundary_transport", tca.CalendarActionsSource, **common, transport=transport,
                           financial_start=start, execution_binding=binding)
        self.assertFailure("formal_blob_pin", tca.CalendarActionsSource, **{**common, "formal_blob": FORMAL + b" "}, transport=transport)
        self.assertEqual(transport.opens, [])
        self.assertFailure("quota_namespace", tca.AttemptLedger, "issue98-other/qa1")


# --- calendar gate ---------------------------------------------------------------------------------------

def insert_sorted(rows, day):
    rows.append({"date": day})
    rows.sort(key=lambda row: row["date"])


class Calendar(Case):
    def fail_at(self, index, code, *, corpus=None, mutate=None, bodies=None):
        corpus = corpus or Corpus()
        if mutate:
            mutate(corpus)
        source, transport, _ = build(corpus=corpus, bodies=bodies)
        error = self.assertFailure(code, source.acquire)
        self.assertEqual(len(transport.opens), index + 1)
        self.assertEqual(source.ledger.attempted, tuple(range(index + 1)))
        self.assertEqual(source.state, "failed")
        self.assertEqual(source.inspection()["data_bytes"], b"")
        self.assertTrue(all(response.closed for response in transport.responses))
        return error

    def test_calendar_document_gates_stop_the_batch_after_the_first_get(self):
        rows = lambda c: c.docs[0]["data"]  # noqa: E731
        cases = [
            ("trading_dates_document", lambda c: c.docs.__setitem__(0, [1])),
            ("trading_dates_document", lambda c: c.docs[0].update(extra=1)),
            ("trading_dates_document_status", lambda c: c.docs[0].update(status=500)),
            ("trading_dates_document_status", lambda c: c.docs[0].update(msg="no")),
            ("trading_dates_rows", lambda c: c.docs[0].update(data={})),
            ("trading_dates_rows", lambda c: c.docs[0].update(data=[])),
            ("trading_dates_row", lambda c: rows(c)[0].update(extra=1)),
            ("trading_dates_row", lambda c: rows(c).__setitem__(0, "2026-07-01")),
            ("trading_dates_date", lambda c: rows(c)[3].update(date="2026-7-4")),
            ("trading_dates_date", lambda c: rows(c)[3].update(date=20260704)),
            ("trading_dates_order", lambda c: rows(c).insert(5, dict(rows(c)[2]))),
            ("trading_dates_order", lambda c: rows(c).reverse()),
            ("trading_dates_date", lambda c: rows(c).append({"date": "2099-13-01"})),  # malformed rows outside the window still count
            ("trading_dates_weekday", lambda c: insert_sorted(rows(c), "2026-07-04")),
            ("trading_dates_identity_day", lambda c: c.docs[0].update(data=[r for r in rows(c) if r["date"] != IDENTITY])),
            ("trading_dates_formal_mismatch", lambda c: c.docs[0].update(data=[r for r in rows(c) if r["date"] != "2026-08-14"])),
            ("trading_dates_formal_mismatch", lambda c: insert_sorted(rows(c), "2026-09-25")),
            ("trading_dates_empty", lambda c: c.docs[0].update(data=[{"date": "2026-06-30"}, {"date": "2026-10-13"}])),
        ]
        for code, mutate in cases:
            with self.subTest(code=code, case=cases.index((code, mutate))):
                self.fail_at(0, code, mutate=mutate)

    def test_july_gap_unknown_closures_and_days_after_the_formal_span_are_taken_as_returned(self):
        corpus = Corpus()
        corpus.docs[0]["data"] = [{"date": "2026-06-30"}] + [r for r in corpus.docs[0]["data"] if r["date"] != "2026-07-10"] + [{"date": "2026-10-13"}]
        source, _, _ = acquired(corpus=corpus)
        data = data_of(source)
        self.assertNotIn("2026-07-10", data["calendar"])
        self.assertNotIn("2026-06-30", data["calendar"])
        self.assertNotIn("2026-10-13", data["calendar"])
        self.assertEqual(data["calendar_after_formal"], list(BEYOND))
        self.assertEqual(len(data["calendar"]), 70)
        # days a symbol lacks relative to the calendar are incomparable days, never an asserted closure
        self.assertEqual(source.inspection()["metrics"]["calendar_rows"], 70)

    def test_a_row_outside_the_window_with_valid_structure_is_discarded_and_nothing_else_is_requested_on_failure(self):
        corpus = Corpus()
        source, transport, _ = acquired(corpus=corpus)
        self.assertEqual([url for url, _ in transport.opens], [step.url for step in tca.STEPS])
        self.assertEqual(source.ledger.attempted, tuple(range(44)))
        self.assertEqual(source.ledger.unrun, ())
        self.assertEqual(source.state, "pending")


# --- acquisition mechanics ---------------------------------------------------------------------------------

class Acquisition(Case):
    real_roots_tests = ("test_retained_roots_cap_fails_closed_before_and_during_acquisition",)

    def fail_with(self, index, code, **options):
        source, transport, _ = build(transport=Transport(Corpus().bodies, response_options={index: options}))
        error = self.assertFailure(code, source.acquire)
        self.assertEqual(len(transport.opens), index + 1)
        self.assertEqual(source.ledger.attempted, tuple(range(index + 1)))
        self.assertTrue(all(response.closed for response in transport.responses))
        return error

    def test_http_framing_and_body_boundaries_fail_the_whole_batch(self):
        for index in (0, 9, 43):
            cases = [
                ("http_status", dict(status=500)), ("http_status", dict(status=401)), ("http_status", dict(status=402)),
                ("http_status", dict(status=403)), ("http_status", dict(status=302)), ("http_status", dict(status=200.0)),
                ("content_encoding", dict(headers=(("Content-Encoding", "gzip"),) + JSON_TYPE + (("Content-Length", "9"),))),
                ("content_encoding", dict(headers=(("Content-Encoding", "br"),) + JSON_TYPE)),
                ("content_type", dict(headers=(("Content-Length", "9"), ("Content-Type", "text/html")))),
                ("content_type", dict(headers=(("Content-Length", "9"),))),
                ("content_type", dict(headers=(("Content-Length", "9"), ("Content-Type", "application/jsonx")))),
                ("ambiguous_framing", dict(headers=(("Content-Length", "9"), ("Transfer-Encoding", "chunked")) + JSON_TYPE)),
                ("ambiguous_framing", dict(headers=(("Transfer-Encoding", "gzip"),) + JSON_TYPE)),
                ("duplicate_framing_header", dict(headers=(("Content-Length", "9"), ("content-length", "9")) + JSON_TYPE)),
                ("duplicate_framing_header", dict(headers=(("Content-Type", "application/json"), ("content-type", "application/json")))),
                ("content_length", dict(headers=(("Content-Length", "09"),) + JSON_TYPE)),
                ("content_length", dict(headers=(("Content-Length", "-1"),) + JSON_TYPE)),
                ("declared_body_cap", dict(headers=(("Content-Length", str(tca.BODY_CAP + 1)),) + JSON_TYPE)),
                ("incomplete_content_length", dict(headers=(("Content-Length", "99999"),) + JSON_TYPE)),
            ]
            for code, options in cases:
                with self.subTest(index=index, code=code, options=str(options)[:60]):
                    self.fail_with(index, code, **options)

    def test_empty_body_unknown_eof_and_oversize_bodies(self):
        bodies = Corpus().bodies
        source, transport, _ = build(bodies=[b""] + bodies[1:])
        self.assertFailure("empty_body", source.acquire)
        source, transport, _ = build(transport=Transport(bodies, response_options={0: dict(declared=False, eof=False)}))
        with patch.object(tca, "BODY_CAP", 40):  # the cap is reached without a known EOF
            self.assertFailure("body_cap_without_known_eof", source.acquire)
        self.assertTrue(all(response.closed for response in transport.responses))
        source, transport, _ = build()
        with patch.object(tca, "RAW_CAP", 3000):  # aggregate raw cap: a declared size beyond what is left is refused
            error = self.assertFailure("declared_body_cap", source.acquire)
        self.assertEqual(len(transport.opens), 2)
        self.assertEqual(error.diagnostics["attempts"], 2)

    def test_invalid_transport_reads_are_rejected_and_the_response_is_closed(self):
        class Over(Response):
            def read(self, count, timeout):
                return b"x" * (count + 1)

        class NotBytes(Response):
            def read(self, count, timeout):
                return "text"

        class NoEof(Response):
            @property
            def known_eof(self):
                return False

            def read(self, count, timeout):
                return b""

        for response_class, code in ((Over, "invalid_transport_read"), (NotBytes, "invalid_transport_read"), (NoEof, "missing_known_eof")):
            transport = Transport(Corpus().bodies)
            transport.open = (lambda cls: lambda url, timeout: transport.responses.append(cls(b"{}", declared=False)) or transport.responses[-1])(response_class)
            source, _, _ = build(transport=transport)
            with self.subTest(code=code, response=response_class.__name__):
                self.assertFailure(code, source.acquire)
                self.assertTrue(transport.responses[0].closed)

    def test_close_failures_keep_the_primary_code_and_cleanup_only_failure_rejects(self):
        bodies = Corpus().bodies
        source, transport, _ = build(transport=Transport(bodies, response_options={0: dict(close_raises=True)}))
        error = self.assertFailure("cleanup_failure", source.acquire)  # cleanup-only failure rejects the batch
        self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        source, transport, _ = build(transport=Transport(bodies, response_options={0: dict(status=500, close_raises=True)}))
        error = self.assertFailure("http_status", source.acquire)
        self.assertEqual((error.diagnostics["secondary_cleanup_count"], error.diagnostics["secondary_cleanup_1_stage"]),
                         (1, "capture_response_close"))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        source, transport, _ = build(transport=Transport(bodies, fail_at=0))
        error = self.assertFailure("transport_or_parse_failure", source.acquire)
        self.assertNotIn("synthetic", repr(dict(error.diagnostics)))
        self.assertEqual(source.ledger.attempted, (0,))  # an open failure is still SPENT

    def test_get_failures_stop_after_the_failing_get_and_spend_only_what_was_attempted(self):
        for index in (1, 8, 22, 43):
            source, transport, _ = build(transport=Transport(Corpus().bodies, fail_at=index))
            with self.subTest(index=index):
                error = self.assertFailure("transport_or_parse_failure", source.acquire)
                self.assertEqual(len(transport.opens), index + 1)
                self.assertEqual(source.ledger.attempted, tuple(range(index + 1)))
                self.assertEqual(source.ledger.unrun, tuple(range(index + 1, 44)))
                self.assertEqual(error.diagnostics["attempts"], index + 1)

    def test_cooperative_request_batch_and_lease_deadlines(self):
        clock = Clock()
        source, transport, _ = build(clock=clock, transport=Transport(Corpus().bodies, clock=clock, open_delay=21))
        self.assertFailure("cooperative_deadline", source.acquire)
        self.assertEqual(len(transport.opens), 1)
        clock = Clock()
        source, transport, _ = build(clock=clock, transport=Transport(Corpus().bodies, clock=clock, open_delay=15))
        with patch.object(tca, "BATCH_SECONDS", 40):  # three 15 s opens exceed the 40 s batch budget
            self.assertFailure("cooperative_deadline", source.acquire)
        self.assertEqual(len(transport.opens), 3)
        clock = Clock()
        source, _, _ = acquired(clock=clock)
        self.assertEqual(source.state, "pending")
        clock.now += 179
        self.assertEqual(source.state, "pending")
        clock.now += 1
        self.assertEqual(source.state, "expired")
        self.assertFailure("consumer_unavailable", source._usable)
        self.assertFailure("inspection_unavailable", source.inspection)
        clock = Clock()
        source, _, _ = build(clock=clock, lease_seconds=5)
        source.acquire()
        clock.now += 5
        self.assertEqual(source.state, "expired")
        clock = Clock()
        source, _, _ = build(clock=clock, transport=Transport(Corpus().bodies, clock=clock, open_delay=-1))
        self.assertFailure("invalid_monotonic_clock", source.acquire)

    def test_retained_roots_cap_fails_closed_before_and_during_acquisition(self):
        self.assertFailure("retained_roots_estimate_cap", build, observer_roots=lambda: ["x" * (tca.ROOTS_CAP + 1)])
        source, transport, _ = build()
        floor = source._roots_estimate
        self.assertGreater(floor, 0)
        with patch.object(tca, "ROOTS_CAP", floor + 5000):  # the constructor fits, the captured documents do not
            error = self.assertFailure("retained_roots_estimate_cap", source.acquire)
        self.assertGreater(error.diagnostics["estimate_bytes"], floor + 5000)
        self.assertEqual(source.state, "failed")
        self.assertTrue(all(response.closed for response in transport.responses))

    def test_one_shot_ledger_namespace_and_no_second_attempt(self):
        source, _, _ = acquired()
        self.assertFailure("snapshot_already_attempted", source.acquire)
        ledger = source.ledger
        second, transport, _ = build(ledger=ledger)
        self.assertFailure("quota_spent", second.acquire)
        self.assertEqual(transport.opens, [])
        fresh = tca.AttemptLedger(NAMESPACE)
        self.assertEqual((fresh.attempted, fresh.unrun), ((), tuple(range(44))))
        self.assertFailure("quota_order", fresh.charge, 0)
        fresh.begin()
        self.assertFailure("quota_spent", fresh.begin)
        self.assertFailure("quota_order", fresh.charge, 1)
        for index in range(44):
            fresh.charge(index)
        self.assertFailure("quota_order", fresh.charge, 44)
        self.assertFailure("quota_order", fresh.charge, "0")
        self.assertEqual(fresh.unrun, ())
        self.assertTrue(issubclass(tca.AttemptLedger, base.AttemptLedger))

    def test_pending_until_independent_admission_binds_receipts_and_data(self):
        corpus = Corpus()
        source, _, _ = acquired(corpus=corpus)
        self.assertEqual(source.state, "pending")
        self.assertFailure("consumer_unavailable", source._usable)
        self.assertFailure("consumer_unavailable", source.save, root=self.new_root())
        good = admission(source, corpus)
        for code, changes in (
                ("oracle_type", dict(calendar_rows="71")), ("oracle_type", dict(independent=1)), ("oracle_type", dict(receipt_sha256s=[])),
                ("oracle_scope", dict(independent=False)), ("oracle_scope", dict(namespace="issue98-other/qa1")),
                ("oracle_scope", dict(policy_sha256="0" * 64)), ("oracle_receipt_type", dict(data_sha256="x")),
                ("oracle_receipt_type", dict(receipt_sha256s=good.receipt_sha256s[:-1] + ("zz",))),
                ("oracle_complete_scope", dict(calendar_rows=70)), ("oracle_complete_scope", dict(price_rows=7 * 71 - 1)),
                ("oracle_complete_scope", dict(event_rows=6)),
                ("oracle_capture_binding", dict(receipt_sha256s=good.receipt_sha256s[:-1])),
                ("oracle_capture_binding", dict(receipt_sha256s=tuple(reversed(good.receipt_sha256s)))),
                ("oracle_data_binding", dict(data_sha256="0" * 64))):
            with self.subTest(code=code, changes=sorted(changes)):
                self.assertFailure(code, source.admit_independent_verification, replace(good, **changes))
                self.assertEqual(source.state, "pending")
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, "proof")
        source.admit_independent_verification(good)
        self.assertEqual(source.state, "available")
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, good)
        source.release()
        self.assertEqual(source.state, "released")
        self.assertFailure("consumer_unavailable", source._usable)
        self.assertEqual((source._data_bytes, source._captures, source.ledger.attempted), (b"", [], tuple(range(44))))
        self.assertFailure("snapshot_already_attempted", source.acquire)

    def test_failed_acquisition_exposes_no_derived_state_and_cannot_be_saved(self):
        corpus = Corpus()
        corpus.docs[step_index("split", "5274")]["status"] = 500
        source, transport, _ = build(corpus=corpus)
        error = self.assertFailure("split_document_status", source.acquire)
        self.assertEqual(error.diagnostics["source_index"], step_index("split", "5274"))
        view = source.inspection()
        self.assertEqual((view["data_bytes"], dict(view["metrics"])), (b"", {}))
        self.assertEqual(source.state, "failed")
        self.assertFailure("consumer_unavailable", source.save, root=self.new_root())
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, admission(source, Corpus()))
        self.assertEqual(len(transport.opens), step_index("split", "5274") + 1)


# --- response shapes through the real http.client path -----------------------------------------------------

class Replay(Case):
    def run_wires(self, wires):
        replay = ReplayTransport(wires)
        source, _, _ = build(transport=replay)
        return source, replay

    def test_full_pipeline_for_each_accepted_framing(self):
        corpus = Corpus()
        for framing in ("length", "chunked", "none"):
            wires = [finmind_wire(body, framing=framing, content_type="application/json; charset=UTF-8" if framing == "chunked" else "application/json",
                                  extra=(("Set-Cookie", "a=b"), ("Vary", "Origin"))) for body in corpus.bodies]
            source, replay = self.run_wires(wires)
            with self.subTest(framing=framing):
                source.acquire()
                self.assertEqual(source.state, "pending")
                self.assertEqual(replay.opens, [step.url for step in tca.STEPS])
                self.assertEqual(data_of(source), corpus.expected_data())
                self.assertEqual({tuple(sorted(headers)) for _, _, _, headers in replay.requests},
                                 {("Accept", "Accept-Encoding", "Connection", "User-Agent")})
                self.assertEqual(replay.requests[0][3], {"Accept-Encoding": "identity", "Connection": "close",
                                                         "User-Agent": "stock-lab-issue32-local-ram/1", "Accept": "application/json"})

    def test_response_shapes_that_must_reject_the_batch_after_one_get(self):
        body = Corpus().bodies[0]
        cases = [
            ("http_status", dict(status=401, reason="Unauthorized")), ("http_status", dict(status=402, reason="Payment Required")),
            ("http_status", dict(status=403, reason="Forbidden")),
            ("content_encoding", dict(content_encoding="gzip")), ("content_encoding", dict(content_encoding="br")),
            ("content_type", dict(content_type="text/html")), ("content_type", dict(content_type=None)),
            ("ambiguous_framing", dict(framing="both")),
            ("duplicate_framing_header", dict(extra=(("Content-Length", str(len(body))),))),
            ("duplicate_framing_header", dict(extra=(("Content-Type", "application/json"),))),
        ]
        for code, options in cases:
            source, replay = self.run_wires([finmind_wire(body, **options)])
            with self.subTest(code=code, options=str(options)):
                self.assertFailure(code, source.acquire)
                self.assertEqual(len(replay.opens), 1)
        source, replay = self.run_wires([finmind_wire(b"\xef\xbb\xbf" + body)])
        self.assertFailure("transport_or_parse_failure", source.acquire)
        source, replay = self.run_wires([finmind_wire(b'{"status":200,"status":200,"msg":"success","data":[]}')])
        self.assertFailure("duplicate_json_key", source.acquire)
        source, replay = self.run_wires([finmind_wire(b'{"status":NaN,"msg":"success","data":[]}')])
        self.assertFailure("nonfinite_json_number", source.acquire)



# --- derivation scenarios --------------------------------------------------------------------------------

def run(corpus):
    source, _, _ = acquired(corpus=corpus)
    return data_of(source)


def rows_of(corpus, kind, symbol):
    return corpus.docs[step_index(kind, symbol)]["data"]


def only_event(entry):
    assert len(entry["events"]) == 1, entry["events"]
    return entry["events"][0]


def set_implied(corpus, symbol, day, reference):
    """Make the day's close - spread (the reference price its spread implies) equal ``reference``."""
    row = next(row for row in corpus.rows[symbol] if row["date"] == day)
    row["spread"] = float(Decimal(str(row["close"])) - Decimal(str(reference)))  # decimal arithmetic: no float noise


def align(corpus, symbol, reference):
    """State ``reference`` as the symbol's F3 reference price and as the price its event-day spread implies."""
    for row in corpus.docs[step_index("dividend_result", symbol)]["data"]:
        row.update(reference_price=reference, after_price=reference)
    set_implied(corpus, symbol, corpus.event_day[symbol], reference)


class Derivation(Case):
    def test_base_corpus_is_exactly_the_independent_expectation(self):
        corpus = Corpus()
        source, _, _ = acquired(corpus=corpus)
        view = source.inspection()
        self.assertEqual(data_of(source), corpus.expected_data())
        self.assertEqual(view["data_bytes"], canonical(corpus.expected_data()))
        self.assertEqual(dict(view["metrics"]), {"calendar_rows": 71, "price_rows": 497, "event_rows": 7})
        self.assertEqual(view["dates"], DATES)
        self.assertEqual(len(view["captures"]), 44)
        self.assertEqual([c.receipt.url for c in view["captures"]], [step.url for step in tca.STEPS])
        self.assertTrue(all(c.receipt.namespace == NAMESPACE for c in view["captures"]))
        self.assertEqual(view["captures"][0].receipt.source_version, CALENDAR_VERSION)
        self.assertEqual({c.receipt.source_version for c in view["captures"][1:]}, {POLICY_VERSION})

    def test_missing_zero_partial_zero_and_bounds_days_are_incomparable_and_never_fail_the_batch(self):
        corpus = Corpus()
        rows = corpus.rows["3105"]
        by_day = {row["date"]: row for row in rows}
        days = [DATES[index] for index in (5, 6, 7, 8)]
        rows.remove(by_day[days[0]])
        by_day[days[1]].update(open=0, max=0, min=0, close=0, spread=0, Trading_Volume=0, Trading_money=0)
        by_day[days[2]].update(open=0)
        by_day[days[3]].update(max=1)
        # the exchange reference after a gap is the last traded close: day 4
        by_day[DATES[9]]["spread"] = by_day[DATES[9]]["close"] - by_day[DATES[4]]["close"]
        data = run(corpus)
        entry = data["symbols"]["3105"]
        self.assertEqual(entry["incomparable_days"], [[days[0], "missing_row"], [days[1], "ohlc_zero"],
                                                      [days[2], "ohlc_partial_zero"], [days[3], "ohlc_bounds"]])
        self.assertEqual((entry["status"], entry["refusal_reasons"]), ("usable", []))
        self.assertEqual((entry["spread_check"]["checked"], entry["spread_check"]["matched"], entry["spread_check"]["status"]),
                         (66, 65, "consistent"))
        self.assertEqual(entry["adjusted"], {"supported_from": DATES[0], "reasons": []})
        for symbol in SYMBOLS[1:]:
            self.assertEqual(data["symbols"][symbol], Corpus().expected_symbol(symbol))

    def test_price_structure_failures_are_first_failures_at_the_failing_get(self):
        cases = [
            ("price_document", lambda d: d.update(extra=1)), ("price_document_status", lambda d: d.update(status=201)),
            ("price_document_status", lambda d: d.update(msg="error")), ("price_rows", lambda d: d.update(data="x")),
            ("price_row", lambda d: d["data"].__setitem__(0, 5)), ("price_row_fields", lambda d: d["data"][0].pop("close")),
            ("price_stock_id", lambda d: d["data"][2].update(stock_id="3293")), ("price_string", lambda d: d["data"][2].update(stock_id="")),
            ("price_duplicate", lambda d: d["data"].insert(3, dict(d["data"][2]))),
            ("price_date", lambda d: d["data"][0].update(date="2026-7-1")), ("price_negative", lambda d: d["data"][4].update(close=-1)),
            ("price_number", lambda d: d["data"][4].update(close="100")), ("price_number", lambda d: d["data"][4].update(spread="x")),
            ("price_integer", lambda d: d["data"][4].update(Trading_Volume=1.5)),
            ("price_integer", lambda d: d["data"][4].update(Trading_turnover="1")),
            ("price_integer", lambda d: d["data"][4].update(Trading_money=-1)),
        ]
        for symbol in ("3105", "8069"):
            index = step_index("price", symbol)
            for code, edit in cases:
                corpus = Corpus()
                edit(corpus.docs[index])
                source, transport, _ = build(corpus=corpus)
                with self.subTest(symbol=symbol, code=code, case=cases.index((code, edit))):
                    error = self.assertFailure(code, source.acquire)
                    self.assertEqual(len(transport.opens), index + 1)
                    self.assertEqual(error.diagnostics["source_index"], index)
                    self.assertEqual(source.ledger.attempted, tuple(range(index + 1)))

    def test_rows_outside_the_window_are_discarded_after_structure_validation(self):
        corpus = Corpus()
        rows = corpus.rows["3293"]
        template = dict(rows[0])
        rows.insert(0, {**template, "date": "2026-06-30"})
        rows.append({**template, "date": "2026-10-13"})
        data = run(corpus)
        self.assertEqual(data, Corpus().expected_data())  # neither row is stored or counted
        corpus = Corpus()
        corpus.rows["3293"].insert(0, {**template, "date": "2026-06-30", "close": -5})
        source, transport, _ = build(corpus=corpus)
        self.assertFailure("price_negative", source.acquire)
        self.assertEqual(len(transport.opens), step_index("price", "3293") + 1)

    def test_a_row_inside_the_window_but_off_the_calendar_refuses_the_symbol(self):
        corpus = Corpus()
        corpus.rows["3293"].insert(2, {**corpus.rows["3293"][0], "date": "2026-07-04"})  # a Saturday; ascending order is not required
        source, _, _ = acquired(corpus=corpus)
        data = data_of(source)
        self.assertEqual(data["symbols"]["3293"]["status"], "refused")
        self.assertEqual(data["symbols"]["3293"]["refusal_reasons"], ["price_row_off_calendar"])
        self.assertEqual(data["symbols"]["3105"], Corpus().expected_symbol("3105"))
        self.assertEqual(source.inspection()["metrics"]["price_rows"], 498)

    def test_identity_anchor_empty_prices_and_stock_info_decide_the_symbol_status(self):
        corpus = Corpus()
        anchor = corpus.rows["6488"][-4]  # the 2026-10-06 row
        self.assertEqual(anchor["date"], IDENTITY)
        anchor["close"] += 1
        self.assertEqual(corpus.rows["6510"].pop(-4)["date"], IDENTITY)
        corpus.docs[step_index("price", "8069")]["data"] = []
        info = corpus.docs[43]["data"]
        info[:] = [row for row in info if row["stock_id"] != "5274"]
        next(row for row in info if row["stock_id"] == "3293")["type"] = "twse"
        info.append({"stock_id": "5347", "type": "twse", "date": "2026-09-30"})                    # same newest date, other type
        info.append({"stock_id": "6510", "type": "twse", "date": "2026-10-01", "extra": 1})          # a newer row wins
        data = run(corpus)["symbols"]
        self.assertEqual((data["6488"]["status"], data["6488"]["refusal_reasons"]), ("refused", ["identity_anchor_mismatch"]))
        self.assertEqual(data["6510"]["refusal_reasons"], ["identity_anchor_mismatch", "market_type_not_accepted"])
        self.assertEqual(data["6510"]["info"], {"type": "twse", "date": "2026-10-01"})
        self.assertEqual(data["6510"]["incomparable_days"], [[IDENTITY, "missing_row"]])
        self.assertEqual(data["8069"]["refusal_reasons"], ["identity_anchor_mismatch", "price_rows_missing"])
        self.assertEqual(len(data["8069"]["incomparable_days"]), 71)
        self.assertEqual(data["8069"]["spread_check"]["status"], "semantics_unverified")
        self.assertEqual((data["5274"]["info"], data["5274"]["refusal_reasons"]), ({"type": None, "date": None}, ["info_missing"]))
        self.assertEqual((data["3293"]["refusal_reasons"], data["3293"]["info"]["type"]), (["market_type_not_accepted"], "twse"))
        self.assertEqual((data["5347"]["refusal_reasons"], data["5347"]["info"]), (["info_ambiguous"], {"type": None, "date": None}))
        self.assertEqual(data["3105"], Corpus().expected_symbol("3105"))  # its older 'emerging' row is ignored: the newest row wins

    def test_stock_info_structure_and_null_type(self):
        corpus = Corpus()
        corpus.docs[43]["data"].append({"stock_id": "", "type": "twse", "date": "2026-09-30"})
        source, transport, _ = build(corpus=corpus)
        self.assertFailure("info_string", source.acquire)
        self.assertEqual(len(transport.opens), 44)
        corpus = Corpus()
        corpus.docs[43]["data"].append({"stock_id": "2317", "type": 5, "date": "2026-09-30"})
        self.assertFailure("info_string", build(corpus=corpus)[0].acquire)
        corpus = Corpus()
        corpus.docs[43]["data"].append({"stock_id": "2317", "date": "2026-09-30"})
        self.assertFailure("info_row_fields", build(corpus=corpus)[0].acquire)
        corpus = Corpus()
        next(r for r in corpus.docs[43]["data"] if r["stock_id"] == "8069")["type"] = None
        corpus.docs[43]["data"].append({"stock_id": "9999", "type": None, "date": "garbage"})  # unrelated stock: unparsable date tolerated
        data = run(corpus)["symbols"]
        self.assertEqual(data["8069"]["refusal_reasons"], ["market_type_not_accepted"])
        self.assertEqual(data["8069"]["info"]["type"], None)

    def dividend_symbol(self, edit_f3=None, edit_f4=None, symbol="3105"):
        corpus = Corpus()
        if edit_f3:
            edit_f3(rows_of(corpus, "dividend_result", symbol), corpus)
        if edit_f4:
            edit_f4(rows_of(corpus, "dividend", symbol), corpus)
        return corpus, run(corpus)["symbols"][symbol]

    def test_ex_dividend_factor_is_exact_for_cash_stock_and_combined_terms(self):
        corpus = Corpus()
        day = corpus.event_day["3105"]
        price = Fraction(str(corpus.prior["3105"]))
        self.assertEqual(price, Fraction(205, 2))
        base = only_event(run(Corpus())["symbols"]["3105"])
        self.assertEqual((base["factor"], base["before"], base["reference"]), (ft(Fraction(101, 1) / price), ft(price), "101/1"))

        def combined(rows, c):
            rows[0].update(StockExDividendTradingDate=day, StockEarningsDistribution=1, StockStatutorySurplus=0.5)
            align(c, "3105", nearest((price - Fraction(3, 2)) / (1 + Fraction(3, 20))))
        _, entry = self.dividend_symbol(edit_f4=combined)
        event = only_event(entry)
        self.assertEqual(event["factor"], ft((price - Fraction(3, 2)) / price / (1 + Fraction(3, 20))))
        self.assertEqual((event["trace"]["C"], event["trace"]["Rf"], event["supported"], event["reasons"]), ("3/2", "3/20", True, []))
        self.assertEqual(entry["adjusted"], {"supported_from": DATES[0], "reasons": []})

        def stock_only(rows, c):
            rows[0].update(StockExDividendTradingDate=day, CashExDividendTradingDate="", StockEarningsDistribution=2)
            align(c, "3105", nearest(price / (1 + Fraction(1, 5))))
        _, entry = self.dividend_symbol(edit_f4=stock_only)
        event = only_event(entry)
        self.assertEqual((event["factor"], event["trace"]["C"], event["trace"]["Rf"]), ("5/6", "0/1", "1/5"))

        def stock_on_the_day_cash_later(rows, c):
            rows[0].update(StockExDividendTradingDate=day, CashExDividendTradingDate=DATES[45], StockEarningsDistribution=1)
            align(c, "3105", nearest(price / (1 + Fraction(1, 10))))
        _, entry = self.dividend_symbol(edit_f4=stock_on_the_day_cash_later)
        first, second = entry["events"]
        self.assertEqual((first["kind"], first["factor"], first["supported"]), ("ex_dividend", "10/11", True))
        self.assertEqual((second["kind"], second["date"], second["reasons"], second["supported"], second["formula"]),
                         ("announced_without_result", DATES[45], ["dividend_result_missing"], False, "unsupported"))
        self.assertEqual(entry["adjusted"], {"supported_from": DATES[45], "reasons": []})  # only dates before it depend on it

        def null_terms(rows, c):
            rows[0].update(CashEarningsDistribution=None, CashStatutorySurplus=None)
            align(c, "3105", nearest(price))
        _, entry = self.dividend_symbol(edit_f4=null_terms)
        self.assertEqual((only_event(entry)["factor"], only_event(entry)["supported"]), ("1/1", True))

        def identical_duplicate(rows, c):
            rows.append(dict(rows[0]))
        _, entry = self.dividend_symbol(edit_f4=identical_duplicate)
        self.assertEqual(only_event(entry), only_event(run(Corpus())["symbols"]["3105"]))

    def test_unsupported_dividend_events_carry_their_reason_and_cut_the_adjusted_basis_at_their_date(self):
        corpus = Corpus()
        day = corpus.event_day["3105"]
        cases = [
            ("dividend_terms_missing", None, lambda rows, c: rows[0].pop("CashEarningsDistribution")),
            ("dividend_terms_invalid", None, lambda rows, c: rows[0].update(CashStatutorySurplus=-1)),
            ("dividend_terms_unmatched", None, lambda rows, c: rows.clear()),
            ("dividend_terms_ambiguous", None, lambda rows, c: rows.append({**rows[0], "CashEarningsDistribution": 9})),
            ("cash_exceeds_price", None, lambda rows, c: rows[0].update(CashEarningsDistribution=500)),
            ("paid_subscription_unsupported", None, lambda rows, c: rows[0].update(TotalNumberOfCashCapitalIncrease=1000)),
            ("paid_subscription_unsupported", None, lambda rows, c: rows[0].update(CashIncreaseSubscriptionRate=0.5)),
            ("paid_subscription_fields_missing", None, lambda rows, c: rows[0].pop("CashIncreaseSubscriptionpRrice")),
            ("event_price_invalid", lambda rows, c: rows[0].update(before_price=None), None),
            ("event_price_invalid", lambda rows, c: rows[0].update(before_price=0), None),
            ("event_price_invalid", lambda rows, c: rows[0].update(reference_price=None), None),
            ("event_price_invalid", lambda rows, c: rows[0].update(reference_price=0), None),
            ("factor_reference_mismatch", None, lambda rows, c: rows[0].update(CashEarningsDistribution=15)),
            ("event_duplicate_conflict", lambda rows, c: rows.append({**rows[0], "reference_price": 1}), None),
        ]
        for reason, edit_f3, edit_f4 in cases:
            _, entry = self.dividend_symbol(edit_f3=edit_f3, edit_f4=edit_f4)
            event = only_event(entry)
            with self.subTest(reason=reason):
                self.assertIn(reason, event["reasons"])
                if reason == "factor_reference_mismatch":  # the computed factor stays visible, only its use is refused
                    self.assertEqual((event["factor"] is not None, event["supported"]), (True, False))
                else:
                    self.assertEqual((event["factor"], event["supported"]), (None, False))
                if reason == "paid_subscription_fields_missing":  # an in-period row without the fields is also a symbol-level reason
                    self.assertEqual(entry["adjusted"], {"supported_from": None, "reasons": [reason]})
                else:
                    self.assertEqual(entry["adjusted"], {"supported_from": day, "reasons": []})
                self.assertEqual(entry["status"], "usable")
                if reason == "dividend_terms_unmatched":
                    self.assertEqual((event["announced_date"], event["announced_time"]), (None, None))
        _, entry = self.dividend_symbol(edit_f3=lambda rows, c: rows.append(dict(rows[0])))  # identical duplicate result rows
        self.assertEqual(only_event(entry)["supported"], True)

    def test_capital_reduction_split_and_par_value_events_use_the_exact_reference_ratio(self):
        corpus = Corpus()
        rows_of(corpus, "capital_reduction", "3293").append(
            {"date": DATES[5], "stock_id": "3293", "ClosingPriceonTheLastTradingDay": 10, "PostReductionReferencePrice": 25,
             "ReasonforCapitalReduction": "彌補虧損", "LimitUp": 27.5})
        rows_of(corpus, "split", "5274").append({"date": DATES[10], "stock_id": "5274", "type": "分割", "before_price": 100, "after_price": 50})
        rows_of(corpus, "par_value", "5347").append(
            {"date": DATES[15], "stock_id": "5347", "stock_name": "N", "before_close": 30, "after_ref_close": 10.5})
        rows_of(corpus, "split", "6488").append({"date": DATES[11], "stock_id": "6488", "before_price": 100, "after_price": 0})
        rows_of(corpus, "par_value", "6510").append({"date": DATES[12], "stock_id": "6510", "before_close": None, "after_ref_close": 3})
        rows_of(corpus, "capital_reduction", "8069").append(
            {"date": DATES[13], "stock_id": "8069", "ClosingPriceonTheLastTradingDay": 8, "PostReductionReferencePrice": 8})
        for symbol, day, reference in (("3293", DATES[5], 25), ("5274", DATES[10], 50), ("5347", DATES[15], 10.5),
                                       ("8069", DATES[13], 8)):
            set_implied(corpus, symbol, day, reference)
        source, _, _ = acquired(corpus=corpus)
        data = data_of(source)["symbols"]
        self.assertEqual(source.inspection()["metrics"]["event_rows"], 7 + 6)
        by_kind = lambda symbol, kind: next(e for e in data[symbol]["events"] if e["kind"] == kind)  # noqa: E731
        event = by_kind("3293", "capital_reduction")
        self.assertEqual((event["date"], event["dataset"], event["before"], event["reference"], event["factor"], event["formula"], event["supported"]),
                         (DATES[5], "capital_reduction", "10/1", "25/1", "5/2", "after_reference/before_close", True))
        self.assertEqual(event["trace"], {"before_field": "ClosingPriceonTheLastTradingDay", "after_field": "PostReductionReferencePrice",
                                          "spread_reference": "25/1", "spread_diff": "0/1", "spread_tick": "1/20"})
        self.assertEqual((event["announced_date"], event["announced_time"]), (None, None))
        self.assertEqual(by_kind("5274", "split")["factor"], "1/2")
        self.assertEqual((by_kind("5347", "par_value_change")["factor"], by_kind("5347", "par_value_change")["dataset"]), ("7/20", "par_value"))
        self.assertEqual(by_kind("8069", "capital_reduction")["factor"], "1/1")
        for symbol, kind in (("6488", "split"), ("6510", "par_value_change")):
            event = by_kind(symbol, kind)
            self.assertEqual((event["reasons"], event["factor"], event["supported"]), (["event_price_invalid"], None, False))
        self.assertEqual(data["6488"]["adjusted"]["supported_from"], DATES[11])  # the latest unsupported event date; its cash event is supported
        self.assertEqual(data["6510"]["adjusted"]["supported_from"], DATES[12])
        self.assertEqual(data["3293"]["events"][0]["kind"], "capital_reduction")  # events are ordered by date then kind

    def test_unsupported_event_dates_and_foreign_or_out_of_window_rows(self):
        corpus = Corpus()
        day = corpus.event_day["3105"]
        rows_of(corpus, "capital_reduction", "3105").append(
            {"date": day, "stock_id": "3105", "ClosingPriceonTheLastTradingDay": 110, "PostReductionReferencePrice": 101})
        rows_of(corpus, "par_value", "3293").append({"date": "2026-07-04", "stock_id": "3293", "before_close": 10, "after_ref_close": 5})
        rows_of(corpus, "split", "3293").append({"date": DATES[30], "stock_id": "3293", "before_price": 10, "after_price": 0})
        rows_of(corpus, "split", "5274").extend([
            {"date": "2026-06-30", "stock_id": "5274", "before_price": 10, "after_price": 5},
            {"date": "2026-10-13", "stock_id": "5274", "before_price": 10, "after_price": 5},
            {"date": DATES[9], "stock_id": "9999", "before_price": 10, "after_price": 5}])
        data = run(corpus)["symbols"]
        kinds = [(e["kind"], e["supported"], e["reasons"]) for e in data["3105"]["events"]]
        self.assertEqual(kinds, [("capital_reduction", False, ["same_day_multiple_events"]),
                                 ("ex_dividend", False, ["same_day_multiple_events"])])
        self.assertEqual(data["3105"]["adjusted"]["supported_from"], day)
        event = next(e for e in data["3293"]["events"] if e["kind"] == "par_value_change")
        self.assertEqual((event["reasons"], event["supported"], event["factor"]),
                         (["event_date_not_trading_day", "factor_reference_unverified"], False, "1/2"))
        self.assertEqual([(e["date"], e["supported"]) for e in data["3293"]["events"]],
                         [("2026-07-04", False), (DATES[23], True), (DATES[30], False)])
        self.assertEqual(data["3293"]["adjusted"]["supported_from"], DATES[30])  # the LATEST unsupported event date cuts the basis
        self.assertEqual(len(data["5274"]["events"]), 1)  # out-of-window and foreign rows add nothing
        self.assertEqual(data["5274"]["foreign_rows"]["split"], 1)
        self.assertEqual(sum(sum(entry["foreign_rows"].values()) for entry in data.values()), 1)
        bad = Corpus()
        rows_of(bad, "split", "8069").append({"date": "2026-06-30", "stock_id": "8069", "before_price": "x", "after_price": 5})
        source, transport, _ = build(corpus=bad)
        self.assertFailure("split_number", source.acquire)
        self.assertEqual(len(transport.opens), step_index("split", "8069") + 1)
        bad = Corpus()
        rows_of(bad, "split", "8069").append({"date": DATES[9], "stock_id": "9999", "before_price": "x", "after_price": 5})
        self.assertFailure("split_number", build(corpus=bad)[0].acquire)  # a foreign row is still structure-checked
        full = {"dividend_result": {"before_price": 1, "after_price": 1, "reference_price": 1},
                "capital_reduction": {"ClosingPriceonTheLastTradingDay": 1, "PostReductionReferencePrice": 1},
                "par_value": {"before_close": 1, "after_ref_close": 1}, "dividend": {}}
        for kind, field in (("dividend_result", "reference_price"), ("capital_reduction", "PostReductionReferencePrice"),
                            ("par_value", "after_ref_close"), ("dividend", "date")):
            bad = Corpus()
            rows_of(bad, kind, "5347").append({"date": DATES[3], "stock_id": "5347", **full[kind], field: "bad"})
            with self.subTest(kind=kind):
                self.assertFailure(kind + ("_date" if field == "date" else "_number"), build(corpus=bad)[0].acquire)

    def test_dividend_only_rows_paid_subscriptions_and_symbol_level_dividend_reasons(self):
        corpus = Corpus()
        add = lambda symbol, **row: rows_of(corpus, "dividend", symbol).append(  # noqa: E731
            {"date": DATES[50], "stock_id": symbol, "StockExDividendTradingDate": "", "AnnouncementDate": "2026-08-01", **row})
        add("3293", CashExDividendTradingDate=DATES[40], CashEarningsDistribution=1, CashStatutorySurplus=0,
            TotalNumberOfCashCapitalIncrease=0, CashIncreaseSubscriptionRate=0, CashIncreaseSubscriptionpRrice=0)
        add("5274", CashExDividendTradingDate=DATES[41], TotalNumberOfCashCapitalIncrease=500, CashIncreaseSubscriptionRate=0.1,
            CashIncreaseSubscriptionpRrice=50)
        add("5347", CashExDividendTradingDate="not-a-date")
        add("6488", CashExDividendTradingDate="", CashEarningsDistribution=3, TotalNumberOfCashCapitalIncrease=0,
            CashIncreaseSubscriptionRate=0, CashIncreaseSubscriptionpRrice=0)
        add("8069", CashExDividendTradingDate="", CashEarningsDistribution=0, StockEarningsDistribution=0,
            TotalNumberOfCashCapitalIncrease=0, CashIncreaseSubscriptionRate=0, CashIncreaseSubscriptionpRrice=0)  # a zero dividend is not a reason
        rows_of(corpus, "dividend", "3105").append({"date": "2026-12-30", "stock_id": "3105", "CashExDividendTradingDate": "2026-12-29",
                                                    "CashEarningsDistribution": 2})  # beyond the window: structure only
        rows_of(corpus, "dividend", "6510")[0].pop("CashIncreaseSubscriptionRate")
        data = run(corpus)["symbols"]
        event = next(e for e in data["3293"]["events"] if e["date"] == DATES[40])
        self.assertEqual((event["kind"], event["reasons"], event["announced_date"], event["announced_time"]),
                         ("announced_without_result", ["dividend_result_missing"], "2026-08-01", None))
        event = next(e for e in data["5274"]["events"] if e["date"] == DATES[41])
        self.assertEqual((event["kind"], event["reasons"]), ("paid_subscription", ["paid_subscription_unsupported"]))
        self.assertEqual(data["5347"]["adjusted"], {"supported_from": None, "reasons": ["f4_date_unparsed"]})
        self.assertEqual(data["6488"]["adjusted"], {"supported_from": None, "reasons": ["f4_ex_date_unknown"]})
        self.assertEqual(data["8069"]["adjusted"], {"supported_from": DATES[0], "reasons": []})
        self.assertEqual(data["3105"]["adjusted"], {"supported_from": DATES[0], "reasons": []})
        self.assertEqual(data["6510"]["adjusted"], {"supported_from": None, "reasons": ["paid_subscription_fields_missing"]})
        self.assertEqual(only_event(data["6510"])["reasons"], ["paid_subscription_fields_missing"])
        for symbol in data:
            self.assertEqual(data[symbol]["status"], "usable")  # the adjusted basis never changes the raw status

    def test_unexplained_reference_change_refuses_only_the_adjusted_basis(self):
        corpus = Corpus()
        corpus.rows["3105"][30]["spread"] += 0.5
        data = run(corpus)
        entry = data["symbols"]["3105"]
        self.assertEqual((entry["spread_check"]["status"], entry["spread_check"]["unexplained_dates"]), ("unexplained_change", [DATES[30]]))
        self.assertEqual(entry["spread_check"]["mismatch_dates"], sorted([DATES[20], DATES[30]]))
        self.assertEqual(entry["adjusted"], {"supported_from": None, "reasons": ["unexplained_change"]})
        self.assertEqual(entry["status"], "usable")
        self.assertEqual(data["symbols"]["3293"], Corpus().expected_symbol("3293"))
        self.assertTrue(data["spread_semantics"]["demonstrated"])

    def test_without_a_demonstrating_event_day_every_symbol_is_semantics_unverified(self):
        corpus = Corpus(adjust=False)  # spread is the raw previous-close difference: events exist but the reference never moves
        data = run(corpus)
        self.assertEqual(data["spread_semantics"], {"demonstrated": False, "evidence": []})
        for symbol in SYMBOLS:
            entry = data["symbols"][symbol]
            with self.subTest(symbol=symbol):
                self.assertEqual(entry["spread_check"]["status"], "semantics_unverified")
                self.assertEqual((entry["spread_check"]["mismatch_dates"], entry["spread_check"]["matched"]), ([], 70))
                self.assertEqual(entry["adjusted"], {"supported_from": None, "reasons": ["semantics_unverified"]})
                self.assertEqual((entry["status"], len(entry["events"])), ("usable", 1))

    def test_too_few_matched_days_is_unverified_for_that_symbol_only(self):
        for keep, status in ((range(25, 45), "semantics_unverified"), (range(25, 46), "consistent")):
            corpus = Corpus()
            for position, row in enumerate(corpus.rows["8069"]):
                if position not in keep:
                    row["spread"] = None
            entry = run(corpus)["symbols"]["8069"]
            with self.subTest(days=len(keep)):
                self.assertEqual((entry["spread_check"]["checked"], entry["spread_check"]["status"]), (len(keep), status))
                self.assertEqual(entry["spread_check"]["matched"], len(keep) - 1)
        corpus = Corpus()
        for row in corpus.rows["3105"]:
            row["spread"] = None
        data = run(corpus)
        self.assertEqual(data["symbols"]["3105"]["spread_check"]["checked"], 0)
        self.assertEqual(data["symbols"]["3105"]["adjusted"]["reasons"], ["semantics_unverified"])
        self.assertEqual(data["symbols"]["3293"], Corpus().expected_symbol("3293"))
        self.assertEqual(data["spread_semantics"]["evidence"], sorted([s, Corpus().event_day[s]] for s in SYMBOLS[1:]))



class ReferenceCrossCheck(Case):
    """Round 1 / R1: a factor is only supported when it agrees, within one tick, with the reference prices the data states."""

    def entry(self, edit, symbol="3105"):
        corpus = Corpus()
        edit(corpus)
        return run(corpus)["symbols"][symbol]

    def test_the_tick_ladder_is_the_97_ladder(self):
        from app import tpex_execution_rules as rules
        self.assertEqual(list(tca.TICK_LADDER_TEXT), ["0=1/100", "10=1/20", "50=1/10", "100=1/2", "500=1", "1000=5"])
        for text in ("0.01", "9.99", "10", "10.01", "49.95", "50", "99.9", "100", "100.5", "499.5", "500", "999", "1000", "5000", "19520"):
            quote = rules.tick_size(Decimal(text), market="TPEx", security_type="ordinary_share", on_date=date(2026, 10, 12),
                                    rule_version=rules.RULES_VERSION, accept_published_only=True)
            with self.subTest(price=text):
                self.assertEqual(tca._tick(Fraction(text)), Fraction(str(quote.tick)))
                self.assertEqual(tca._tick(Fraction(text)), tick_of(Fraction(text)))

    def test_a_wrong_scale_of_the_f4_amounts_is_a_reference_mismatch_and_never_a_first_failure(self):
        day = Corpus().event_day["3105"]
        entry = self.entry(lambda c: rows_of(c, "dividend", "3105")[0].update(CashEarningsDistribution=15))  # 10x the cash dividend
        event = only_event(entry)
        self.assertEqual((event["reasons"], event["supported"]), (["factor_reference_mismatch"], False))
        self.assertEqual(event["factor"], ft((Fraction(205, 2) - Fraction(15)) / Fraction(205, 2)))  # the computed factor stays visible
        trace = event["trace"]
        self.assertEqual((trace["R"], trace["f3_reference"], trace["f3_diff"], trace["f3_tick"]), ("175/2", "101/1", "27/2", "1/2"))
        self.assertEqual((trace["spread_reference"], trace["spread_diff"], trace["spread_tick"]), ("101/1", "27/2", "1/2"))
        self.assertEqual(entry["adjusted"], {"supported_from": day, "reasons": []})
        self.assertEqual(entry["status"], "usable")
        entry = self.entry(lambda c: rows_of(c, "dividend", "3105")[0].update(StockExDividendTradingDate=day, StockEarningsDistribution=10))
        self.assertEqual(only_event(entry)["reasons"], ["factor_reference_mismatch"])  # stock dividend 10x: Rf = 1
        self.assertEqual(only_event(entry)["trace"]["Rf"], "1/1")

    def test_the_f3_check_alone_decides_when_the_event_day_has_no_price_row(self):
        # P = 101.5 and C = 1.5 give R = 100 exactly; the tolerance is one tick of the OBSERVED reference.
        def setup(reference):
            def edit(c):
                rows_of(c, "dividend_result", "3105")[0].update(before_price=101.5, reference_price=reference, after_price=reference)
                c.rows["3105"].remove(next(r for r in c.rows["3105"] if r["date"] == c.event_day["3105"]))
            return edit
        for reference, supported in ((100.0, True), (99.95, True), (99.9, False), (100.25, True), (100.4, True), (100.5, False), (100.6, False)):
            event = only_event(self.entry(setup(reference)))
            with self.subTest(reference=reference):
                self.assertEqual((event["supported"], event["reasons"]), (supported, [] if supported else ["factor_reference_mismatch"]))
                self.assertEqual((event["trace"]["R"], event["trace"]["spread_reference"], event["trace"]["spread_diff"]), ("100/1", None, None))
                self.assertEqual(event["trace"]["f3_tick"], ft(tick_of(Fraction(str(reference)))))

    def test_the_spread_reference_must_be_within_one_tick_too_and_both_checks_are_required(self):
        day = Corpus().event_day["3105"]
        for implied, supported in ((101.0, True), (101.25, True), (100.75, True), (101.5, False), (100.5, False), (102.0, False), (-5.0, False)):
            event = only_event(self.entry(lambda c: set_implied(c, "3105", day, implied)))  # F3 keeps stating 101
            with self.subTest(implied=implied):
                self.assertEqual((event["supported"], event["reasons"]), (supported, [] if supported else ["factor_reference_mismatch"]))
                self.assertEqual(event["trace"]["spread_reference"], ft(Fraction(str(implied))))
                self.assertEqual(event["trace"]["f3_diff"], "0/1")
        # F3 off by a tick while the spread agrees is also a mismatch
        event = only_event(self.entry(lambda c: align(c, "3105", 101.5) or set_implied(c, "3105", day, 101.0)))
        self.assertEqual((event["supported"], event["reasons"]), (False, ["factor_reference_mismatch"]))
        # the check never changes the spread consistency or the raw status
        entry = self.entry(lambda c: set_implied(c, "3105", day, 99.0))
        self.assertEqual((entry["status"], entry["spread_check"]["status"]), ("usable", "consistent"))

    def test_the_stated_reference_price_must_be_a_positive_number(self):
        for value in (None, 0, -1):
            event = only_event(self.entry(lambda c: rows_of(c, "dividend_result", "3105")[0].update(reference_price=value)))
            with self.subTest(value=value):
                self.assertEqual((event["reasons"], event["supported"], event["factor"]), (["event_price_invalid"], False, None))

    def test_reduction_split_and_par_value_factors_need_a_matching_spread_reference(self):
        kinds = (("capital_reduction", "3293", {"ClosingPriceonTheLastTradingDay": 10, "PostReductionReferencePrice": 25}, 25, "capital_reduction"),
                 ("split", "5274", {"before_price": 100, "after_price": 50}, 50, "split"),
                 ("par_value", "5347", {"before_close": 30, "after_ref_close": 10.5}, 10.5, "par_value_change"))
        for kind, symbol, values, after, event_kind in kinds:
            def run_case(implied=None, remove_row=False, zero_row=False, spread_none=False):
                corpus = Corpus()
                rows_of(corpus, kind, symbol).append({"date": DATES[5], "stock_id": symbol, **values})
                row = next(r for r in corpus.rows[symbol] if r["date"] == DATES[5])
                if implied is not None:
                    set_implied(corpus, symbol, DATES[5], implied)
                if remove_row:
                    corpus.rows[symbol].remove(row)
                if zero_row:
                    row.update(open=0, max=0, min=0, close=0, spread=0)
                if spread_none:
                    row["spread"] = None
                entry = run(corpus)["symbols"][symbol]
                return entry, next(e for e in entry["events"] if e["kind"] == event_kind)
            target = Fraction(str(after))
            offsets = {"25": ("25", "25.04", "24.96", "25.05", "24.95", "75"), "50": ("50", "50.08", "49.92", "50.1", "49.9", "150"),
                       "10.5": ("10.5", "10.54", "10.46", "10.55", "10.45", "31.5")}[str(after)]
            cases = [(float(Fraction(text)), abs(Fraction(text) - target) < tick_of(Fraction(text))) for text in offsets]
            self.assertEqual({supported for _, supported in cases}, {True, False})
            for implied, supported in cases:
                entry, event = run_case(implied=implied)
                with self.subTest(kind=kind, implied=implied):
                    self.assertEqual((event["supported"], event["reasons"]),
                                     (supported, [] if supported else ["factor_reference_mismatch"]))
                    self.assertEqual(event["trace"]["spread_reference"], ft(Fraction(str(implied))))
                    self.assertIsNotNone(event["factor"])  # the computed factor stays visible; only its use is refused
            for label, options in (("no row", dict(remove_row=True)), ("zero row", dict(zero_row=True)), ("no spread", dict(spread_none=True))):
                entry, event = run_case(**options)
                with self.subTest(kind=kind, case=label):
                    self.assertEqual((event["supported"], event["reasons"]), (False, ["factor_reference_unverified"]))
                    self.assertEqual((event["trace"]["spread_reference"], event["trace"]["spread_diff"], event["trace"]["spread_tick"]),
                                     (None, None, None))


# --- saving, reading back and the read interface -------------------------------------------------------------

def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def trusted(source):
    """Admission bound to the source's own derived bytes: for storage tests of variant corpora only."""
    return tca.OracleAdmission(
        NAMESPACE, source._pins.sha256, "synthetic-boundary-oracle", "a" * 40, "b" * 64,
        tuple(receipt_hash(capture.receipt) for capture in source.inspection()["captures"]),
        source._metrics["calendar_rows"], source._metrics["price_rows"], source._metrics["event_rows"],
        hashlib.sha256(source.inspection()["data_bytes"]).hexdigest(), True)


def variant_source(corpus):
    source, _, _ = acquired(corpus=corpus)
    source.admit_independent_verification(trusted(source))
    return source


def expected_receipt(source, corpus, saved_at):
    gets = []
    for capture in source.inspection()["captures"]:
        entry = {f.name: getattr(capture.receipt, f.name) for f in dataclasses.fields(capture.receipt)}
        entry["receipt_sha256"] = receipt_hash(capture.receipt)
        gets.append(entry)
    data_bytes = canonical(corpus.expected_data())
    digest = hashlib.sha256(data_bytes).hexdigest()
    return {
        "schema": RECEIPT_SCHEMA, "storage": "private_local", "storage_schema": STORAGE_SCHEMA, "namespace": NAMESPACE,
        "purpose": PURPOSE, "consumer_version": CONSUMER,
        "source_policy": {"version": POLICY_VERSION, "sha256": source._pins.sha256, "bytes": source._pins.nbytes},
        "calendar_source_version": CALENDAR_VERSION, "market": "TW/TPEx", "instrument_type": "ordinary_stock",
        "identity_as_of": IDENTITY, "window": {"start_date": START, "end_date": END, "dividend_end_date": DIV_END},
        "calendar_rows": 71, "gets": gets,
        "adapter": {"tpex_calendar_actions_source_sha256": hashlib.sha256(TCA_FILE.read_bytes()).hexdigest(),
                    "ohlcv_history_source_sha256": hashlib.sha256(BASE_FILE.read_bytes()).hexdigest()},
        "data": {"file": "data.json", "sha256": digest, "bytes": len(data_bytes)}, "data_version": DATA_PREFIX + digest,
        "saved_at": saved_at, "attribution": ATTRIBUTION, "rights": RIGHTS,
        "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
        "limitations": LIMITATIONS,
    }


class Saving(Case):
    def final(self, root):
        return os.path.join(root, POLICY_VERSION, END)

    def test_bundle_is_the_independent_expectation_and_stores_no_raw_values(self):
        corpus = Corpus()
        source, transport, _ = available(corpus=corpus)
        root = self.new_root()
        saved = source.save(root=root)
        final = self.final(root)
        data_bytes, receipt_bytes = read_bytes(os.path.join(final, "data.json")), read_bytes(os.path.join(final, "receipt.json"))
        self.assertEqual(self.tree(root), [
            (POLICY_VERSION, None), (os.path.join(POLICY_VERSION, END), None),
            (os.path.join(POLICY_VERSION, END, "data.json"), len(data_bytes)),
            (os.path.join(POLICY_VERSION, END, "receipt.json"), len(receipt_bytes))])
        self.assertEqual(data_bytes, canonical(corpus.expected_data()))
        receipt = json.loads(receipt_bytes)
        self.assertEqual(receipt, expected_receipt(source, corpus, receipt["saved_at"]))
        self.assertEqual(receipt_bytes, canonical(receipt))
        self.assertEqual((saved.action, saved.policy_version, saved.window_end, saved.path, saved.saved_at),
                         ("created", POLICY_VERSION, END, final, receipt["saved_at"]))
        self.assertEqual((saved.data_sha256, saved.data_bytes, saved.receipt_sha256, saved.receipt_bytes),
                         (hashlib.sha256(data_bytes).hexdigest(), len(data_bytes), hashlib.sha256(receipt_bytes).hexdigest(), len(receipt_bytes)))
        self.assertLess(len(data_bytes), tca.DATA_CAP)
        self.assertLess(len(receipt_bytes), tca.RECEIPT_CAP)
        blob = data_bytes + receipt_bytes
        for symbol, values in ANCHORS.items():  # no raw volume / amount / body bytes
            for number in values[4:]:
                self.assertNotIn(str(number).encode(), blob)
        for body in corpus.bodies[:3]:
            self.assertNotIn(body[:60], blob)
        self.assertEqual(len(transport.opens), 44)  # saving never fetched anything
        self.assertEqual(source.ledger.attempted, tuple(range(44)))
        if os.name != "nt":
            self.assertEqual(stat_mode(os.path.join(final, "data.json")) & 0o077, 0)

    def test_the_save_root_can_never_be_the_real_private_root_and_the_default_is_it(self):
        source, _, _ = available()
        self.assertFailure("root_required_for_boundary", source.save)
        for spelling in (REAL_ROOT, REAL_ROOT.replace("/", "\\"), REAL_ROOT + "/", REAL_ROOT.upper()):
            with self.subTest(spelling=spelling):
                self.assertFailure("boundary_root_is_private_root", source.save, root=spelling)
        dotted = REAL_ROOT.replace("taiwan-stock-research/", "taiwan-stock-research/../taiwan-stock-research/")
        for bad in ("r", "..", "rel/path", "", "x\x00y", 5, b"bytes", dotted):
            with self.subTest(bad=bad):
                self.assertFailure("root_invalid", source.save, root=bad)
        self.assertFailure("source_required", tca.save_calendar_actions, object(), root=self.new_root())
        seen = []
        with patch.object(tca, "_publish", lambda root, data, receipt, pins: seen.append(root) or "published"):
            source._real = True  # test-only: the default transport's save target
            self.assertFailure("root_not_private_root", source.save, root=self.new_root())
            self.assertFailure("root_invalid", source.save, root=5)
            self.assertEqual(tca.save_calendar_actions(source), "published")
            self.assertEqual(source.save(root=REAL_ROOT.replace("/", "\\")), "published")
            self.assertEqual(source.save(root=REAL_ROOT), "published")
        self.assertEqual(seen, [REAL_ROOT, REAL_ROOT, REAL_ROOT])  # whatever spelling was accepted, the target is the fixed path

    def test_resaving_is_idempotent_and_different_content_is_refused(self):
        source, _, _ = available()
        root = self.new_root()
        first = source.save(root=root)
        before = self.tree(root)
        again = source.save(root=root)
        self.assertEqual((again.action, again.saved_at, again.data_sha256), ("idempotent", first.saved_at, first.data_sha256))
        self.assertEqual(self.tree(root), before)
        other = variant_source(Corpus(adjust=False))
        error = self.assertFailure("final_conflict", other.save, root=root)
        self.assertNotIn("saved_at", dict(error.diagnostics))
        self.assertEqual(self.tree(root), before)
        self.assertEqual(tca.load_saved(root, pins=source._pins).data_sha256, first.data_sha256)

    def test_quota_of_bundles_files_and_bytes_fails_closed_without_partial_writes(self):
        source, _, _ = available()
        for name, value, code in (("MAX_BUNDLES", 0, "quota_bundles"), ("MAX_FILES", 1, "quota_files"),
                                  ("MAX_TOTAL_BYTES", 100, "quota_bytes")):
            root = self.new_root()
            with self.subTest(quota=name), patch.object(tca, name, value):
                self.assertFailure(code, source.save, root=root)
                self.assertFalse(os.path.lexists(root))  # the root this call created is removed again
            existing = self.new_dir()
            with self.subTest(quota=name, existing=True), patch.object(tca, name, value):
                self.assertFailure(code, source.save, root=existing)
                self.assertEqual(os.listdir(existing), [])
        with patch.object(tca, "DATA_CAP", 100):
            self.assertFailure("data_cap", source.save, root=self.new_root())
        with patch.object(tca, "RECEIPT_CAP", 100):
            self.assertFailure("receipt_cap", source.save, root=self.new_root())

    def test_failures_leave_no_staging_and_the_snapshot_can_save_again(self):
        source, _, _ = available()
        for label, target, error in (("write", "os.write", OSError(28, "no space")), ("fsync", "os.fsync", OSError(5, "io")),
                                     ("rename", "os.rename", OSError(13, "denied")), ("mkdir", "os.mkdir", OSError(13, "denied"))):
            root = self.new_root()
            with self.subTest(failure=label), patch(target, side_effect=error):
                caught = self.assertFailure("storage_io_failure", source.save, root=root)
                self.assertEqual(caught.diagnostics["errno"], error.errno)
                self.assertFalse(os.path.lexists(root), self.tree(root) if os.path.lexists(root) else "")
        root = self.new_root()
        os.mkdir(root)  # an existing empty root is left exactly as found
        with patch("os.rename", side_effect=OSError(13, "denied")):
            self.assertFailure("storage_io_failure", source.save, root=root)
        self.assertEqual(os.listdir(root), [])
        self.assertEqual(source.save(root=root).action, "created")

    def test_read_back_failure_is_reported_and_the_published_bundle_is_kept_for_inspection(self):
        source, _, _ = available()
        root = self.new_root()
        with patch.object(tca, "_load_verified", side_effect=tca.SourceError("saved_shape")):
            error = self.assertFailure("saved_readback_failed", source.save, root=root)
        self.assertEqual(error.diagnostics["reader_code"], "saved_shape")
        self.assertEqual(sorted(os.listdir(self.final(root))), ["data.json", "receipt.json"])
        root = self.new_root()
        real = tca._load_verified
        with patch.object(tca, "_load_verified", lambda *a: (b"x",) + real(*a)[1:]):
            self.assertFailure("saved_readback_mismatch", source.save, root=root)
        self.assertEqual(sorted(os.listdir(self.final(root))), ["data.json", "receipt.json"])

    def test_root_that_is_not_exactly_the_expected_layout_fails_closed_untouched(self):
        source, _, _ = available()
        cases = {
            "stray_file": lambda root: write_bytes(os.path.join(root, "stray.txt"), b"x"),
            "staging_leftover": lambda root: os.mkdir(os.path.join(root, ".staging-0123456789abcdef")),
            "other_policy_dir": lambda root: os.mkdir(os.path.join(root, "issue98-other-v1")),
            "other_window_dir": lambda root: (os.mkdir(os.path.join(root, POLICY_VERSION)),
                                              os.mkdir(os.path.join(root, POLICY_VERSION, "2026-10-13"))),
            "empty_final": lambda root: (os.mkdir(os.path.join(root, POLICY_VERSION)), os.mkdir(os.path.join(root, POLICY_VERSION, END))),
            "policy_dir_is_a_file": lambda root: write_bytes(os.path.join(root, POLICY_VERSION), b"x"),
        }
        for name, build_root in cases.items():
            root = self.new_root()
            os.mkdir(root)
            build_root(root)
            before = self.tree(root)
            with self.subTest(layout=name):
                with self.assertRaises(tca.SourceError) as caught:
                    source.save(root=root)
                self.assertIn(caught.exception.code, ("root_entries_invalid", "saved_not_dir"))
                self.assertEqual(self.tree(root), before)
        file_root = os.path.join(self.new_dir(), "file")
        write_bytes(file_root, b"x")
        self.assertFailure("saved_not_dir", source.save, root=file_root)
        missing_parent = os.path.join(self.new_dir(), "missing", "r")
        self.assertFailure("saved_missing", source.save, root=missing_parent)
        self.assertFalse(os.path.lexists(os.path.dirname(missing_parent)))

    def test_concurrent_save_is_refused_while_the_lock_is_held(self):
        source, _, _ = available()
        self.assertTrue(tca._SAVE_LOCK.acquire(blocking=False))
        try:
            self.assertFailure("storage_busy", source.save, root=self.new_root())
        finally:
            tca._SAVE_LOCK.release()


def stat_mode(path):
    return os.stat(path).st_mode


def saved_bundle(case, corpus=None):
    source = variant_source(corpus) if corpus is not None else available()[0]
    root = case.new_root()
    source.save(root=root)
    return root, source


KW = dict(market="TPEx", security_type="ordinary_share", purpose=PURPOSE)


def thaw(value):
    if isinstance(value, (dict, types.MappingProxyType)):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return value


class Reader(Case):
    def test_valid_bundle_loads_exact_values_and_derives_the_cumulative_factor(self):
        corpus = Corpus()
        root, source = saved_bundle(self, None)
        saved = tca.load_saved(root, pins=source._pins)
        digest = hashlib.sha256(canonical(corpus.expected_data())).hexdigest()
        self.assertEqual((saved.data_sha256, saved.data_version, saved.policy_version), (digest, DATA_PREFIX + digest, POLICY_VERSION))
        self.assertEqual((saved.calendar, saved.calendar_after_formal), (DATES, BEYOND))
        self.assertEqual(saved.receipt["data_version"], saved.data_version)
        self.assertEqual(saved.receipt_sha256, hashlib.sha256(read_bytes(os.path.join(root, POLICY_VERSION, END, "receipt.json"))).hexdigest())
        kw = dict(KW, data_version=saved.data_version)
        self.assertEqual(saved.trading_days(**kw), DATES)
        self.assertEqual(thaw(saved.events(symbol="3105", **kw)), [corpus.event_dict("3105")])
        for symbol in SYMBOLS:
            day, price, cash = corpus.event_day[symbol], Fraction(str(corpus.prior[symbol])), Fraction(str(corpus.cash[symbol]))
            factor = (price - cash) / price
            index = DATES.index(day)
            raw = saved.read_day(symbol=symbol, on_date=DATES[index - 1], basis="raw", **kw)
            before = saved.read_day(symbol=symbol, on_date=DATES[index - 1], basis="adjusted", **kw)
            on_day = saved.read_day(symbol=symbol, on_date=day, basis="adjusted", **kw)
            last = saved.read_day(symbol=symbol, on_date=IDENTITY, basis="adjusted", **kw)
            with self.subTest(symbol=symbol):
                self.assertEqual((raw.factor, raw.events, raw.basis, raw.data_version), (None, (), "raw", saved.data_version))
                self.assertEqual((before.factor, before.events), (factor, ((day, "ex_dividend", factor),)))
                self.assertEqual((on_day.factor, on_day.events, last.factor), (Fraction(1), (), Fraction(1)))
                self.assertIs(type(before.factor), Fraction)
        provenance = saved.read_day(symbol="3105", on_date=DATES[0], basis="raw", **kw).provenance
        self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]),
                         ("unknown", "unknown", "unknown"))
        self.assertEqual((provenance["data_version"], provenance["namespace"], provenance["storage"]),
                         (saved.data_version, NAMESPACE, "private_local"))
        self.assertEqual(list(provenance["unsupported"]), UNSUPPORTED)
        self.assertEqual(list(provenance["limitations"]), LIMITATIONS)
        with self.assertRaises(TypeError):
            provenance["publication_time"] = "now"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            saved.data_version = "x"

    def test_scope_arguments_and_every_refusal_of_the_read_interface(self):
        root, source = saved_bundle(self)
        saved = tca.load_saved(root, pins=source._pins)
        kw = dict(KW, data_version=saved.data_version)
        read = lambda **changes: saved.read_day(**{"symbol": "3105", "on_date": DATES[3], "basis": "raw", **kw, **changes})  # noqa: E731
        self.assertEqual(read().on_date, DATES[3])
        for code, changes in (
                ("unsupported_market", dict(market="TWSE")), ("unsupported_market", dict(market=None)),
                ("unsupported_security_type", dict(security_type="etf")), ("unsupported_security_type", dict(security_type=None)),
                ("unsupported_symbol", dict(symbol="2330")), ("unsupported_symbol", dict(symbol=3105)),
                ("data_version_mismatch", dict(data_version=DATA_PREFIX + "0" * 64)), ("data_version_mismatch", dict(data_version=None)),
                ("unsupported_purpose", dict(purpose="strategy")), ("unsupported_purpose", dict(purpose=None)),
                ("unsupported_basis", dict(basis="latest")), ("unsupported_basis", dict(basis=None)),
                ("date_invalid", dict(on_date="2026-7-3")), ("date_invalid", dict(on_date="20260703")),
                ("date_invalid", dict(on_date=date(2026, 7, 3))), ("date_invalid", dict(on_date=None)),
                ("date_outside_window", dict(on_date="2026-06-30")), ("date_outside_window", dict(on_date="2026-10-13")),
                ("date_not_in_observed_calendar", dict(on_date="2026-07-04")),
                ("date_not_in_observed_calendar", dict(on_date="2026-10-09"))):
            with self.subTest(code=code, changes=str(changes)):
                self.assertFailure(code, read, **changes)
        for method, extra in (("trading_days", {}), ("events", {"symbol": "3105"})):
            for code, changes in (("unsupported_market", dict(market="TWSE")), ("unsupported_security_type", dict(security_type="x")),
                                  ("data_version_mismatch", dict(data_version="x")), ("unsupported_purpose", dict(purpose="x"))):
                with self.subTest(method=method, code=code):
                    self.assertFailure(code, getattr(saved, method), **{**kw, **extra, **changes})
        self.assertFailure("unsupported_symbol", saved.events, symbol="2330", **kw)

    def test_refused_symbols_incomparable_days_and_unsupported_adjusted_basis_are_refused_not_estimated(self):
        corpus = Corpus()
        info = corpus.docs[43]["data"]
        next(row for row in info if row["stock_id"] == "3293")["type"] = "twse"
        del corpus.rows["3105"][5]
        corpus.rows["3105"][5]["spread"] = corpus.rows["3105"][5]["close"] - corpus.rows["3105"][4]["close"]
        corpus.rows["5274"][30]["spread"] += 0.5
        rows_of(corpus, "capital_reduction", "5347").append(
            {"date": DATES[44], "stock_id": "5347", "ClosingPriceonTheLastTradingDay": 10, "PostReductionReferencePrice": 0})
        corpus.rows["6488"][-4]["close"] += 1  # the 2026-10-06 anchor row no longer equals SOURCE_REGISTRY 32.2
        next(row for row in info if row["stock_id"] == "6488")["type"] = "twse"  # two reasons: the first (sorted) one is reported
        corpus.rows["6510"].insert(2, {**corpus.rows["6510"][0], "date": "2026-07-04"})  # a priced row on a non-calendar day
        info[:] = [row for row in info if row["stock_id"] != "8069"]
        root, source = saved_bundle(self, corpus)
        saved = tca.load_saved(root, pins=source._pins)
        kw = dict(KW, data_version=saved.data_version)
        # QA F-1: one gate for every symbol-scoped read, so events() refuses a refused symbol exactly like read_day
        refused = {"3293": "market_type_not_accepted", "6488": "identity_anchor_mismatch", "6510": "price_row_off_calendar",
                   "8069": "info_missing"}
        for symbol, reason in refused.items():
            calls = {"events": lambda: saved.events(symbol=symbol, **kw),
                     "raw": lambda: saved.read_day(symbol=symbol, on_date=DATES[3], basis="raw", **kw),
                     "adjusted": lambda: saved.read_day(symbol=symbol, on_date=DATES[3], basis="adjusted", **kw),
                     "bad arguments": lambda: saved.read_day(symbol=symbol, on_date="bad", basis="nope", **kw)}
            for name, call in calls.items():
                with self.subTest(refused=symbol, call=name):
                    self.assertEqual(self.assertFailure("symbol_refused", call).diagnostics["reason"], reason)
        for symbol in ("3105", "5274", "5347"):  # usable symbols still return their event tables, supported or not
            self.assertGreaterEqual(len(saved.events(symbol=symbol, **kw)), 1)
        self.assertFailure("unsupported_symbol", saved.events, symbol="2330", **kw)
        self.assertFailure("unsupported_market", saved.events, symbol="3293", **dict(kw, market="TWSE"))  # scope is checked before the gate
        self.assertFailure("data_version_mismatch", saved.events, symbol="3293", **dict(kw, data_version=DATA_PREFIX + "0" * 64))
        self.assertFalse(hasattr(saved, "symbols"))  # no public mapping that bypasses the gate
        self.assertEqual(len(saved.trading_days(**kw)), 71)  # not symbol-scoped: no gate
        self.assertFailure("symbol_refused", saved.read_day, symbol="3293", on_date=DATES[3], basis="raw", **kw)
        self.assertEqual(self.assertFailure("symbol_refused", saved.read_day, symbol="3293", on_date=DATES[3], basis="adjusted", **kw)
                         .diagnostics["reason"], "market_type_not_accepted")
        gap = self.assertFailure("day_incomparable", saved.read_day, symbol="3105", on_date=DATES[5], basis="raw", **kw)
        self.assertEqual(gap.diagnostics["reason"], "missing_row")
        self.assertEqual(saved.read_day(symbol="3105", on_date=DATES[6], basis="raw", **kw).factor, None)
        self.assertEqual(saved.read_day(symbol="5274", on_date=DATES[6], basis="raw", **kw).basis, "raw")
        error = self.assertFailure("adjusted_unsupported", saved.read_day, symbol="5274", on_date=DATES[6], basis="adjusted", **kw)
        self.assertEqual(error.diagnostics["reason"], "unexplained_change")
        for day in (DATES[43], DATES[44], DATES[45], IDENTITY):  # the unsupported reduction is dated DATES[44]: only days before it are cut
            with self.subTest(day=day):
                if day < DATES[44]:
                    self.assertEqual(self.assertFailure("adjusted_unsupported", saved.read_day, symbol="5347", on_date=day,
                                                        basis="adjusted", **kw).diagnostics["reason"], "event_unsupported")
                else:
                    self.assertEqual(saved.read_day(symbol="5347", on_date=day, basis="adjusted", **kw).factor, Fraction(1))
        self.assertEqual(saved.read_day(symbol="5347", on_date=DATES[3], basis="raw", **kw).factor, None)

    def rebuilt(self, source, data_document, mutate=None):
        data_bytes = canonical(data_document)
        receipt = source._receipt_document(tca._utc_now())
        digest = hashlib.sha256(data_bytes).hexdigest()
        receipt["data"] = {"file": "data.json", "sha256": digest, "bytes": len(data_bytes)}
        receipt["data_version"] = DATA_PREFIX + digest
        if mutate:
            mutate(receipt)
        return data_bytes, canonical(receipt)

    def test_data_contract_violations_are_refused_by_the_reader_before_any_use(self):
        source, _, _ = available()
        pins = source._pins
        good = Corpus().expected_data()
        data_bytes, receipt_bytes = self.rebuilt(source, good)
        data, receipt = tca._verify_bundle(data_bytes, receipt_bytes, pins)
        self.assertEqual((data, receipt["data_version"]), (good, DATA_PREFIX + hashlib.sha256(data_bytes).hexdigest()))

        def sym(change, symbol="3105"):
            return lambda d: change(d["symbols"][symbol])

        def ev(change, symbol="3105"):
            return lambda d: change(d["symbols"][symbol]["events"][0])
        cases = [
            ("saved_shape", lambda d: d.update(extra=1)), ("saved_shape", lambda d: d.pop("observed_fields")),
            ("saved_value", lambda d: d.update(schema="x")),
            ("saved_value", lambda d: d["window"].update(end_date="2026-10-13")),
            ("saved_calendar", lambda d: d["calendar"].reverse()), ("saved_calendar", lambda d: d["calendar"].insert(2, "2026-07-04")),
            ("saved_calendar", lambda d: d["calendar"].append("2026-10-13")), ("saved_calendar", lambda d: d.update(calendar=[])),
            ("saved_calendar", lambda d: d["calendar"].remove(IDENTITY)), ("saved_calendar", lambda d: d["calendar"].__setitem__(0, 7)),
            ("saved_calendar", lambda d: d["calendar_after_formal"].pop()),
            ("saved_spread_status", lambda d: d["spread_semantics"].update(demonstrated=False)),
            ("saved_semantics", lambda d: d["spread_semantics"]["evidence"].pop()),
            ("saved_semantics", lambda d: d["spread_semantics"].update(extra=1)),
            ("saved_shape", lambda d: d["observed_fields"].update(unknown_kind=["a"])),
            ("saved_shape", lambda d: d["observed_fields"].update(price=["b", "a"])),
            ("saved_shape", lambda d: d["symbols"].pop("8069")),
            ("saved_symbol", sym(lambda e: e.update(extra=1))), ("saved_symbol", sym(lambda e: e.update(status="maybe"))),
            ("saved_symbol", sym(lambda e: e.update(status="refused"))),
            ("saved_symbol", sym(lambda e: e.update(refusal_reasons=["info_missing"]))),
            ("saved_symbol", sym(lambda e: e["info"].update(type=5))), ("saved_symbol", sym(lambda e: e["info"].update(date="2026-9-30"))),
            ("saved_symbol", sym(lambda e: e.update(incomparable_days=[["2026-07-02", "unknown_reason"]]))),
            ("saved_symbol", sym(lambda e: e.update(incomparable_days=[["2026-07-04", "missing_row"]]))),
            ("saved_symbol", sym(lambda e: e.update(incomparable_days=[[DATES[3], "missing_row"], [DATES[2], "missing_row"]]))),
            ("saved_symbol", sym(lambda e: e["spread_check"].update(matched=e["spread_check"]["checked"] + 1))),
            ("saved_symbol", sym(lambda e: e["spread_check"].update(mismatch_dates=[]))),
            ("saved_symbol", sym(lambda e: e["spread_check"].update(unexplained_dates=e["spread_check"]["demonstrating_dates"]))),
            ("saved_symbol", sym(lambda e: e["spread_check"].update(checked=True))),
            ("saved_spread_status", sym(lambda e: e["spread_check"].update(status="semantics_unverified"))),
            ("saved_spread_status", sym(lambda e: e["spread_check"].update(status="bogus"))),
            ("saved_event", sym(lambda e: e.update(events=[e["events"][0], e["events"][0]]))),
            ("saved_event", sym(lambda e: e.update(events="x"))),
            ("saved_event", ev(lambda x: x.update(extra=1))), ("saved_event", ev(lambda x: x.update(kind="unknown"))),
            ("saved_event", ev(lambda x: x.update(dataset="price"))), ("saved_event", ev(lambda x: x.update(date="2026-06-30"))),
            ("saved_event", ev(lambda x: x.update(announced_date="2026-7-20"))),
            ("saved_event", ev(lambda x: x.update(announced_time=""))), ("saved_event", ev(lambda x: x.update(factor="2/4"))),
            ("saved_event", ev(lambda x: x.update(factor="0/1"))), ("saved_event", ev(lambda x: x.update(before="-1/2"))),
            ("saved_event", ev(lambda x: x.update(formula="P*Q"))), ("saved_event", ev(lambda x: x.update(trace={"a": 5}))),
            ("saved_event", ev(lambda x: x.update(supported=False))),
            ("saved_event", ev(lambda x: x.update(reasons=["event_price_invalid"]))),
            ("saved_event", ev(lambda x: x.update(reasons=["Bad Code"], supported=False))),
            ("saved_event", ev(lambda x: x.update(date="2026-07-04"))),
            ("saved_event", sym(lambda e: e["spread_check"].update(unexplained_dates=[e["events"][0]["date"]],
                                                                   demonstrating_dates=[], status="unexplained_change"))),
            ("saved_adjusted", sym(lambda e: e["adjusted"].update(supported_from=DATES[5]))),
            ("saved_adjusted", sym(lambda e: e["adjusted"].update(supported_from=None))),
            ("saved_adjusted", sym(lambda e: e["adjusted"].update(reasons=["f4_date_unparsed"]))),
            ("saved_adjusted", sym(lambda e: e["adjusted"].update(supported_from="2026-7-1"))),
            ("saved_symbol", sym(lambda e: e["foreign_rows"].update(split=-1))),
            ("saved_symbol", sym(lambda e: e["foreign_rows"].pop("split"))),
        ]
        for code, edit in cases:
            document = Corpus().expected_data()
            edit(document)
            blob, receipt_blob = self.rebuilt(source, document)
            with self.subTest(code=code, case=cases.index((code, edit))):
                self.assertFailure(code, tca._verify_bundle, blob, receipt_blob, pins)
        two = Corpus().expected_data()
        two["symbols"]["3105"]["events"].append({**two["symbols"]["3105"]["events"][0], "kind": "split", "dataset": "split"})
        blob, receipt_blob = self.rebuilt(source, two)
        self.assertFailure("saved_event", tca._verify_bundle, blob, receipt_blob, pins)  # two events on one date need the same-day reason

    def test_byte_level_data_violations(self):
        source, _, _ = available()
        pins = source._pins
        good = canonical(Corpus().expected_data())
        base_receipt = self.rebuilt(source, json.loads(good))[1]
        pretty = json.dumps(json.loads(good), indent=1, sort_keys=True).encode()
        for code, data in (("saved_not_canonical", pretty), ("saved_not_canonical", good + b"\n"), ("saved_parse", b"not json"),
                           ("saved_parse", b"\xff\xfe"), ("saved_shape", b"[]"), ("duplicate_json_key", b'{"a":1,"a":2}'),
                           ("saved_size_cap", good + b" " * tca.DATA_CAP)):
            with self.subTest(code=code):
                self.assertFailure(code, tca._verify_bundle, data, base_receipt, pins)
        self.assertFailure("saved_size_cap", tca._verify_bundle, good, base_receipt + b" " * tca.RECEIPT_CAP, pins)

    def test_receipt_contract_violations_are_refused_by_the_reader(self):
        source, _, _ = available()
        pins = source._pins
        good = Corpus().expected_data()

        def get(index, **changes):
            def edit(receipt):
                receipt["gets"][index].update(changes)
            return edit

        def rehash(index, **changes):
            def edit(receipt):
                entry = receipt["gets"][index]
                entry.update(changes)
                entry["receipt_sha256"] = hashlib.sha256(canonical({k: entry[k] for k in tca._RECEIPT_FIELDS})).hexdigest()
            return edit

        def top(**changes):
            return lambda receipt: receipt.update(changes)
        cases = [
            ("saved_shape", top(extra=1)), ("saved_shape", lambda r: r["gets"].pop()), ("saved_shape", lambda r: r.pop("data_version")),
            ("saved_value", top(schema="x")), ("saved_value", top(storage="public")), ("saved_value", top(namespace="issue98-other/qa1")),
            ("saved_value", top(purpose="strategy")), ("saved_value", top(consumer_version="x")), ("saved_value", top(market="TWSE")),
            ("saved_value", top(instrument_type="etf")), ("saved_value", top(identity_as_of="2026-10-05")),
            ("saved_value", top(publication_time="2026-10-12")), ("saved_value", top(first_availability="now")),
            ("saved_value", top(revision_time="never")), ("saved_value", top(limitations=LIMITATIONS[:-1] + ["other"])),
            ("saved_value", lambda r: r["window"].update(end_date="2026-10-13")), ("saved_value", top(data_version=DATA_PREFIX + "0" * 64)),
            ("saved_value", top(attribution="")), ("saved_value", top(attribution="x" * 1025)), ("saved_value", top(rights="")),
            ("saved_value", top(calendar_source_version="bad version!")),
            ("saved_pin_or_scope", lambda r: r["source_policy"].update(version="issue98-other-v1")),
            ("saved_pin_or_scope", lambda r: r["source_policy"].update(sha256="0" * 64)),
            ("saved_pin_or_scope", lambda r: r["source_policy"].update(bytes=1)),
            ("saved_calendar_rows", top(calendar_rows=70)),
            ("saved_get", rehash(0, url="https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate")),
            ("saved_get", rehash(5, source_id="finmind_price/9999")), ("saved_get", rehash(5, source_version="x")),
            ("saved_get", rehash(5, method="POST")), ("saved_get", rehash(5, status=201)), ("saved_get", rehash(5, full_eof=False)),
            ("saved_get", rehash(5, content_encoding="gzip")), ("saved_get", rehash(5, content_type="text/html")),
            ("saved_get", rehash(5, namespace="x")), ("saved_get", rehash(5, policy_sha256="0" * 64)),
            ("saved_get", rehash(5, body_bytes=0)), ("saved_get", rehash(5, body_bytes=tca.BODY_CAP + 1)),
            ("saved_get", rehash(5, body_sha256="Z" * 64)),
            ("saved_get", lambda r: r["gets"].reverse()),
            ("saved_get", lambda r: [rehash(i, body_bytes=tca.BODY_CAP)(r) for i in range(20)]),
            ("saved_get_times", rehash(5, observed_utc="2000-01-01T00:00:00+00:00")),
            ("saved_get_times", top(saved_at="2000-01-01T00:00:00+00:00")),
            ("saved_time", rehash(5, request_started_utc="2026-10-12 00:00:00")), ("saved_time", top(saved_at="2026-10-12T00:00:00")),
            ("saved_time", rehash(5, observed_utc="2026-10-12T00:00:00+08:00")),
            ("saved_get_receipt_sha", get(5, receipt_sha256="0" * 64)),
            ("saved_adapter", lambda r: r["adapter"].update(ohlcv_history_source_sha256="x" * 64)),
            ("saved_data_reference", lambda r: r["data"].update(bytes=1)), ("saved_data_reference", lambda r: r["data"].update(file="other.json")),
            ("saved_data_reference", lambda r: r["data"].update(sha256="0" * 64)),
        ]
        for code, edit in cases:
            blob, receipt_blob = self.rebuilt(source, good, edit)
            with self.subTest(code=code, case=cases.index((code, edit))):
                self.assertFailure(code, tca._verify_bundle, blob, receipt_blob, pins)

    def test_missing_polluted_partial_and_oversize_bundles_are_refused_from_disk(self):
        root, source = saved_bundle(self)
        pins = source._pins
        final = os.path.join(root, POLICY_VERSION, END)
        good = {name: read_bytes(os.path.join(final, name)) for name in ("data.json", "receipt.json")}
        self.assertEqual(tca.load_saved(root, pins=pins).data_sha256, hashlib.sha256(good["data.json"]).hexdigest())
        self.assertFailure("pins_type", tca.load_saved, root, pins="pins")
        self.assertFailure("saved_pin_or_scope", tca.load_saved, root, pins=tca.Pins("0" * 64, pins.nbytes))
        self.assertFailure("root_invalid", tca.load_saved, "relative", pins=pins)
        self.assertFailure("saved_missing", tca.load_saved, os.path.join(root, "nope"), pins=pins)
        polluted = good["data.json"].replace(b'"3105"', b'"3106"', 1)
        write_bytes(os.path.join(final, "data.json"), polluted)
        with self.assertRaises(tca.SourceError) as caught:
            tca.load_saved(root, pins=pins)
        self.assertTrue(caught.exception.code.startswith("saved_"), caught.exception.code)
        write_bytes(os.path.join(final, "data.json"), good["data.json"] + b" ")
        self.assertFailure("saved_not_canonical", tca.load_saved, root, pins=pins)
        write_bytes(os.path.join(final, "data.json"), b"x" * (tca.DATA_CAP + 1))
        self.assertFailure("saved_size_cap", tca.load_saved, root, pins=pins)
        write_bytes(os.path.join(final, "data.json"), good["data.json"])
        extra = os.path.join(final, "extra.txt")
        write_bytes(extra, b"x")
        self.assertFailure("saved_entries", tca.load_saved, root, pins=pins)
        os.remove(extra)
        os.remove(os.path.join(final, "receipt.json"))
        self.assertFailure("saved_entries", tca.load_saved, root, pins=pins)
        os.mkdir(os.path.join(final, "receipt.json"))
        self.assertFailure("saved_not_file", tca.load_saved, root, pins=pins)
        os.rmdir(os.path.join(final, "receipt.json"))
        write_bytes(os.path.join(final, "receipt.json"), good["receipt.json"])
        os.rename(final, final + "x")
        self.assertFailure("saved_missing", tca.load_saved, root, pins=pins)
        os.rename(final + "x", final)
        self.assertEqual(tca.load_saved(root, pins=pins).data_version, DATA_PREFIX + hashlib.sha256(good["data.json"]).hexdigest())

    def test_a_real_symlink_root_is_refused(self):
        root, source = saved_bundle(self)
        link = os.path.join(self.new_dir(), "link")
        try:
            os.symlink(os.path.join(root, POLICY_VERSION, END), link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest("symlinks are not permitted here (%r); the patched-lstat test below covers the same guard" % (error,))
        try:
            self.assertFailure("saved_reparse_point", tca.load_saved, link, pins=source._pins)
        finally:
            os.rmdir(link) if os.name == "nt" else os.remove(link)

    def test_saved_files_that_are_links_are_refused(self):
        with patch.object(tca.os, "lstat", lambda path: types.SimpleNamespace(st_mode=0o120777, st_size=0, st_file_attributes=0)):
            self.assertFailure("saved_reparse_point", tca._lstat, "x", "kind", "dir")
        with patch.object(tca.os, "lstat", lambda path: types.SimpleNamespace(st_mode=0o040777, st_size=0, st_file_attributes=0x400)):
            self.assertFailure("saved_reparse_point", tca._lstat, "x", "kind", "dir")
        with patch.object(tca.os, "lstat", side_effect=PermissionError(13, "denied")):
            self.assertFailure("storage_io_failure", tca._lstat, "x", "kind", "dir")


# --- a new process re-reads and re-verifies --------------------------------------------------------------------

CHILD = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from app import tpex_calendar_actions_source as m
root, sha, nbytes = sys.argv[2], sys.argv[3], int(sys.argv[4])
try:
    saved = m.load_saved(root, pins=None if sha == "default" else m.Pins(sha, nbytes))
    kw = dict(market="TPEx", security_type="ordinary_share", data_version=saved.data_version, purpose=m.PURPOSE)
    day = saved.read_day(symbol="3105", on_date="2026-07-02", basis="adjusted", **kw)
    out = {"ok": True, "version": saved.data_version, "calendar": len(saved.calendar), "factor": str(day.factor),
           "unknown": saved.read_day(symbol="3105", on_date="2026-07-02", basis="raw", **kw).provenance["publication_time"]}
except m.SourceError as error:
    out = {"ok": False, "code": error.code}
print(json.dumps(out))
'''


class CrossProcess(Case):
    def child(self, root, pins):
        CHILD_ALLOWED[0] = True
        try:
            arguments = ("default", "0") if pins is None else (pins.sha256, str(pins.nbytes))
            done = subprocess.run([PYTHON, "-I", "-B", "-c", CHILD, str(ROOT / "backend"), root, *arguments],
                                  capture_output=True, timeout=120, cwd=SESSION)
        finally:
            CHILD_ALLOWED[0] = False
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        return json.loads(done.stdout)

    def test_a_new_process_rereads_and_rejects_pollution_without_writing_or_fetching(self):
        corpus = Corpus()
        root, source = saved_bundle(self)
        before = self.tree(root)
        result = self.child(root, source._pins)
        digest = hashlib.sha256(canonical(corpus.expected_data())).hexdigest()
        price = Fraction(str(corpus.prior["3105"]))
        self.assertEqual(result, {"ok": True, "version": DATA_PREFIX + digest, "calendar": 71,
                                  "factor": str((price - Fraction(str(corpus.cash["3105"]))) / price), "unknown": "unknown"})
        self.assertEqual(self.tree(root), before)
        write_bytes(os.path.join(root, POLICY_VERSION, END, "data.json"), canonical(corpus.expected_data()) + b" ")
        self.assertEqual(self.child(root, source._pins), {"ok": False, "code": "saved_not_canonical"})
        self.assertEqual(self.child(os.path.join(root, "nope"), source._pins), {"ok": False, "code": "saved_missing"})
        write_bytes(os.path.join(root, POLICY_VERSION, END, "data.json"), canonical(corpus.expected_data()))
        self.assertEqual(self.child(root, tca.Pins("0" * 64, source._pins.nbytes)), {"ok": False, "code": "saved_pin_or_scope"})
        self.assertEqual(self.child(root, source._pins)["ok"], True)
        self.assertEqual(self.child(root, None)["ok"], True)  # the module's own published pins
        self.assertEqual(len(BLOCKED), EXPECTED_BLOCKED[0])


# --- what this module takes from issue 32, and what it must never do ---------------------------------------------

_RECEIPT_FIELDS_LITERAL = ("source_id", "source_version", "method", "url", "status", "request_started_utc", "observed_utc",
                           "body_bytes", "body_sha256", "full_eof", "content_type", "content_encoding", "namespace", "policy_sha256")
ISSUE32_PRODUCT_SHA256 = "528875c3b14f5ce7a7f140e7385f32a209d45118219b8e1e63de7848cf3f9a7b"


class HelperLocks(Case):
    """Everything this module takes from issue 32's private surface, with its signature and key behaviour pinned."""

    def test_reference_manifest_equals_the_names_actually_referenced(self):
        tree = ast.parse(TCA_FILE.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "_base" and not node.attr.startswith("__")}
        self.assertEqual(used, set(tca.IMPORTED_HELPERS))
        self.assertEqual(len(tca.IMPORTED_HELPERS), len(set(tca.IMPORTED_HELPERS)))
        sources = [(node.module, tuple(alias.name for alias in node.names), node.level)
                   for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertIn((None, ("ohlcv_history_source",), 1), sources)
        self.assertEqual([m for m, _, _ in sources if m and "ohlcv" in m], [])

    def test_issue32_product_file_is_unchanged_since_the_qa2_candidate(self):
        # SOURCE_REGISTRY 49.1: the qa2 candidate 8c7b5ab product file. A later edit to that file must be noticed here.
        self.assertEqual(hashlib.sha256(BASE_FILE.read_bytes()).hexdigest(), ISSUE32_PRODUCT_SHA256)

    def test_signatures_fields_and_constants(self):
        import inspect
        signature = lambda function: str(inspect.signature(function))  # noqa: E731
        expected = {
            "_number": "(value, *, positive=True)", "_integer": "(value, *, positive=True)", "_formal_reference": "(formal_blob)",
            "_iso_date": "(value, code='price_date')", "_json": "(text, *, price=False)", "_canonical": "(value)",
            "_shape": "(value, schema)", "_freeze": "(value)",
            "_failure_values": "(exception, stage, fallback='transport_or_parse_failure')",
            "_close_all": "(operations, primary_failure=None)", "_raise_failure": "(values)", "_fail": "(code, **diagnostics)",
            "retained_roots_estimate": "(*roots)"}
        for name, text in expected.items():
            with self.subTest(helper=name):
                self.assertEqual(signature(getattr(base, name)), text)
        self.assertEqual(signature(base.AttemptLedger.__init__), "(self, namespace)")
        self.assertEqual(signature(base.AttemptLedger.begin), "(self)")
        self.assertEqual(signature(base.AttemptLedger.charge), "(self, index)")
        self.assertEqual(signature(base._HTTPSTransport.open), "(self, url, timeout)")
        names = lambda cls: [field.name for field in dataclasses.fields(cls)]  # noqa: E731
        self.assertEqual(names(base.Receipt), list(_RECEIPT_FIELDS_LITERAL))
        self.assertEqual(names(base.Capture), ["body", "receipt"])
        self.assertEqual(names(base.FinancialStart), ["version", "issuer_thread_id", "coordinator_session_ids",
                                                      "implementer_session_ids", "namespace", "policy_sha256", "seal_comment_url",
                                                      "binding", "authorized", "whole_batch"])
        self.assertEqual(names(base.ExecutionBinding), ["holder_thread_id", "holder_session_id", "parent_thread_id", "model",
                                                        "reasoning_effort", "candidate_sha", "loaded_source_sha256", "script_sha256",
                                                        "native_command"])
        self.assertEqual(tca._RECEIPT_FIELDS, _RECEIPT_FIELDS_LITERAL)
        for cls in (base.Receipt, base.Capture, base.FinancialStart, base.ExecutionBinding):
            self.assertTrue(cls.__dataclass_params__.frozen)
        constants = {"BODY_CAP": 1048576, "ROOTS_CAP": 33554432, "REQUEST_SECONDS": 20,
                     "USER_AGENT": "stock-lab-issue32-local-ram/1", "ACCEPT": "application/json",
                     "SESSION_ID_PATTERN": r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                     "MODEL_PATTERN": r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", "FORMAL_BLOB": FORMAL_OBJECT, "FORMAL_SHA256": FORMAL_SHA,
                     "SYMBOLS": SYMBOLS}
        for name, value in constants.items():
            with self.subTest(constant=name):
                self.assertEqual(getattr(base, name), value)
        self.assertIs(tca.SourceError, base.SourceError)
        self.assertTrue(issubclass(tca.AttemptLedger, base.AttemptLedger))
        self.assertEqual(base.AttemptLedger.__init__.__code__.co_varnames[:2], ("self", "namespace"))

    def test_number_integer_json_and_formal_helpers_behave_as_this_module_relies_on(self):
        self.assertEqual(base._number(Decimal("-1.5"), positive=False), Fraction(-3, 2))
        self.assertEqual(base._number(0, positive=False), Fraction(0))
        for bad in (True, "1", None, 1.5, Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(bad=bad):
                self.assertFailure("price_number_type", base._number, bad, positive=False)
        self.assertFailure("numeric_representation_cap", base._number, Decimal("1e%d" % (base.BODY_CAP + 5)), positive=False)
        self.assertEqual(base._integer(0, positive=False), 0)
        for bad in (True, 1.0, Decimal(1), "1", -1, 2 ** 63):
            with self.subTest(bad=bad):
                self.assertFailure("canonical_int64", base._integer, bad, positive=False)
        self.assertEqual(base._integer(2 ** 63 - 1, positive=False), 2 ** 63 - 1)
        self.assertFailure("duplicate_json_key", base._json, '{"a":1,"a":2}')
        self.assertFailure("nonfinite_json_number", base._json, '{"a":NaN}')
        self.assertEqual(base._json('{"a":1.50}', price=True)["a"], Decimal("1.50"))
        self.assertEqual(base._canonical({"b": [1, "鈴"], "a": None}), '{"a":null,"b":[1,"鈴"]}'.encode("utf-8"))
        self.assertFailure("policy_keys", base._shape, {"a": 1}, {"b": int})
        self.assertFailure("policy_list", base._shape, ["x"], (str, 2))
        self.assertFailure("policy_type", base._shape, True, int)
        frozen = base._freeze({"a": [1, {"b": [2]}]})
        self.assertIsInstance(frozen, types.MappingProxyType)
        self.assertEqual(frozen["a"][1]["b"], (2,))
        self.assertEqual(base._iso_date("2026-10-06"), "2026-10-06")
        for bad in ("2026-10-6", "20261006", "2026-02-30", "2026-10-06 ", 20261006, None, b"2026-10-06", "٢026-10-06"):
            self.assertFailure("custom_code", base._iso_date, bad, "custom_code")
        prior, anchors = base._formal_reference(FORMAL)
        self.assertEqual((len(prior), prior[0], prior[-1]), (45, "2026-08-03", IDENTITY))
        self.assertEqual(prior, PRIOR)
        self.assertEqual(tuple(anchors), SYMBOLS)
        for symbol, values in ANCHORS.items():
            self.assertEqual(anchors[symbol], tuple(Fraction(str(value)) for value in values[:4]) + values[4:])
        self.assertFailure("formal_blob_pin", base._formal_reference, FORMAL + b" ")

    def test_failure_cleanup_and_roots_helpers(self):
        values = base._failure_values(OSError("SECRET RAW BODY" * 100), "capture_open", "fallback_code")
        self.assertEqual((values["code"], values["primary_code"], values["primary_stage"]), ("fallback_code", "fallback_code", "capture_open"))
        self.assertNotIn("SECRET", repr(values))
        calls = []

        def closer(name, fail):
            def close():
                calls.append(name)
                if fail:
                    raise OSError("x")
            return close
        failure = base._close_all([("a", closer("a", True)), ("b", closer("b", False)), ("c", closer("c", True)),
                                   ("d", closer("d", True)), ("e", closer("e", True))])
        self.assertEqual(calls, ["a", "b", "c", "d", "e"])
        self.assertEqual((failure["primary_stage"], failure["secondary_cleanup_count"], failure["secondary_cleanup_omitted"]), ("a", 2, 1))
        self.assertIsNone(base._close_all([("ok", closer("ok", False))]))
        with self.assertRaises(base.SourceError) as caught:
            base._raise_failure({"code": "boom", "primary_code": "boom", "extra": 1})
        self.assertEqual((caught.exception.code, caught.exception.diagnostics["extra"]), ("boom", 1))
        shared = [1, 2, 3]
        self.assertEqual(base.retained_roots_estimate(shared), base.retained_roots_estimate(shared, shared))
        self.assertGreater(base.retained_roots_estimate(Fraction(10 ** 40, 3)), base.retained_roots_estimate(Fraction(1, 3)))
        receipt = base.Receipt("a", "b", "GET", "https://x", 200, "s", "o", 1, "h" * 64, True, "t", "identity", "n", "p")
        self.assertEqual(receipt.canonical_sha256, hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest())

    def test_default_transport_url_rules_and_fixed_request_headers(self):
        transport = base._HTTPSTransport()
        for url in ("http://api.finmindtrade.com/api/v4/data?x=1", "https://example.invalid/api/v4/data?x=1",
                    "https://api.finmindtrade.com:444/api/v4/data?x=1", "https://user@api.finmindtrade.com/api/v4/data?x=1",
                    "https://api.finmindtrade.com.evil.invalid/api/v4/data?x=1", "ftp://api.finmindtrade.com/x"):
            with self.subTest(url=url):
                self.assertFailure("transport_url", transport.open, url, 5)
        replay = ReplayTransport([finmind_wire(Corpus().bodies[43])])
        response = replay.open(step_url("info"), 5)
        try:
            self.assertEqual((replay.requests[0][1], replay.requests[0][2]), ("GET", "/api/v4/data?dataset=TaiwanStockInfo"))
            self.assertEqual(response.status, 200)
        finally:
            response.close()


class RunnerGuards(Case):
    def test_module_has_no_environment_network_or_foreign_write_surface(self):
        source = TCA_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for banned in ("os.environ", "getenv", "urlopen", "requests.", "import socket", "import subprocess", "import shutil",
                       "import tempfile", "import http", "import ssl", "import urllib"):
            self.assertNotIn(banned, source, banned)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertEqual(imported, {"hashlib", "math", "os", "re", "secrets", "stat", "threading", "time"})

    def test_import_time_calls_are_pure_and_the_hook_blocks_network_foreign_writes_and_processes(self):
        tree = ast.parse(TCA_FILE.read_text(encoding="utf-8"))
        called = set()

        def walk(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for decorator in getattr(node, "decorator_list", []):
                    walk(decorator)
                return
            if isinstance(node, ast.Call):
                function = node.func
                called.add(function.attr if isinstance(function, ast.Attribute) else function.id)
            for child in ast.iter_child_nodes(node):
                walk(child)
        for node in tree.body:
            walk(node)
        self.assertEqual(called, {"dataclass", "getattr", "tuple", "compile", "Lock", "fields", "len", "_build_steps", "RuntimeError",
                                  "_source_shape", "Fraction"})
        before = len(BLOCKED)
        outside = os.path.join(os.path.dirname(SESSION), "must-not-exist-" + os.path.basename(SESSION))
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("localhost", 80)
        with self.assertRaises(AssertionError):
            open(outside, "w")
        with self.assertRaises(AssertionError):
            os.mkdir(outside)
        with self.assertRaises(AssertionError):
            subprocess.run([PYTHON, "-c", "pass"], capture_output=True)
        with self.assertRaises(AssertionError):
            subprocess.run(["cmd", "/c", "echo", "x"], capture_output=True)
        self.assertFalse(os.path.exists(outside))
        self.assertEqual(len(BLOCKED) - before, 6)
        EXPECTED_BLOCKED[0] += 6


def tearDownModule():
    leftovers = os.listdir(SESSION)
    if leftovers:
        raise AssertionError("session directory not empty: %r" % leftovers)
    os.rmdir(SESSION)
    sys.stdout.write("RESIDUE session_dir_exists=%s hook_blocked=%d expected_probe_blocks=%d\n"
                     % (os.path.exists(SESSION), len(BLOCKED), EXPECTED_BLOCKED[0]))
    if len(BLOCKED) != EXPECTED_BLOCKED[0]:
        raise AssertionError("the hook blocked an unexpected operation: %r" % BLOCKED)


if __name__ == "__main__":
    unittest.main(verbosity=1)
