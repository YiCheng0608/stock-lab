"""Independent, finite chips-only daily gross trade. No I/O occurs on import/read."""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import sys
import threading
import time
import uuid

from .tpex_institutional_window import _rows, _market_date, _decimal, WindowEvidenceError

POLICY_CANONICAL = r'''{"calculation_version":"gross-buy-sell-net-running-sum/window-reset-int64-v1","calendar":{"adopted_dates":["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"closed_dates":["2026-09-25","2026-09-28"],"closed_notice":"https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html","completeness":"ALL_adopted_dates_equal_weekdays_2026-09-01_through_cutoff_minus_explicit_closed_dates; last20_last5_only_after_full_validation","from":"2026-09-01","meaning":"observed_index_calendar_only_not_stock_closes","observation_date":"2026-10-08","original_rows":"validate_ALL_returned_month_rows_before_selection; unique_requested_month_valid_weekday_nonclosed_positive_finite_OHLC; no_future_after_observation_date; no_assumed_row_count","post_cutoff":"validate_and_retain_all_original_rows_but_exclude_after_cutoff","to":"2026-10-06","weekday_rule":"https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html"},"capture_schema":"tpex-institutional-gross-capture/chips-stock-scope-7-v1","entry":{"actions":"explicit_trusted_FIRST_once_then_explicit_READ_held; stock_investor_horizon_apply_back_no_automatic_fetch","api":"/api/chips/gross-stock-scope-7","capture_api":"/api/chips/gross-stock-scope-7/capture","capture_keys":["as_of"],"failure":"same_generation_failure_masks_all_gross_net_values_charts_tables_raw_calendar; controls_back_cannot_unmask_without_successful_explicit_READ","frontend_flag":"VITE_CHIPS_GROSS_STOCK_SCOPE_7=m1-v1","get_body_bytes":0,"get_keys":["as_of"],"navigation":"detail_stock_and_back_preserve_all_raw_controls_same_cutoff","old_profiles":"immutable_default_off_no_private_price_oldproducer_capture_clone_replay_hydration_preload","parameters":"exact_keys_once_no_unknown_duplicates; ISO_date; unsupported_valid_cutoff_unavailable_before_state_or_IO","post_body":"empty_JSON_object","post_body_max":4096,"raw_controls":["as_of","investor","horizon"],"route":"/chips-stock-scope-7-gross-trade","runner_flag":"--chips-gross-stock-scope-7-opt-in"},"execution":{"batch_deadline_seconds":180,"deadline":"cooperative_checks_at_request_response_chunk_boundaries_not_OS_preemption","diagnostic_max_response_bytes":16777216,"disk_artifacts":0,"estimate":"deduplicated_getsizeof_estimate_not_RSS_or_construction_peak","freshness":"ONE_new_empty_distinct_producer_ZERO_seed_preload_FIRST_once_failure_SPENT; no_old_producer_capture_receipt_reuse; dynamic_full_returned_calendar_validation; source_schema_date_contract_conflict_stop_without_retry","header_cap":"received_header_postcheck_not_socket_cap","max_requests":22,"max_response_header_bytes":16384,"max_retained_graph_estimate_bytes":67108864,"max_total_bytes":44040192,"metadata_get":0,"ordinary_price_get":0,"private_actual_io":0,"redirects":0,"request_timeout_seconds":15,"retries":0,"storage":"process_memory","transport":"request_local_DNS_and_exact_TPEx_IP443_only_finally_clear; no_cross_thread_authority","upstream_post":0},"profile":"free_public_local_chips_only_daily_gross_trade_stock_scope_7","read_schema":"institutional-daily-gross-read/chips-stock-scope-7-v1","rights":{"access_basis":"2026-10-08_ROOT_exact_dataset11391_11856_free_CSV_UTF8_license1_owner_and_distribution_verified; TPEx_terms_section7_government_open_data_exception; finite_local_use_only","attribution":"Taipei Exchange (TPEx); 2026; dataset11391 Index historical data and dataset11856 Information on the trading details of OTC stocks three major institutional investors; observed source versions; Government Data Open License v1.0 https://data.gov.tw/license; original rows and provenance preserved","first_available_time":"unknown","historical_pit":"unsupported","license":"Government Data Open License v1.0","license_url":"https://data.gov.tw/license","owner":"Taipei Exchange (TPEx)","published_time":"unknown","revision_time":"unknown","statistical_basis":"original_trade_executions_before_broker_account_corrections","uses":["local_fetch","raw_store_process_memory_only","summarize_gross_buy_sell_net_with_complete_attribution"]},"scope":{"currency":"TWD","cutoff":"2026-10-06","daily_dates":["2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"exchange":"TPEx","foreign_definition":"excluding_foreign_dealer","horizons":[5,20],"identities":{"3105":"穩懋","3293":"鈊象","5274":"信驊","5347":"世界","6488":"環球晶","6510":"精測","8069":"元太"},"identity_date":"2026-10-06","investors":["foreign","trust","dealer"],"market":"TW","pit_membership":false,"security_type":"stock","symbols":["3105","3293","5274","5347","6488","6510","8069"]},"series":{"completeness":"ALL7_ALL2windows_ALL3investors_before_any_available_series_or_zero","components":{"dealer":[21,22,23],"foreign":[3,4,5],"trust":[12,13,14]},"cumulative":"reset_buy_sell_net_to_zero_before_each_window_first_day; three_exact_ordered_prefix_sums","encoding":"canonical_integer_strings","gross":"buy_and_sell_nonnegative_signed_int64; foreign_excludes_foreign_dealer; dealer_total_self_and_hedge","lots_denominator":1000,"lots_max_decimals":3,"net":"signed_int64_buy_minus_sell","overflow":"any_ALL7_daily_gross_net_aggregate_or_prefix_outside_signed_int64_makes_entire_profile_unavailable","reconciliation":"ALL84_gross_window_totals_and_ALL42_net_totals_independent; final_prefix_totals_equal_sums; buy_total_minus_sell_total_equals_net_total; every_daily_and_prefix_relation","signed_max":"9223372036854775807","signed_min":"-9223372036854775808","trace":"each_dated_point_and_row_preserves_ALL25_original_strings_row_ordinal_original_receipt_SHA256_body_SHA256_calendar","unit":"shares","window":"last_exact_5_or_20_adopted_sessions_inclusive_cutoff"},"sources":{"body":"empty","charset":"utf-8","content_encoding":"identity","content_types":["application/csv","text/csv"],"daily":{"base_url":"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data","dataset":"https://data.gov.tw/dataset/11856","header":["資料日期","代號","名稱","外資及陸資不含外資自營商買進股數","外資及陸資不含外資自營商賣出股數","外資及陸資不含外資自營商買賣超股數","外資自營商買進股數","外資自營商賣出股數","外資自營商買賣超股數","外資及陸資買進股數","外資及陸資賣出股數","外資及陸資買賣超股數","投信買進股數","投信賣出股數","投信買賣超股數","自營商自行買賣買進股數","自營商自行買賣賣出股數","自營商自行買賣買賣超股數","自營商避險買進股數","自營商避險賣出股數","自營商避險買賣超股數","自營商買進股數","自營商賣出股數","自營商買賣超股數","三大法人買賣超股數合計"],"max_body_bytes":2097152,"source_version":"dataset-11856-dated-csv-observed-2026-10-08/chips-gross-trade-stock-scope-7-v1"},"exact_urls":["https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F09%2F01","https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F10%2F01","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F07","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F08","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F09","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F10","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F11","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F14","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F15","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F16","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F17","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F18","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F21","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F22","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F23","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F24","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F29","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F30","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F01","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F02","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F05","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F06"],"http_status":200,"index":{"base_url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data","dataset":"https://data.gov.tw/dataset/11391","header":["資料日期","開市","最高價","最低價","收市","漲跌"],"max_body_bytes":1048576,"requests":["2026-09-01","2026-10-01"],"source_version":"dataset-11391-month-csv-observed-2026-10-08/chips-gross-trade-stock-scope-7-v1"},"method":"GET","validation":"ALL_returned_index_rows_ALL6_original_fields_no_assumed_count; ALL_daily_structure_dates_unique_codes_names; ALL7x20x25_original_strings_ALL22_int64_fields_ALL7_group_and_component_relations; ORIGINAL_body_and_canonical_receipt_dual_SHA_UTC_monotonic"},"version":"m1-chips-gross-trade-stock-scope-7-tpex-2026-10-06.1","worker_schema":"tpex-institutional-gross/chips-stock-scope-7-v1"}'''
POLICY_SHA256 = "ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144"
POLICY_DIGEST = "sha256:" + POLICY_SHA256
_POLICY = json.loads(POLICY_CANONICAL)
POLICY_VERSION = _POLICY["version"]
PROFILE = _POLICY["profile"]
SCHEMA = _POLICY["read_schema"]
CAPTURE_SCHEMA = _POLICY["capture_schema"]
CALCULATION = _POLICY["calculation_version"]
CUTOFF = _POLICY["scope"]["cutoff"]
DATES = tuple(_POLICY["scope"]["daily_dates"])
ADOPTED_DATES = tuple(_POLICY["calendar"]["adopted_dates"])
SYMBOLS = tuple(_POLICY["scope"]["symbols"])
NAMES = _POLICY["scope"]["identities"]
INVESTORS = tuple(_POLICY["scope"]["investors"])
HEADER = tuple(_POLICY["sources"]["daily"]["header"])
INDEX_HEADER = tuple(_POLICY["sources"]["index"]["header"])
URLS = tuple(_POLICY["sources"]["exact_urls"])
MIN_I64, MAX_I64 = -(2**63), 2**63 - 1


class GrossError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise GrossError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def policy():
    return json.loads(POLICY_CANONICAL)


def check_policy(value, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
    require(len(POLICY_CANONICAL.encode("utf-8")) == 10654 and digest(POLICY_CANONICAL.encode("utf-8")) == POLICY_SHA256, "literal_policy_corrupt")
    require(version == POLICY_VERSION and pin == POLICY_DIGEST and profile == PROFILE, "policy_pin_mismatch")
    require(canonical(value) == POLICY_CANONICAL.encode("utf-8"), "canonical_policy_mismatch")


def integer(value, gross=False):
    require(type(value) is str and len(value) <= 20 and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "integer_not_canonical")
    n = int(value)
    require(MIN_I64 <= n <= MAX_I64, "daily_int64_overflow")
    require(not gross or n >= 0, "negative_gross")
    return n


def bounded(n, reason):
    require(MIN_I64 <= n <= MAX_I64, reason)
    return n


def lots(value):
    n = int(value)
    whole, rest = divmod(abs(n), 1000)
    return ("-" if n < 0 else "") + str(whole) + (("." + str(rest).zfill(3).rstrip("0")) if rest else "")


def graph_estimate(value):
    """Deduplicated getsizeof estimate, not RSS or construction peak."""
    seen = set()
    def walk(v):
        if id(v) in seen:
            return 0
        seen.add(id(v))
        size = sys.getsizeof(v)
        if isinstance(v, dict):
            size += sum(walk(k) + walk(x) for k, x in v.items())
        elif isinstance(v, (list, tuple, set)):
            size += sum(walk(x) for x in v)
        elif isinstance(v, Captured):
            size += walk(vars(v))
        return size
    return walk(value)


@dataclass(frozen=True)
class Captured:
    ordinal: int
    url: str
    body: bytes
    request_started_at: datetime
    captured_at: datetime
    http_status: int = 200
    content_type: str = "application/csv;charset=utf-8"
    content_encoding: str = "identity"
    policy_version: str = POLICY_VERSION
    policy_digest: str = POLICY_DIGEST
    profile: str = PROFILE
    original_receipt_bytes: bytes = field(init=False, repr=False)
    original_receipt_sha256: str = field(init=False)

    def __post_init__(self):
        raw = canonical(self.receipt())
        object.__setattr__(self, "original_receipt_bytes", raw)
        object.__setattr__(self, "original_receipt_sha256", digest(raw))

    def receipt(self):
        source = "index" if self.ordinal < 2 else "daily"
        requested = _POLICY["sources"]["index"]["requests"][self.ordinal] if self.ordinal < 2 else DATES[self.ordinal - 2]
        return {"schema": CAPTURE_SCHEMA, "ordinal": self.ordinal, "source": source,
                "source_version": _POLICY["sources"][source]["source_version"], "requested_date": requested,
                "url": self.url, "method": "GET", "request_body_bytes": 0, "http_status": self.http_status,
                "content_type": self.content_type, "content_encoding": self.content_encoding,
                "body_bytes": len(self.body), "body_sha256": digest(self.body),
                "request_started_at": self.request_started_at.isoformat(), "captured_at": self.captured_at.isoformat(),
                "policy_version": self.policy_version, "policy_digest": self.policy_digest, "profile": self.profile,
                "publication_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
                "historical_pit": "unsupported", "request_count": 1}


def checked_capture(capture, ordinal, previous=None):
    require(type(capture) is Captured and type(capture.ordinal) is int and capture.ordinal == ordinal and type(capture.body) is bytes, "capture_type_or_order_invalid")
    require(capture.url == URLS[ordinal], "capture_url_mismatch")
    require((capture.policy_version, capture.policy_digest, capture.profile) == (POLICY_VERSION, POLICY_DIGEST, PROFILE), "capture_profile_mismatch")
    require(capture.http_status == 200 and capture.content_encoding.lower() == "identity", "capture_status_or_encoding")
    media = capture.content_type.lower().replace(" ", "")
    require(media.split(";")[0] in ("text/csv", "application/csv") and ("charset=" not in media or "charset=utf-8" in media), "capture_content_type")
    cap = _POLICY["sources"]["index" if ordinal < 2 else "daily"]["max_body_bytes"]
    require(0 < len(capture.body) <= cap, "capture_body_limit")
    for instant in (capture.request_started_at, capture.captured_at):
        require(type(instant) is datetime and instant.tzinfo is timezone.utc, "capture_utc_invalid")
        require(instant.date().isoformat() == "2026-10-08", "capture_observation_date_changed")
    require(capture.request_started_at <= capture.captured_at and (previous is None or previous <= capture.request_started_at), "capture_time_order")
    require(capture.original_receipt_bytes == canonical(capture.receipt()) and capture.original_receipt_sha256 == digest(capture.original_receipt_bytes), "original_receipt_tampered")
    return capture.receipt()


def trace(capture, ordinal, row, day):
    return {"date": day, "row_ordinal": ordinal, "source_values": row,
            "receipt_sha256": capture.original_receipt_sha256, "body_sha256": digest(capture.body)}


def parse_index(capture):
    rows = _rows(capture.body, INDEX_HEADER)
    parsed = []
    seen = set()
    month = _POLICY["sources"]["index"]["requests"][capture.ordinal][:7]
    for ordinal, row in enumerate(rows, 1):
        day = _market_date(row[0], roc=False).isoformat()
        actual = date.fromisoformat(day)
        require(day[:7] == month and day not in seen and actual.weekday() < 5
                and day not in _POLICY["calendar"]["closed_dates"]
                and day <= _POLICY["calendar"]["observation_date"], "index_date_bound_or_duplicate")
        seen.add(day)
        opening, high, low, closing = (_decimal(x, positive=True) for x in row[1:5])
        _decimal(row[5], positive=False)
        require(low <= min(opening, closing) <= max(opening, closing) <= high, "index_ohlc_invalid")
        parsed.append(trace(capture, ordinal, row, day))
    return parsed


def checked_calendar(captures):
    """Validate all returned rows before selecting the complete cutoff calendar."""
    rows = sorted(parse_index(captures[0]) + parse_index(captures[1]), key=lambda x: x["date"])
    original = [row["date"] for row in rows]
    require(len(original) == len(set(original)), "calendar_duplicate")
    begin, end = date.fromisoformat(_POLICY["calendar"]["from"]), date.fromisoformat(CUTOFF)
    expected = []
    while begin <= end:
        day = begin.isoformat()
        if begin.weekday() < 5 and day not in _POLICY["calendar"]["closed_dates"]:
            expected.append(day)
        begin += timedelta(days=1)
    adopted = [day for day in original if day <= CUTOFF]
    require(adopted == expected and tuple(adopted) == ADOPTED_DATES and tuple(adopted[-20:]) == DATES,
            "complete_adopted_calendar_mismatch")
    return {"original_dates": original, "adopted_dates": adopted, "rows": rows,
            "post_cutoff_excluded": [day for day in original if day > CUTOFF]}


def parse_daily(capture):
    day = DATES[capture.ordinal - 2]
    selected, seen = {}, set()
    for ordinal, row in enumerate(_rows(capture.body, HEADER), 1):
        require(_market_date(row[0], roc=True).isoformat() == day, "daily_date_mismatch")
        require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None and row[1] not in seen, "daily_identity_duplicate_or_invalid")
        require(bool(row[2].strip()), "daily_name_missing")
        seen.add(row[1])
        if row[1] not in SYMBOLS:
            continue
        require(row[2].strip() == NAMES[row[1]], "selected_identity_name_mismatch")
        groups = []
        for start in (3, 6, 9, 12, 15, 18, 21):
            buy, sell, net = (integer(row[start], True), integer(row[start + 1], True), integer(row[start + 2]))
            require(net == buy - sell, "daily_net_relation")
            groups.append((buy, sell, net))
        require(groups[2] == tuple(a + b for a, b in zip(groups[0], groups[1])), "foreign_components")
        require(groups[6] == tuple(a + b for a, b in zip(groups[4], groups[5])), "dealer_components")
        require(integer(row[24]) == groups[0][2] + groups[3][2] + groups[6][2], "daily_total_relation")
        selected[row[1]] = {**trace(capture, ordinal, row, day), "gross": dict(zip(INVESTORS, (groups[0], groups[3], groups[6])))}
    require(set(selected) == set(SYMBOLS), "daily_selected_missing")
    return selected


def blank(reason, as_of=CUTOFF, generation=None):
    return {"schema": SCHEMA, "calculation_version": CALCULATION, "profile": PROFILE,
            "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST, "policy": policy(),
            "as_of": as_of, "generation": generation, "available": False, "reason": reason,
            "count": None, "stocks": [], "calendar": None, "receipts": []}


def summarize(captures, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE, generation=None):
    try:
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        require(type(captures) in (tuple, list) and len(captures) == 22, "capture_set_incomplete")
        require(sum(len(c.body) for c in captures) <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
        previous = None
        receipts = []
        for ordinal, c in enumerate(captures):
            receipt = checked_capture(c, ordinal, previous)
            previous = c.captured_at
            receipts.append({"original": receipt, "canonical": c.original_receipt_bytes.decode("utf-8"), "sha256": c.original_receipt_sha256})
        calendar = checked_calendar(captures)
        daily = [parse_daily(c) for c in captures[2:]]
        stocks = []
        for symbol in SYMBOLS:
            series = {}
            for investor in INVESTORS:
                windows = {}
                for horizon in (5, 20):
                    rows = [d[symbol] for d in daily[-horizon:]]
                    totals = tuple(bounded(sum(row["gross"][investor][i] for row in rows), "aggregate_int64_overflow") for i in range(3))
                    require(totals[0] - totals[1] == totals[2], "aggregate_net_reconciliation")
                    prefix = [0, 0, 0]
                    points = []
                    for row in rows:
                        values = row["gross"][investor]
                        prefix = [bounded(prefix[i] + values[i], "running_prefix_int64_overflow") for i in range(3)]
                        require(prefix[0] - prefix[1] == prefix[2], "prefix_net_reconciliation")
                        point = {k: v for k, v in row.items() if k != "gross"}
                        for i, component in enumerate(("buy", "sell", "net")):
                            point[component + "_shares"] = str(values[i])
                            point[component + "_lots"] = lots(values[i])
                            point["cumulative_" + component + "_shares"] = str(prefix[i])
                            point["cumulative_" + component + "_lots"] = lots(prefix[i])
                        points.append(point)
                    require(tuple(prefix) == totals, "final_cumulative_reconciliation")
                    window = {"horizon": horizon, "points": points}
                    for i, component in enumerate(("buy", "sell", "net")):
                        window["total_" + component + "_shares"] = str(totals[i])
                        window["total_" + component + "_lots"] = lots(totals[i])
                        window["verified_" + component + "_zero"] = totals[i] == 0
                    windows[str(horizon)] = window
                series[investor] = windows
            stocks.append({"symbol": symbol, "name": NAMES[symbol], "exchange": "TPEx", "security_type": "stock", "currency": "TWD", "series": series})
        result = blank("", generation=generation) | {"available": True, "reason": None, "count": 7, "stocks": stocks,
                "calendar": calendar, "receipts": receipts}
        require(graph_estimate((captures, result)) <= _POLICY["execution"]["max_retained_graph_estimate_bytes"], "retained_graph_estimate_limit")
        return result
    except (GrossError, WindowEvidenceError, ValueError, TypeError, AttributeError, IndexError, KeyError) as exc:
        return blank(str(exc), generation=generation)


class Producer:
    """One new empty producer. fetch(url, body_cap, deadline) is injected by the runner."""
    def __init__(self, fetch, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        self.fetch = fetch
        self.generation = str(uuid.uuid4())
        self.attempted = False
        self.request_count = 0
        self._captures = ()
        self._result = blank("not_captured", generation=self.generation)
        self._lock = threading.Lock()

    def read(self, as_of=CUTOFF):
        if as_of != CUTOFF:
            return blank("cutoff_not_supported", as_of)
        with self._lock:
            return copy.deepcopy(self._result) | {"attempted": self.attempted, "request_count": self.request_count}

    def capture(self):
        with self._lock:
            require(not self.attempted, "already_attempted")
            self.attempted = True
            captures, total = [], 0
            deadline = time.monotonic() + 180
            try:
                require(utcnow().date().isoformat() == "2026-10-08", "capture_observation_date_changed")
                for ordinal, url in enumerate(URLS):
                    require(time.monotonic() < deadline, "batch_deadline")
                    cap = _POLICY["sources"]["index" if ordinal < 2 else "daily"]["max_body_bytes"]
                    started = utcnow()
                    require(started.date().isoformat() == "2026-10-08", "capture_observation_date_changed")
                    self.request_count += 1
                    response = self.fetch(url, cap, deadline)
                    require(time.monotonic() <= deadline, "batch_deadline")
                    c = Captured(ordinal, url, response["body"], started, utcnow(),
                                 response["status"], response["content_type"], response["content_encoding"])
                    checked_capture(c, ordinal, captures[-1].captured_at if captures else None)
                    total += len(c.body)
                    require(total <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
                    captures.append(c)
                    if ordinal < 2:
                        parse_index(c)  # Both full monthly calendars gate every daily request.
                        if ordinal == 1:
                            checked_calendar(captures)
                    else:
                        parse_daily(c)
                    require(graph_estimate(captures) <= _POLICY["execution"]["max_retained_graph_estimate_bytes"], "retained_graph_estimate_limit")
                self._captures = tuple(captures)
                self._result = summarize(self._captures, generation=self.generation)
                require(self._result["available"], self._result["reason"])
            except Exception as exc:
                self._captures = tuple(captures)
                self._result = blank(str(exc), generation=self.generation)
            return self.read_unlocked()

    def read_unlocked(self):
        return copy.deepcopy(self._result) | {"attempted": self.attempted, "request_count": self.request_count}

    def diagnostic(self):
        with self._lock:
            result = {"generation": self.generation, "attempted": self.attempted, "request_count": self.request_count,
                      "seed_count": 0, "preloaded": False, "policy_digest": POLICY_DIGEST,
                      "captures": [{"body_base64": base64.b64encode(c.body).decode("ascii"),
                                    "original_receipt_base64": base64.b64encode(c.original_receipt_bytes).decode("ascii"),
                                    "original_receipt_sha256": c.original_receipt_sha256} for c in self._captures]}
            require(len(canonical(result)) <= 16 * 1024 * 1024, "diagnostic_response_limit")
            return result
