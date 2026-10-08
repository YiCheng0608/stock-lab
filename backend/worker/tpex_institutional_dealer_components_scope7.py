"""Independent dealer self/hedge/total evidence; only explicit FIRST performs I/O."""
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
from urllib.parse import quote
from .tpex_institutional_window import _rows, _market_date, _decimal, WindowEvidenceError

POLICY_CANONICAL = r'''{"calculation_version":"dealer-self-hedge-total-buy-sell-net/five-session-step-int64-v1","calendar":{"closed_dates":["2026-09-25","2026-09-28"],"closed_notice":"https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html","completeness":"ALL_adopted_dates_equal_weekdays_from_through_cutoff_minus_explicit_closed_dates; only_then_derive_last5","from":"2026-09-01","meaning":"observed_index_calendar_only_not_stock_closes","observation_date":"2026-10-08","original_rows":"validate_ALL_returned_month_rows_ALL6_fields_before_selection; unique_requested_month_valid_weekday_nonclosed_positive_finite_OHLC; no_future_after_observation_date; no_assumed_row_count","post_cutoff":"validate_and_retain_all_original_rows_but_exclude_after_cutoff","rule_evidence":"starting214b_SOURCE45_ROOT_accepted_complete_original_rule_and_notice_clauses; reuse_frozen_rules_not_old_financial_calendar_or_capture; new6_metadata_transfer_incomplete_not_new_clause_audit","to":"2026-10-06","weekday_rule":"https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html","window":"last5_fresh_derived_dates_strict_order_exact5; no_old_calendar_seed"},"calendar_schema":"institutional-dealer-components-calendar/chips-stock-scope-7-v1","calendar_version":"dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1","capture_schema":"tpex-institutional-dealer-components-capture/chips-stock-scope-7-v1","entry":{"actions":"explicit_trusted_FIRST_once_then_explicit_READ_held; stock_asof_investor_horizon_apply_back_no_automatic_fetch","api":"/api/chips/dealer-components-stock-scope-7","capture_api":"/api/chips/dealer-components-stock-scope-7/capture","capture_keys":["as_of"],"failure":"samekey_or_samegeneration_failure_masks_ALL_daily_window_totals_component_checks_raw_receipts_calendar; apply_back_pagehide_and_pageshow_persisted_never_unmask_without_successful_explicit_READ","frontend_flag":"VITE_CHIPS_DEALER_COMPONENTS_STOCK_SCOPE_7=m1-v1","get_body_bytes":0,"get_keys":["as_of"],"navigation":"detail_raw_calendar_and_back_preserve_all3_raw_controls_same_cutoff; self_hedge_total_always_parallel","no_ranking_filter_price_signal_plan_save_crossprocess":true,"old_profiles":"immutable_default_off_no_oldproducer_capture_clone_replay_hydration_preload_private_price","parameters":"exact_keys_once_no_unknown_duplicates; ISO_date; dealer_only_horizon5_only; unsupported_valid_cutoff_unavailable_before_state_or_IO","post_body":"empty_JSON_object","post_body_max":4096,"raw_controls":["as_of","investor","horizon"],"route":"/chips-stock-scope-7-dealer-components","runner_flag":"--chips-dealer-components-stock-scope-7-opt-in"},"execution":{"batch_deadline_seconds":180,"deadline":"cooperative_request_response_chunk_checks_not_OS_preemption","diagnostic_max_response_bytes":16777216,"disk_artifacts":0,"estimate":"deduplicated_getsizeof_not_RSS_or_construction_peak","freshness":"ONE_new_empty_distinct_producer_ZERO_seed_preload_FIRST_once_failure_SPENT; no_old_raw_capture_receipt_reuse; calendar_first_then_dynamic_daily_sequence; source_schema_date_contract_conflict_stop_without_retry","header_cap":"received_header_postcheck_not_socket_cap","max_requests":7,"max_response_header_bytes":16384,"max_retained_graph_estimate_bytes":67108864,"max_total_bytes":12582912,"metadata_get":0,"ordinary_price_get":0,"private_actual_io":0,"redirects":0,"request_timeout_seconds":15,"retries":0,"storage":"process_memory","transport":"request_local_DNS_and_exact_TPEx_IP443_only_finally_clear; no_cross_thread_authority","upstream_post":0},"profile":"free_public_local_chips_only_dealer_components_stock_scope_7","read_schema":"institutional-dealer-components-read/chips-stock-scope-7-v1","rights":{"access_basis":"ROOT_NEW3_direct_official_dataset_HTML11391_11856_and_English_TPEx_terms_complete_original_bodies_unaugmented_receipts_byteequal_dualSHA_verified; OGL1_full_primary_reader_clauses_verified; dataset_owner_provider_free_license1_exact_CSV_resource_links; TPEx_section7_open_data_exception_section5_general_download_restriction_retained; first6_direct_metadata_SPENT_incomplete_ROOT_transfer_not_passed; 2_reader_SPENT_OGL_success_Chinese_terms_InternalError_not_direct_HTTP_counter; finite_local_RAM_dealer_component_comparison_only","attribution":"金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；自行買賣、避險及總額之每日與五日比較為本地衍生結果。","first_available_time":"unknown","historical_pit":"unsupported","license":"Government Data Open License v1.0","license_url":"https://data.gov.tw/license","metadata_provider":"Financial Supervisory Commission, Securities and Futures Bureau","owner":"Taipei Exchange (TPEx)","published_time":"unknown","revision_time":"unknown","statistical_basis":"original_trade_executions_before_broker_account_corrections","uses":["local_fetch","raw_store_process_memory_only","derive_self_hedge_total_daily_and_five_session_buy_sell_net_with_complete_attribution"]},"scope":{"components":["self","hedge","total"],"currency":"TWD","cutoff":"2026-10-06","exchange":"TPEx","horizons":[5],"identities":{"3105":"穩懋","3293":"鈊象","5274":"信驊","5347":"世界","6488":"環球晶","6510":"精測","8069":"元太"},"identity_date":"2026-10-06","investors":["dealer"],"market":"TW","pit_membership":false,"security_type":"stock","symbols":["3105","3293","5274","5347","6488","6510","8069"],"window_count":1},"series":{"actual_zero":"fresh_original_self_hedge_total_daily_or_window_zero_only; zero_distinct_missing; absent_actual_zero_shape_remains_gap","completeness":"ALL35_selected_rows_ALL875_original_strings_ALL770_int64_before_any_available_result","components":{"hedge":[18,19,20],"self":[15,16,17],"total":[21,22,23]},"display":"ALL3_self_hedge_total_buy_sell_net_parallel_daily_and_five_session_totals; no_component_filter_no_relabel_oldTOTAL","encoding":"canonical_integer_strings","lots_denominator":1000,"lots_max_decimals":3,"overflow":"check_ALL22_daily_numeric_fields_ALL7_buy_sell_net_triplets; every_component_addition_subtraction_and_each5_window_sum_step_signed_int64; buy_minus_sell_equals_net_each_day_and_window; self_plus_hedge_equals_total_for_each_metric_each_day_and_window; any_failure_whole7_unavailable","signed_max":"9223372036854775807","signed_min":"-9223372036854775808","trace":"ALL35_rows_preserve_ALL25_original_fields_header_ordinal_body_SHA256_unaugmented_ORIGINAL_receipt_SHA256_and_ALL_returned_calendar","unit":"shares"},"sources":{"body":"empty","charset":"utf-8","content_encoding":"identity","content_types":["application/csv","text/csv"],"daily":{"base_url":"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data","dataset":"https://data.gov.tw/dataset/11856","header":["資料日期","代號","名稱","外資及陸資不含外資自營商買進股數","外資及陸資不含外資自營商賣出股數","外資及陸資不含外資自營商買賣超股數","外資自營商買進股數","外資自營商賣出股數","外資自營商買賣超股數","外資及陸資買進股數","外資及陸資賣出股數","外資及陸資買賣超股數","投信買進股數","投信賣出股數","投信買賣超股數","自營商自行買賣買進股數","自營商自行買賣賣出股數","自營商自行買賣買賣超股數","自營商避險買進股數","自營商避險賣出股數","自營商避險買賣超股數","自營商買進股數","自營商賣出股數","自營商買賣超股數","三大法人買賣超股數合計"],"max_body_bytes":2097152,"source_version":"dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1"},"exact_sequence":"2_index_base_URLs_plus_date=percent_encoded_YYYY/MM/01; then_5_daily_base_URLs_plus_d=percent_encoded_ROCyear/MM/DD_for_only_last5_derived_after_ALL_calendar_validation","http_status":200,"index":{"base_url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data","dataset":"https://data.gov.tw/dataset/11391","header":["資料日期","開市","最高價","最低價","收市","漲跌"],"max_body_bytes":1048576,"requests":["2026-09-01","2026-10-01"],"source_version":"dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1"},"method":"GET","validation":"ALL_daily_structure_dates_unique_codes_names; ALL7_identity_and_missing_checks; ALL_selected_original_integer_fields_and_components; ORIGINAL_body_and_unaugmented_canonical_receipt_dual_SHA_UTC_monotonic"},"version":"m1-chips-dealer-components-stock-scope-7-tpex-2026-10-06.1","worker_schema":"tpex-institutional-dealer-components/chips-stock-scope-7-v1"}'''
POLICY_SHA256 = "54347a73a5d725e702599eb582e9c75550f2c24c6839afd61c890e37bed99eab"
POLICY_DIGEST = "sha256:" + POLICY_SHA256
_POLICY = json.loads(POLICY_CANONICAL)
POLICY_VERSION, PROFILE = _POLICY["version"], _POLICY["profile"]
SCHEMA, WORKER_SCHEMA = _POLICY["read_schema"], _POLICY["worker_schema"]
CAPTURE_SCHEMA, CALCULATION = _POLICY["capture_schema"], _POLICY["calculation_version"]
CALENDAR_SCHEMA, CALENDAR_VERSION = _POLICY["calendar_schema"], _POLICY["calendar_version"]
CUTOFF = _POLICY["scope"]["cutoff"]
SYMBOLS, NAMES = tuple(_POLICY["scope"]["symbols"]), _POLICY["scope"]["identities"]
COMPONENTS, METRICS = ("self", "hedge", "total"), ("buy", "sell", "net")
HEADER, INDEX_HEADER = tuple(_POLICY["sources"]["daily"]["header"]), tuple(_POLICY["sources"]["index"]["header"])
INDEX_URLS = tuple(_POLICY["sources"]["index"]["base_url"] + "&date=" + quote(d.replace("-", "/"), safe="") for d in _POLICY["sources"]["index"]["requests"])
MIN_I64, MAX_I64 = -(2**63), 2**63 - 1


class DealerComponentsError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise DealerComponentsError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def policy():
    return json.loads(POLICY_CANONICAL)


def check_policy(value, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
    raw = POLICY_CANONICAL.encode("utf-8")
    require(len(raw) == 9245 and digest(raw) == POLICY_SHA256, "literal_policy_corrupt")
    require((version, pin, profile) == (POLICY_VERSION, POLICY_DIGEST, PROFILE), "policy_pin_mismatch")
    require(canonical(value) == raw, "canonical_policy_mismatch")


def bounded(n, reason="arithmetic_int64_overflow"):
    require(type(n) is int and MIN_I64 <= n <= MAX_I64, reason)
    return n


def integer(value, gross=False):
    require(type(value) is str and len(value) <= 20 and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "integer_not_canonical")
    n = bounded(int(value), "daily_int64_overflow")
    require(not gross or n >= 0, "negative_gross")
    return n


def lots(value):
    n = integer(value)
    whole, rest = divmod(abs(n), 1000)
    return ("-" if n < 0 else "") + str(whole) + (("." + str(rest).zfill(3).rstrip("0")) if rest else "")


def amounts(values):
    require(len(values) == 3 and bounded(values[0] - values[1]) == values[2], "buy_sell_net_mismatch")
    result = {}
    for metric, value in zip(METRICS, values):
        bounded(value)
        require(metric == "net" or value >= 0, "negative_gross")
        result[metric + "_shares"] = str(value)
        result[metric + "_lots"] = lots(str(value))
        result["verified_" + metric + "_zero"] = value == 0
    return result


def daily_url(day):
    actual = date.fromisoformat(day)
    return _POLICY["sources"]["daily"]["base_url"] + "&d=" + quote(f"{actual.year - 1911}/{actual.month:02}/{actual.day:02}", safe="")


def graph_estimate(value):
    """Deduplicated getsizeof estimate, never RSS or construction peak."""
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
    requested_date: str
    url: str
    body: bytes
    request_started_at: datetime
    captured_at: datetime
    http_status: int = 200
    content_type: str = "application/csv;charset=utf-8"
    content_encoding: str = "identity"
    original_receipt_bytes: bytes = field(init=False, repr=False)
    original_receipt_sha256: str = field(init=False)

    def __post_init__(self):
        raw = canonical(self.receipt())
        object.__setattr__(self, "original_receipt_bytes", raw)
        object.__setattr__(self, "original_receipt_sha256", digest(raw))

    def receipt(self):
        source = "index" if self.ordinal < 2 else "daily"
        return {"schema": CAPTURE_SCHEMA, "ordinal": self.ordinal, "source": source,
                "source_version": _POLICY["sources"][source]["source_version"], "requested_date": self.requested_date,
                "url": self.url, "method": "GET", "request_body_bytes": 0, "http_status": self.http_status,
                "content_type": self.content_type, "content_encoding": self.content_encoding,
                "body_bytes": len(self.body), "body_sha256": digest(self.body),
                "request_started_at": self.request_started_at.isoformat(), "captured_at": self.captured_at.isoformat(),
                "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST, "profile": PROFILE,
                "publication_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
                "historical_pit": "unsupported", "request_count": 1}


def checked_capture(c, ordinal, requested, url, previous=None):
    require(type(c) is Captured and type(c.ordinal) is int and c.ordinal == ordinal and type(c.body) is bytes, "capture_type_or_order_invalid")
    require(c.requested_date == requested and c.url == url, "capture_date_or_url_mismatch")
    require(c.http_status == 200 and c.content_encoding.lower() == "identity", "capture_status_or_encoding")
    media = c.content_type.lower().replace(" ", "")
    require(media.split(";")[0] in ("text/csv", "application/csv") and ("charset=" not in media or "charset=utf-8" in media), "capture_content_type")
    require(0 < len(c.body) <= _POLICY["sources"]["index" if ordinal < 2 else "daily"]["max_body_bytes"], "capture_body_limit")
    for instant in (c.request_started_at, c.captured_at):
        require(type(instant) is datetime and instant.tzinfo is timezone.utc and instant.date().isoformat() == _POLICY["calendar"]["observation_date"], "capture_utc_or_observation_date")
    require(c.request_started_at <= c.captured_at and (previous is None or previous <= c.request_started_at), "capture_time_order")
    require(c.original_receipt_bytes == canonical(c.receipt()) and c.original_receipt_sha256 == digest(c.original_receipt_bytes), "original_receipt_tampered")
    return c.receipt()


def trace(c, ordinal, row, day):
    return {"date": day, "row_ordinal": ordinal, "source_values": row,
            "receipt_sha256": c.original_receipt_sha256, "body_sha256": digest(c.body)}


def parse_index(c):
    result, seen = [], set()
    month = _POLICY["sources"]["index"]["requests"][c.ordinal][:7]
    for ordinal, row in enumerate(_rows(c.body, INDEX_HEADER), 1):
        day = _market_date(row[0], roc=False).isoformat()
        actual = date.fromisoformat(day)
        require(day[:7] == month and day not in seen and actual.weekday() < 5 and day not in _POLICY["calendar"]["closed_dates"] and day <= _POLICY["calendar"]["observation_date"], "index_date_bound_or_duplicate")
        seen.add(day)
        opening, high, low, closing = (_decimal(x, positive=True) for x in row[1:5])
        _decimal(row[5], positive=False)
        require(low <= min(opening, closing) <= max(opening, closing) <= high, "index_ohlc_invalid")
        result.append(trace(c, ordinal, row, day))
    return result


def checked_calendar(captures):
    require(len(captures) == 2, "two_index_originals_required")
    rows = sorted(parse_index(captures[0]) + parse_index(captures[1]), key=lambda r: r["date"])
    original = [r["date"] for r in rows]
    require(len(original) == len(set(original)), "calendar_duplicate")
    begin, end = date.fromisoformat(_POLICY["calendar"]["from"]), date.fromisoformat(CUTOFF)
    expected = []
    while begin <= end:
        day = begin.isoformat()
        if begin.weekday() < 5 and day not in _POLICY["calendar"]["closed_dates"]:
            expected.append(day)
        begin += timedelta(days=1)
    adopted = [d for d in original if d <= CUTOFF]
    require(adopted == expected and len(adopted) >= 5, "complete_adopted_calendar_mismatch")
    return {"schema": CALENDAR_SCHEMA, "version": CALENDAR_VERSION, "original_dates": original,
            "adopted_dates": adopted, "daily_dates": adopted[-5:], "rows": rows,
            "post_cutoff_excluded": [d for d in original if d > CUTOFF]}


def parse_daily(c, day):
    selected, seen = {}, set()
    for ordinal, row in enumerate(_rows(c.body, HEADER), 1):
        require(_market_date(row[0], roc=True).isoformat() == day, "daily_date_mismatch")
        require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None and row[1] not in seen and bool(row[2].strip()), "daily_identity_duplicate_or_invalid")
        seen.add(row[1])
        if row[1] not in SYMBOLS:
            continue
        require(row[2].strip() == NAMES[row[1]], "selected_identity_name_mismatch")
        groups = []
        for start in (3, 6, 9, 12, 15, 18, 21):
            buy, sell, net = integer(row[start], True), integer(row[start + 1], True), integer(row[start + 2])
            require(net == bounded(buy - sell), "daily_net_relation")
            groups.append((buy, sell, net))
        require(groups[2] == tuple(bounded(a + b) for a, b in zip(groups[0], groups[1])), "foreign_components")
        require(groups[6] == tuple(bounded(a + b) for a, b in zip(groups[4], groups[5])), "dealer_components")
        require(integer(row[24]) == bounded(bounded(groups[0][2] + groups[3][2]) + groups[6][2]), "daily_total_relation")
        selected[row[1]] = {**trace(c, ordinal, row, day), "components": {name: amounts(groups[i]) for name, i in zip(COMPONENTS, (4, 5, 6))}, "component_check": True}
    require(set(selected) == set(SYMBOLS), "daily_selected_missing")
    return selected


def window(points):
    require(len(points) == 5, "five_session_window_required")
    sums = {name: [0, 0, 0] for name in COMPONENTS}
    for point in points:
        for name in COMPONENTS:
            for i, metric in enumerate(METRICS):
                sums[name][i] = bounded(sums[name][i] + integer(point["components"][name][metric + "_shares"]), "window_sum_step_int64_overflow")
    require(sums["total"] == [bounded(a + b) for a, b in zip(sums["self"], sums["hedge"])], "window_components")
    return {"horizon": 5, "points": points, "totals": {name: amounts(sums[name]) for name in COMPONENTS}, "component_check": True}


def blank(reason, as_of=CUTOFF, generation=None):
    return {"schema": SCHEMA, "worker_schema": WORKER_SCHEMA, "capture_schema": CAPTURE_SCHEMA,
            "calendar_schema": CALENDAR_SCHEMA, "calendar_version": CALENDAR_VERSION, "calculation_version": CALCULATION,
            "profile": PROFILE, "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST, "policy": policy(),
            "as_of": as_of, "generation": generation, "available": False, "reason": reason, "count": None,
            "stocks": [], "calendar": None, "receipts": []}


def summarize(captures, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE, generation=None):
    try:
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        require(type(captures) in (tuple, list) and len(captures) == 7, "capture_set_incomplete")
        require(sum(len(c.body) for c in captures) <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
        for ordinal, c in enumerate(captures[:2]):
            checked_capture(c, ordinal, _POLICY["sources"]["index"]["requests"][ordinal], INDEX_URLS[ordinal], captures[ordinal - 1].captured_at if ordinal else None)
        calendar = checked_calendar(captures[:2])
        receipts = []
        for ordinal, c in enumerate(captures):
            requested = _POLICY["sources"]["index"]["requests"][ordinal] if ordinal < 2 else calendar["daily_dates"][ordinal - 2]
            url = INDEX_URLS[ordinal] if ordinal < 2 else daily_url(requested)
            checked_capture(c, ordinal, requested, url, captures[ordinal - 1].captured_at if ordinal else None)
            receipts.append({"original": c.receipt(), "canonical": c.original_receipt_bytes.decode("utf-8"), "sha256": c.original_receipt_sha256})
        daily = [parse_daily(c, day) for c, day in zip(captures[2:], calendar["daily_dates"])]
        stocks = [{"symbol": symbol, "name": NAMES[symbol], "exchange": "TPEx", "security_type": "stock", "currency": "TWD",
                   "window": window([d[symbol] for d in daily])} for symbol in SYMBOLS]
        result = blank("", generation=generation) | {"available": True, "reason": None, "count": 7, "stocks": stocks, "calendar": calendar, "receipts": receipts}
        require(graph_estimate((captures, result)) <= _POLICY["execution"]["max_retained_graph_estimate_bytes"], "retained_graph_estimate_limit")
        return result
    except (DealerComponentsError, WindowEvidenceError, ValueError, TypeError, AttributeError, IndexError, KeyError, OverflowError) as exc:
        return blank(str(exc), generation=generation)


class Producer:
    def __init__(self, fetch, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        self.fetch, self.generation = fetch, str(uuid.uuid4())
        self.attempted, self.request_count, self._captures = False, 0, ()
        self.request_urls = INDEX_URLS
        self._result = blank("not_captured", generation=self.generation)
        self._lock = threading.Lock()

    def read(self, as_of=CUTOFF):
        if as_of != CUTOFF:
            return blank("cutoff_not_supported", as_of)
        with self._lock:
            return self._read()

    def _read(self):
        return copy.deepcopy(self._result) | {"attempted": self.attempted, "request_count": self.request_count}

    def capture(self):
        with self._lock:
            require(not self.attempted, "already_attempted")
            self.attempted = True
            captures, total = [], 0
            deadline = time.monotonic() + _POLICY["execution"]["batch_deadline_seconds"]
            try:
                require(utcnow().date().isoformat() == _POLICY["calendar"]["observation_date"], "capture_observation_date_changed")
                requested_dates = list(_POLICY["sources"]["index"]["requests"])
                ordinal = 0
                while ordinal < len(self.request_urls):
                    require(ordinal < 7 and time.monotonic() < deadline, "batch_deadline_or_request_cap")
                    url, requested = self.request_urls[ordinal], requested_dates[ordinal]
                    started = utcnow()
                    require(started.date().isoformat() == _POLICY["calendar"]["observation_date"], "capture_observation_date_changed")
                    cap = _POLICY["sources"]["index" if ordinal < 2 else "daily"]["max_body_bytes"]
                    self.request_count += 1
                    response = self.fetch(url, cap, deadline)
                    require(time.monotonic() <= deadline, "batch_deadline")
                    c = Captured(ordinal, requested, url, response["body"], started, utcnow(), response["status"], response["content_type"], response["content_encoding"])
                    captures.append(c)
                    checked_capture(c, ordinal, requested, url, captures[-2].captured_at if ordinal else None)
                    total += len(c.body)
                    require(total <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
                    if ordinal < 2:
                        parse_index(c)
                        if ordinal == 1:
                            calendar = checked_calendar(captures)
                            requested_dates.extend(calendar["daily_dates"])
                            self.request_urls = INDEX_URLS + tuple(daily_url(d) for d in calendar["daily_dates"])
                    else:
                        parse_daily(c, requested)
                    require(graph_estimate(captures) <= _POLICY["execution"]["max_retained_graph_estimate_bytes"], "retained_graph_estimate_limit")
                    ordinal += 1
                self._captures = tuple(captures)
                self._result = summarize(self._captures, generation=self.generation)
                require(self._result["available"], self._result["reason"])
            except Exception as exc:
                self._captures = tuple(captures)
                self._result = blank(str(exc), generation=self.generation)
            return self._read()

    def diagnostic(self):
        with self._lock:
            result = {"generation": self.generation, "attempted": self.attempted, "request_count": self.request_count,
                      "seed_count": 0, "preloaded": False, "policy_digest": POLICY_DIGEST, "request_urls": list(self.request_urls),
                      "captures": [{"body_base64": base64.b64encode(c.body).decode("ascii"), "body_sha256": digest(c.body),
                                    "original_receipt_base64": base64.b64encode(c.original_receipt_bytes).decode("ascii"),
                                    "original_receipt_sha256": c.original_receipt_sha256} for c in self._captures]}
            require(len(canonical(result)) <= _POLICY["execution"]["diagnostic_max_response_bytes"], "diagnostic_response_limit")
            return result
