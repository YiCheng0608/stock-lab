"""Independent finite direction/segments profile; import and reads perform no I/O."""
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

POLICY_CANONICAL = r'''{"calculation_version":"net-sign-triples-counts-contiguous-segments/window-limited-int64-v1","calendar":{"adopted_dates":["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"closed_dates":["2026-09-25","2026-09-28"],"closed_notice":"https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html","completeness":"ALL_adopted_dates_equal_weekdays_2026-09-01_through_cutoff_minus_explicit_closed_dates; last20_last5_only_after_full_validation","from":"2026-09-01","meaning":"observed_index_calendar_only_not_stock_closes","observation_date":"2026-10-08","original_rows":"validate_ALL_returned_month_rows_before_selection; unique_requested_month_valid_weekday_nonclosed_positive_finite_OHLC; no_future_after_observation_date; no_assumed_row_count","post_cutoff":"validate_and_retain_all_original_rows_but_exclude_after_cutoff","to":"2026-10-06","weekday_rule":"https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html"},"calendar_schema":"institutional-direction-calendar/chips-stock-scope-7-v1","calendar_version":"dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1","capture_schema":"tpex-institutional-direction-capture/chips-stock-scope-7-v1","direction":{"actual_zero":"only_fresh_original_raw_net_zero_proves_actual_zero; absent_all_zero_triple_remains_acceptance_gap; derived_count_zero_requires_full_original_predicate_verification","boundary":"first_segment_earlier_unknown_true_at_window_start; never_claim_full_history_duration_even_when_longer_window_is_available","categories":{"all_negative":"all_three_negative","all_positive":"all_three_positive","all_zero":"all_three_exact_zero","opposite":"at_least_one_positive_and_at_least_one_negative_zero_allowed","single_direction_with_zero":"one_nonzero_direction_and_at_least_one_zero"},"counts":"per_investor_window_positive_negative_zero_predicates; sum_equals_window_length","latest_run":"last_segment_only_within_selected_window; latest_zero_interrupts_positive_negative_run","segment_fields":["sign","start_index","end_index","start_date","end_date","length","earlier_unknown"],"segments":"maximal_contiguous_equal_sign; zero_separate_and_breaks_positive_negative; cover_window_once_no_overlap_gap_or_adjacent_equal_sign","sign":"positive_if_net_gt_0_negative_if_lt_0_zero_if_exact_0; unknown_missing_never_zero","triple_order":["foreign","trust","dealer"]},"entry":{"actions":"explicit_trusted_FIRST_once_then_explicit_READ_held; stock_investor_horizon_apply_back_no_automatic_fetch","api":"/api/chips/direction-stock-scope-7","capture_api":"/api/chips/direction-stock-scope-7/capture","capture_keys":["as_of"],"failure":"same_generation_failure_masks_ALL_direction_counts_segments_latest_runs_sign_triples_raw_receipts_calendar; controls_apply_back_never_unmask_without_successful_explicit_READ","frontend_flag":"VITE_CHIPS_DIRECTION_STOCK_SCOPE_7=m1-v1","get_body_bytes":0,"get_keys":["as_of"],"navigation":"detail_stock_and_back_preserve_all_raw_controls_same_cutoff","old_profiles":"immutable_default_off_no_private_price_oldproducer_capture_clone_replay_hydration_preload","parameters":"exact_keys_once_no_unknown_duplicates; ISO_date; unsupported_valid_cutoff_unavailable_before_state_or_IO","post_body":"empty_JSON_object","post_body_max":4096,"raw_controls":["as_of","investor","horizon"],"route":"/chips-stock-scope-7-direction-segments","runner_flag":"--chips-direction-stock-scope-7-opt-in"},"execution":{"batch_deadline_seconds":180,"deadline":"cooperative_checks_at_request_response_chunk_boundaries_not_OS_preemption","diagnostic_max_response_bytes":16777216,"disk_artifacts":0,"estimate":"deduplicated_getsizeof_estimate_not_RSS_or_construction_peak","freshness":"ONE_new_empty_distinct_producer_ZERO_seed_preload_FIRST_once_failure_SPENT; no_old_producer_capture_receipt_reuse; dynamic_full_returned_calendar_validation; source_schema_date_contract_conflict_stop_without_retry","header_cap":"received_header_postcheck_not_socket_cap","max_requests":22,"max_response_header_bytes":16384,"max_retained_graph_estimate_bytes":67108864,"max_total_bytes":44040192,"metadata_get":0,"ordinary_price_get":0,"private_actual_io":0,"redirects":0,"request_timeout_seconds":15,"retries":0,"storage":"process_memory","transport":"request_local_DNS_and_exact_TPEx_IP443_only_finally_clear; no_cross_thread_authority","upstream_post":0},"profile":"free_public_local_chips_only_direction_segments_stock_scope_7","read_schema":"institutional-direction-segments-read/chips-stock-scope-7-v1","rights":{"access_basis":"2026-10-08_ROOT_fresh_exact_dataset11391_11856_free_CSV_UTF8_license1_owner_distribution_verified; OGL1_reproduction_adaptation_attribution; TPEx_terms_section7_government_open_data_exception_section5_not_global_cancellation; finite_local_RAM_direction_use_only","attribution":"財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；方向與區段為本地衍生結果。","first_available_time":"unknown","historical_pit":"unsupported","license":"Government Data Open License v1.0","license_url":"https://data.gov.tw/license","owner":"Taipei Exchange (TPEx)","published_time":"unknown","revision_time":"unknown","statistical_basis":"original_trade_executions_before_broker_account_corrections","uses":["local_fetch","raw_store_process_memory_only","derive_net_sign_triples_counts_contiguous_segments_window_limited_latest_runs_with_complete_attribution"]},"scope":{"currency":"TWD","cutoff":"2026-10-06","daily_dates":["2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"exchange":"TPEx","foreign_definition":"excluding_foreign_dealer","horizons":[5,20],"identities":{"3105":"穩懋","3293":"鈊象","5274":"信驊","5347":"世界","6488":"環球晶","6510":"精測","8069":"元太"},"identity_date":"2026-10-06","investors":["foreign","trust","dealer"],"market":"TW","pit_membership":false,"security_type":"stock","symbols":["3105","3293","5274","5347","6488","6510","8069"]},"series":{"completeness":"ALL7_ALL2windows_ALL3investors_ALL140_sign_triples_before_any_available_result","components":{"dealer":[21,22,23],"foreign":[3,4,5],"trust":[12,13,14]},"encoding":"canonical_integer_strings","lots_denominator":1000,"lots_max_decimals":3,"net":"signed_int64_buy_minus_sell; ALL22_integer_fields_and_components_verified_per_selected_original","overflow":"any_daily_selected_numeric_or_component_relation_outside_signed_int64_makes_entire_profile_unavailable","signed_max":"9223372036854775807","signed_min":"-9223372036854775808","trace":"each_segment_and_dated_point_preserves_three_original_net_fields_ALL25_original_strings_row_ordinal_ORIGINAL_receipt_SHA256_body_SHA256_and_ALL_returned_calendar","unit":"shares","window":"last_exact_5_or_20_adopted_sessions_inclusive_cutoff"},"sources":{"body":"empty","charset":"utf-8","content_encoding":"identity","content_types":["application/csv","text/csv"],"daily":{"base_url":"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data","dataset":"https://data.gov.tw/dataset/11856","header":["資料日期","代號","名稱","外資及陸資不含外資自營商買進股數","外資及陸資不含外資自營商賣出股數","外資及陸資不含外資自營商買賣超股數","外資自營商買進股數","外資自營商賣出股數","外資自營商買賣超股數","外資及陸資買進股數","外資及陸資賣出股數","外資及陸資買賣超股數","投信買進股數","投信賣出股數","投信買賣超股數","自營商自行買賣買進股數","自營商自行買賣賣出股數","自營商自行買賣買賣超股數","自營商避險買進股數","自營商避險賣出股數","自營商避險買賣超股數","自營商買進股數","自營商賣出股數","自營商買賣超股數","三大法人買賣超股數合計"],"max_body_bytes":2097152,"source_version":"dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1"},"exact_urls":["https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F09%2F01","https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F10%2F01","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F07","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F08","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F09","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F10","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F11","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F14","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F15","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F16","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F17","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F18","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F21","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F22","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F23","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F24","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F29","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F09%2F30","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F01","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F02","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F05","https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=115%2F10%2F06"],"http_status":200,"index":{"base_url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data","dataset":"https://data.gov.tw/dataset/11391","header":["資料日期","開市","最高價","最低價","收市","漲跌"],"max_body_bytes":1048576,"requests":["2026-09-01","2026-10-01"],"source_version":"dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1"},"method":"GET","validation":"ALL_returned_index_rows_ALL6_original_fields_no_assumed_count; ALL_daily_structure_dates_unique_codes_names; ALL7x20x25_original_strings_ALL22_int64_fields_ALL7_group_and_component_relations; ORIGINAL_body_and_canonical_receipt_dual_SHA_UTC_monotonic"},"version":"m1-chips-direction-segments-stock-scope-7-tpex-2026-10-06.1","worker_schema":"tpex-institutional-direction/chips-stock-scope-7-v1"}'''
POLICY_SHA256 = "eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348"
POLICY_DIGEST = "sha256:" + POLICY_SHA256
_POLICY = json.loads(POLICY_CANONICAL)
POLICY_VERSION, PROFILE = _POLICY["version"], _POLICY["profile"]
SCHEMA, WORKER_SCHEMA = _POLICY["read_schema"], _POLICY["worker_schema"]
CAPTURE_SCHEMA, CALCULATION = _POLICY["capture_schema"], _POLICY["calculation_version"]
CALENDAR_SCHEMA, CALENDAR_VERSION = _POLICY["calendar_schema"], _POLICY["calendar_version"]
CUTOFF = _POLICY["scope"]["cutoff"]
DATES, ADOPTED_DATES = tuple(_POLICY["scope"]["daily_dates"]), tuple(_POLICY["calendar"]["adopted_dates"])
SYMBOLS, NAMES, INVESTORS = tuple(_POLICY["scope"]["symbols"]), _POLICY["scope"]["identities"], tuple(_POLICY["scope"]["investors"])
HEADER, INDEX_HEADER, URLS = tuple(_POLICY["sources"]["daily"]["header"]), tuple(_POLICY["sources"]["index"]["header"]), tuple(_POLICY["sources"]["exact_urls"])
SIGNS = ("positive", "negative", "zero")
CATEGORIES = ("all_positive", "all_negative", "opposite", "single_direction_with_zero", "all_zero")
MIN_I64, MAX_I64 = -(2**63), 2**63 - 1


class DirectionError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise DirectionError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def policy():
    return json.loads(POLICY_CANONICAL)


def check_policy(value, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
    raw = POLICY_CANONICAL.encode("utf-8")
    require(len(raw) == 12382 and digest(raw) == POLICY_SHA256, "literal_policy_corrupt")
    require((version, pin, profile) == (POLICY_VERSION, POLICY_DIGEST, PROFILE), "policy_pin_mismatch")
    require(canonical(value) == raw, "canonical_policy_mismatch")


def integer(value, gross=False):
    require(type(value) is str and len(value) <= 20 and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "integer_not_canonical")
    n = int(value)
    require(MIN_I64 <= n <= MAX_I64, "daily_int64_overflow")
    require(not gross or n >= 0, "negative_gross")
    return n


def lots(value):
    n = int(value)
    whole, rest = divmod(abs(n), 1000)
    return ("-" if n < 0 else "") + str(whole) + (("." + str(rest).zfill(3).rstrip("0")) if rest else "")


def sign(n):
    require(type(n) is int and MIN_I64 <= n <= MAX_I64, "sign_int64_required")
    return "positive" if n > 0 else "negative" if n < 0 else "zero"


def classify(nets):
    require(type(nets) in (tuple, list) and len(nets) == 3, "three_original_nets_required")
    signs = [sign(n) for n in nets]
    if all(s == "positive" for s in signs):
        return "all_positive"
    if all(s == "negative" for s in signs):
        return "all_negative"
    if "positive" in signs and "negative" in signs:
        return "opposite"
    return "all_zero" if all(s == "zero" for s in signs) else "single_direction_with_zero"


def window_stats(points, investor):
    require(investor in INVESTORS and len(points) in (5, 20), "window_scope_invalid")
    counts = dict.fromkeys(SIGNS, 0)
    segments = []
    for i, point in enumerate(points):
        current = sign(integer(point["net_shares"][investor]))
        counts[current] += 1
        if segments and segments[-1]["sign"] == current:
            segments[-1].update(end_index=i, end_date=point["date"], length=segments[-1]["length"] + 1)
        else:
            segments.append({"sign": current, "start_index": i, "end_index": i, "start_date": point["date"],
                             "end_date": point["date"], "length": 1, "earlier_unknown": i == 0})
    require(sum(counts.values()) == len(points), "counts_reconciliation")
    return {"counts": counts, "segments": segments, "latest_run": dict(segments[-1])}


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
    require(capture.url == URLS[ordinal] and (capture.policy_version, capture.policy_digest, capture.profile) == (POLICY_VERSION, POLICY_DIGEST, PROFILE), "capture_profile_or_url_mismatch")
    require(capture.http_status == 200 and capture.content_encoding.lower() == "identity", "capture_status_or_encoding")
    media = capture.content_type.lower().replace(" ", "")
    require(media.split(";")[0] in ("text/csv", "application/csv") and ("charset=" not in media or "charset=utf-8" in media), "capture_content_type")
    require(0 < len(capture.body) <= _POLICY["sources"]["index" if ordinal < 2 else "daily"]["max_body_bytes"], "capture_body_limit")
    for instant in (capture.request_started_at, capture.captured_at):
        require(type(instant) is datetime and instant.tzinfo is timezone.utc and instant.date().isoformat() == "2026-10-08", "capture_utc_or_observation_date")
    require(capture.request_started_at <= capture.captured_at and (previous is None or previous <= capture.request_started_at), "capture_time_order")
    require(capture.original_receipt_bytes == canonical(capture.receipt()) and capture.original_receipt_sha256 == digest(capture.original_receipt_bytes), "original_receipt_tampered")
    return capture.receipt()


def trace(capture, ordinal, row, day):
    return {"date": day, "row_ordinal": ordinal, "source_values": row,
            "receipt_sha256": capture.original_receipt_sha256, "body_sha256": digest(capture.body)}


def parse_index(capture):
    parsed, seen = [], set()
    month = _POLICY["sources"]["index"]["requests"][capture.ordinal][:7]
    for ordinal, row in enumerate(_rows(capture.body, INDEX_HEADER), 1):
        day = _market_date(row[0], roc=False).isoformat()
        actual = date.fromisoformat(day)
        require(day[:7] == month and day not in seen and actual.weekday() < 5 and day not in _POLICY["calendar"]["closed_dates"] and day <= _POLICY["calendar"]["observation_date"], "index_date_bound_or_duplicate")
        seen.add(day)
        opening, high, low, closing = (_decimal(x, positive=True) for x in row[1:5])
        _decimal(row[5], positive=False)
        require(low <= min(opening, closing) <= max(opening, closing) <= high, "index_ohlc_invalid")
        parsed.append(trace(capture, ordinal, row, day))
    return parsed


def checked_calendar(captures):
    rows = sorted(parse_index(captures[0]) + parse_index(captures[1]), key=lambda x: x["date"])
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
    require(adopted == expected and tuple(adopted) == ADOPTED_DATES and tuple(adopted[-20:]) == DATES, "complete_adopted_calendar_mismatch")
    return {"schema": CALENDAR_SCHEMA, "version": CALENDAR_VERSION, "original_dates": original,
            "adopted_dates": adopted, "rows": rows, "post_cutoff_excluded": [d for d in original if d > CUTOFF]}


def parse_daily(capture):
    day = DATES[capture.ordinal - 2]
    selected, seen = {}, set()
    for ordinal, row in enumerate(_rows(capture.body, HEADER), 1):
        require(_market_date(row[0], roc=True).isoformat() == day, "daily_date_mismatch")
        require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None and row[1] not in seen and bool(row[2].strip()), "daily_identity_duplicate_or_invalid")
        seen.add(row[1])
        if row[1] not in SYMBOLS:
            continue
        require(row[2].strip() == NAMES[row[1]], "selected_identity_name_mismatch")
        groups = []
        for start in (3, 6, 9, 12, 15, 18, 21):
            buy, sell, net = integer(row[start], True), integer(row[start + 1], True), integer(row[start + 2])
            require(net == buy - sell, "daily_net_relation")
            groups.append((buy, sell, net))
        require(groups[2] == tuple(a + b for a, b in zip(groups[0], groups[1])), "foreign_components")
        require(groups[6] == tuple(a + b for a, b in zip(groups[4], groups[5])), "dealer_components")
        require(integer(row[24]) == groups[0][2] + groups[3][2] + groups[6][2], "daily_total_relation")
        nets = [groups[i][2] for i in (0, 3, 6)]
        selected[row[1]] = {**trace(capture, ordinal, row, day), "net_shares": dict(zip(INVESTORS, map(str, nets))),
                           "net_lots": dict(zip(INVESTORS, map(lots, nets))),
                           "signs": dict(zip(INVESTORS, map(sign, nets))), "category": classify(nets)}
    require(set(selected) == set(SYMBOLS), "daily_selected_missing")
    return selected


def blank(reason, as_of=CUTOFF, generation=None):
    return {"schema": SCHEMA, "worker_schema": WORKER_SCHEMA, "capture_schema": CAPTURE_SCHEMA,
            "calendar_schema": CALENDAR_SCHEMA, "calendar_version": CALENDAR_VERSION,
            "calculation_version": CALCULATION, "profile": PROFILE, "policy_version": POLICY_VERSION,
            "policy_digest": POLICY_DIGEST, "policy": policy(), "as_of": as_of, "generation": generation,
            "available": False, "reason": reason, "count": None, "stocks": [], "calendar": None, "receipts": []}


def summarize(captures, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE, generation=None):
    try:
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        require(type(captures) in (tuple, list) and len(captures) == 22, "capture_set_incomplete")
        require(sum(len(c.body) for c in captures) <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
        previous, receipts = None, []
        for ordinal, c in enumerate(captures):
            receipt = checked_capture(c, ordinal, previous)
            previous = c.captured_at
            receipts.append({"original": receipt, "canonical": c.original_receipt_bytes.decode("utf-8"), "sha256": c.original_receipt_sha256})
        calendar = checked_calendar(captures)
        daily = [parse_daily(c) for c in captures[2:]]
        stocks = []
        for symbol in SYMBOLS:
            windows = {}
            for horizon in (5, 20):
                points = [d[symbol] for d in daily[-horizon:]]
                direction_counts = {category: sum(p["category"] == category for p in points) for category in CATEGORIES}
                require(sum(direction_counts.values()) == horizon, "direction_counts_reconciliation")
                windows[str(horizon)] = {"horizon": horizon, "points": points, "direction_counts": direction_counts,
                                         "investors": {i: window_stats(points, i) for i in INVESTORS}}
            stocks.append({"symbol": symbol, "name": NAMES[symbol], "exchange": "TPEx", "security_type": "stock", "currency": "TWD", "windows": windows})
        result = blank("", generation=generation) | {"available": True, "reason": None, "count": 7,
                                                     "stocks": stocks, "calendar": calendar, "receipts": receipts}
        require(graph_estimate((captures, result)) <= _POLICY["execution"]["max_retained_graph_estimate_bytes"], "retained_graph_estimate_limit")
        return result
    except (DirectionError, WindowEvidenceError, ValueError, TypeError, AttributeError, IndexError, KeyError) as exc:
        return blank(str(exc), generation=generation)


class Producer:
    def __init__(self, fetch, *, admitted_policy=None, version=POLICY_VERSION, pin=POLICY_DIGEST, profile=PROFILE):
        check_policy(policy() if admitted_policy is None else admitted_policy, version, pin, profile)
        self.fetch, self.generation = fetch, str(uuid.uuid4())
        self.attempted, self.request_count, self._captures = False, 0, ()
        self._result = blank("not_captured", generation=self.generation)
        self._lock = threading.Lock()

    def read(self, as_of=CUTOFF):
        if as_of != CUTOFF:
            return blank("cutoff_not_supported", as_of)
        with self._lock:
            return self.read_unlocked()

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
                    c = Captured(ordinal, url, response["body"], started, utcnow(), response["status"], response["content_type"], response["content_encoding"])
                    checked_capture(c, ordinal, captures[-1].captured_at if captures else None)
                    total += len(c.body)
                    require(total <= _POLICY["execution"]["max_total_bytes"], "capture_total_limit")
                    captures.append(c)
                    if ordinal < 2:
                        parse_index(c)
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
