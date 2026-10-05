"""Dataset 11370: one explicit bounded CSV capture; no import I/O or persistence."""
from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from http.client import HTTPException
import io
import json
import math
import re
import socket
import ssl
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

VERSION = "tpex-price-capture/m1-v1"
POLICY_VERSION = "m1-price-tpex-11370-2026-10-05.1"
SOURCE_ID = "tpex_11370_daily_close_csv"
ENDPOINT = "https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data"
CUTOFF = date(2026, 10, 5)
MAX_BODY_BYTES = 3 * 1024 * 1024
DEADLINE_SECONDS = 30
MAX_INT64 = "9223372036854775807"
MAX_SAFE_INTEGER = "9007199254740991"
SYMBOLS = {"3105": "穩懋", "6488": "環球晶"}
HEADER = ("資料日期", "代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價",
          "成交股數", "成交金額", "成交筆數", "最後買價", "最後賣價", "發行股數", "次日參考價", "次日漲停價", "次日跌停價")
_POLICY = {
  "version": "m1-price-tpex-11370-2026-10-05.1",
  "profile": "free_public_local",
  "source_id": "tpex_11370_daily_close_csv",
  "metadata_url": "https://data.gov.tw/dataset/11370",
  "resource_url": "https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data",
  "method": "GET",
  "purposes": [
    "local_fetch",
    "raw_store",
    "summarize"
  ],
  "storage": "process_memory",
  "scope": {
    "exchange": "TPEx",
    "asset_type": "stock",
    "currency": "TWD",
    "cutoff": "2026-10-05",
    "symbols": {
      "3105": "穩懋",
      "6488": "環球晶"
    }
  },
  "bounds": {
    "max_requests": 1,
    "max_body_bytes": 3145728,
    "deadline_seconds": 30,
    "redirects": False,
    "retries": 0,
    "accept_encoding": "identity"
  },
  "validation": {
    "structural": "all_rows_header_width_date_unique_date_code",
    "financial": "selected_symbols_only",
    "expected_body_sha256": "bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149",
    "quantity_encoding": "canonical_nonnegative_int64_string",
    "price_encoding": "positive_decimal_ohlc_bounds"
  },
  "attribution": {
    "owners": [
      "金融監督管理委員會證券期貨局",
      "財團法人中華民國證券櫃檯買賣中心"
    ],
    "dataset_name": "上櫃股票行情",
    "year": 2026,
    "release_version": "data-date-2026-10-05",
    "license": "OGL-1.0",
    "license_url": "https://data.gov.tw/license",
    "publication_time": "unknown",
    "first_available_time": "unknown",
    "revision_time": "unknown"
  },
  "limitations": [
    "single_day_only",
    "historical_pit_unsupported",
    "no_history_calendar_ma20_signal_or_plan",
    "capture_time_is_not_publication_time"
  ]
}
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)", re.ASCII)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", re.ASCII)
_CODE = re.compile(r"[0-9A-Z]{4,12}", re.ASCII)


class PriceCaptureError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def price_policy() -> dict:
    return deepcopy(_POLICY)


def validate_policy(policy: dict, expected_version: str, expected_digest: str) -> None:
    # The caller supplies independently accepted pins; computing a hash is not admission.
    if policy != _POLICY or expected_version != POLICY_VERSION or digest(policy) != expected_digest:
        raise PriceCaptureError("price_policy_pins_mismatch")


def integer_text(value: Any) -> str:
    if not isinstance(value, str) or not _INTEGER.fullmatch(value):
        raise PriceCaptureError("price_integer_invalid")
    if (len(value), value) > (len(MAX_INT64), MAX_INT64):
        raise PriceCaptureError("price_integer_overflow")
    return value


def positive_decimal(value: str) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value) or len(value) > 64:
        raise PriceCaptureError("price_decimal_invalid")
    result = Decimal(value)
    if not result.is_finite() or result <= 0 or not math.isfinite(float(result)):
        raise PriceCaptureError("price_decimal_invalid")
    return result


def parse_price_csv(body: bytes, *, cutoff: date = CUTOFF) -> dict:
    if type(body) is not bytes or not body or len(body) > MAX_BODY_BYTES:
        raise PriceCaptureError("price_body_size_invalid")
    if type(cutoff) is not date or cutoff != CUTOFF:
        raise PriceCaptureError("price_cutoff_not_supported")
    try:
        rows = csv.reader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True)
        if tuple(next(rows)) != HEADER:
            raise PriceCaptureError("price_csv_header_mismatch")
        seen = set()
        selected = {}
        count = 0
        for ordinal, row in enumerate(rows, 1):
            count += 1
            if len(row) != len(HEADER):
                raise PriceCaptureError("price_csv_width_invalid")
            if row[0] != "1151005":
                raise PriceCaptureError("price_feed_date_mismatch")
            if not _CODE.fullmatch(row[1]) or not row[2]:
                raise PriceCaptureError("price_csv_identity_invalid")
            key = (row[0], row[1])
            if key in seen:
                raise PriceCaptureError("price_csv_duplicate")
            seen.add(key)
            if row[1] not in SYMBOLS:
                continue  # All-row structural verification is not all-market financial verification.
            if row[2] != SYMBOLS[row[1]]:
                raise PriceCaptureError("price_selected_name_mismatch")
            prices = {field: positive_decimal(row[index]) for field, index in
                      (("open", 5), ("high", 6), ("low", 7), ("close", 3))}
            if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
                raise PriceCaptureError("price_ohlc_bounds_invalid")
            volume = integer_text(row[9])
            amount = None if row[10] == "" else integer_text(row[10])
            selected[row[1]] = {
                "symbol": row[1], "company_name": row[2], "date": cutoff.isoformat(),
                **{field: float(value) for field, value in prices.items()},
                "volume_exact": volume,
                "volume": int(volume) if (len(volume), volume) <= (len(MAX_SAFE_INTEGER), MAX_SAFE_INTEGER) else None,
                "turnover_exact": amount,
                "turnover": int(amount) if amount is not None and (len(amount), amount) <= (len(MAX_SAFE_INTEGER), MAX_SAFE_INTEGER) else None,
                "turnover_status": "unavailable" if amount is None else "available",
                "turnover_reason": "missing" if amount is None else None,
                "row_ordinal": ordinal, "source_date": row[0], "source_fields": dict(zip(HEADER, row)),
            }
        if not count or set(selected) != set(SYMBOLS):
            raise PriceCaptureError("price_selected_rows_missing")
        return {"row_count": count, "structural_validation": "all_rows_header_width_date_unique_date_code",
                "financial_validation": "selected_symbols_only", "date": cutoff.isoformat(), "selected": selected}
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise PriceCaptureError("price_csv_invalid") from error


@dataclass(frozen=True)
class PriceCapture:
    body: bytes
    receipt_bytes: bytes
    parsed: dict

    @property
    def receipt(self) -> dict:
        return json.loads(self.receipt_bytes.decode("utf-8"))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise PriceCaptureError("price_redirect_rejected")


def _remaining(start: float, clock) -> float:
    remaining = DEADLINE_SECONDS - (clock() - start)
    if remaining <= 0:
        raise PriceCaptureError("price_total_deadline_exceeded")
    return remaining


def _set_response_timeout(response, seconds: float) -> None:
    # urllib's HTTPS response retains the TLS socket through its buffered reader.
    # Fail closed rather than allow a fresh 30-second timeout for every chunk.
    try:
        response.fp.raw._sock.settimeout(seconds)
    except (AttributeError, OSError) as error:
        raise PriceCaptureError("price_deadline_socket_unavailable") from error


def capture_price(*, policy: dict, expected_policy_version: str, expected_policy_digest: str,
                  opener=None, clock=time.monotonic, now=None, set_timeout=_set_response_timeout,
                  on_request=None) -> PriceCapture:
    validate_policy(policy, expected_policy_version, expected_policy_digest)
    started = clock()
    now = now or (lambda: datetime.now(timezone.utc))
    request_started_at = now().astimezone(timezone.utc).isoformat()
    opener = opener or build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(ENDPOINT, method="GET", headers={"Accept-Encoding": "identity", "User-Agent": "taiwan-stock-research/M1-PRICE-1"})
    try:
        if on_request:
            on_request()
        with opener.open(request, timeout=_remaining(started, clock)) as response:
            if response.geturl() != ENDPOINT or response.status != 200:
                raise PriceCaptureError("price_response_rejected")
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise PriceCaptureError("price_content_encoding_rejected")
            media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media not in {"application/csv", "text/csv", "application/octet-stream"}:
                raise PriceCaptureError("price_content_type_rejected")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not _INTEGER.fullmatch(declared) or int(declared) > MAX_BODY_BYTES):
                raise PriceCaptureError("price_body_size_invalid")
            chunks = []
            size = 0
            while True:
                _remaining(started, clock)
                # HTTPResponse.read1 closes fp as soon as Content-Length is
                # exhausted. That is normal completion, not an unavailable TLS socket.
                if getattr(response, "fp", True) is None or getattr(response, "length", None) == 0:
                    break
                set_timeout(response, _remaining(started, clock))
                chunk = response.read1(min(65536, MAX_BODY_BYTES - size + 1))
                _remaining(started, clock)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise PriceCaptureError("price_body_size_invalid")
                chunks.append(chunk)
            if declared is not None and size != int(declared):
                raise PriceCaptureError("price_body_truncated")
            body = b"".join(chunks)
            captured_at = now().astimezone(timezone.utc).isoformat()
    except PriceCaptureError:
        raise
    except (HTTPError, HTTPException, OSError, socket.timeout) as error:
        raise PriceCaptureError("price_capture_http_failed") from error
    body_sha = hashlib.sha256(body).hexdigest()
    if body_sha != policy["validation"]["expected_body_sha256"]:
        raise PriceCaptureError("price_body_version_mismatch")
    parsed = parse_price_csv(body)
    receipt = {
        "worker_version": VERSION, "source_id": SOURCE_ID, "source_version": "tpex-11370/2026-10-05",
        "endpoint": ENDPOINT, "method": "GET", "http_status": 200, "request_count": 1,
        "request_started_at": request_started_at, "captured_at": captured_at,
        "body_sha256": body_sha, "body_bytes": len(body), "policy_version": expected_policy_version,
        "policy_digest": expected_policy_digest, "profile": policy["profile"],
        "storage": "process_memory", "historical_pit": "unsupported",
        "structural_validation": parsed["structural_validation"], "financial_validation": parsed["financial_validation"],
        "row_count": parsed["row_count"], "selected_symbols": list(SYMBOLS),
        "attribution": deepcopy(policy["attribution"]), "limitations": list(policy["limitations"]),
    }
    return PriceCapture(body, canonical_bytes(receipt), parsed)
