"""Explicit joint predicate consumer; importing this module performs no I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import os
import re
from threading import Lock
from urllib.parse import parse_qsl, urlencode

VERSION = "price-saved-chips-focus-stock-scope-7/m1-v1"
POLICY_VERSION = "m1-saved-price-chips-focus-stock-scope-7-tpex-2026-10-06.1"
POLICY_DIGEST = "sha256:2f6d3a91337363e5700d7fdf6c16c63b8a14f45362d4407c8b73b01dabfe860e"
POLICY_BYTES = 17021
_POLICY = json.loads(r'''{"consumer_schema":"price-saved-chips-focus-stock-scope-7/m1-v1","independent_pins":{"institutional":{"api_schema":"institutional-windows/chips-1006-stock-scope-7-v1","calculation_version":"independent-net-sum/expected-session-inclusive-v1","calendar_schema":"tpex-observed-calendar/chips-1006-stock-scope-7-v1","calendar_version":"tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-stock-scope-7-v1","canonical_bytes":6742,"capture_schema":"tpex-institutional-memory-capture/chips-1006-stock-scope-7-v1","daily_source_id":"dataset-11856-dated-csv-observed-2026-10-07/chips-stock-scope-7-v1","index_source_id":"dataset-11391-month-csv-observed-2026-10-07/chips-stock-scope-7-v1","policy_version":"m1-chips-cutoff-stock-scope-7-tpex-2026-10-06.1","read_schema":"institutional-windows-read/chips-1006-stock-scope-7-v1","sha256":"b2f939100bd76de12bd974abb80f267596bf5a55f839271a5f4cc61409f9c220","summary_schema":"tpex-institutional-window-summary/chips-1006-stock-scope-7-v1","worker_schema":"tpex-institutional-window/chips-1006-stock-scope-7-v1"},"joint_entry":{"canonical_bytes":13404,"consumer_schema":"saved-price-chips-entry-stock-scope-7/m1-v1","policy_version":"m1-saved-price-chips-integration-stock-scope-7-tpex-2026-10-06.1","sha256":"8e55142cce367fd44d64ea9d6d9e756c1fdd5b091c928669bbe94de1df950de8"},"price_capture":{"canonical_bytes":1548,"memory_schema":"stock-price-memory/m2-stock-scope-v5","policy_version":"m2-stock-scope-tpex-11370-2026-10-06.5","sha256":"5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040","worker_schema":"tpex-price-capture/m2-stock-scope-v5"},"price_storage":{"canonical_bytes":2437,"policy_version":"m1-price-save-tpex-11370-2026-10-06.1","projection_schema":"stock-price-saved/m1-v1","receipt_schema":"tpex-price-storage-receipt/m1-v1","sha256":"0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e"},"saved_focus":{"canonical_bytes":2677,"policy_version":"m1-saved-price-focus-tpex-11370-2026-10-06.1","projection_schema":"price-saved-focus/m1-v1","sha256":"93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b"}},"institutional_use":{"attribution":"existing dataset11856/11391 OGL1.0 scope and TPEx terms section7 government data exception retained; no new metadata request","bounds":{"aggregate_body_bytes":44040192,"batch_cooperative_seconds":180,"capture_attempts":1,"daily_bytes":2097152,"disk_writes":0,"financial_get_requests":22,"index_bytes":1048576,"metadata_get_requests":0,"per_request_seconds":15,"producer_processes":1,"received_response_header_bytes":16384,"redirects":0,"retained_graph_estimate_bytes":67108864,"retries":0},"calendar_adoption":"validate all original monthly rows including 2026-10-07; adopt only exact 24 dates through 2026-10-06","closed_dates":["2026-09-25","2026-09-28"],"closure_notice":"11503027221","daily_base_url":"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php","daily_dates":["2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"daily_query_template":"l=zh-tw&se=EW&t=D&o=data&d=115%2FMM%2FDD","expected_calendar_dates":["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"five_day_dates":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"forbid":["preloaded","replay","fixture_as_actual","date_guess","legacy_retry","ordinary_price_fetch","history_or_PIT_claim","old_failed_producer_restart_or_clone","future_rows_after_observation_date"],"index_base_url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx","index_queries":["response=data&date=2026%2F09%2F01","response=data&date=2026%2F10%2F01"],"original_index_expected_dates":["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07"],"purposes":["local_fetch","raw_store","summarize"],"storage":"process_memory_only","use":"newly admitted ONE fresh 22-resource full-month-calendar seven-stock producer for explicit 2026-10-06 joint eight-condition operation; no prior capture replay","validation":["full body SHA256 and original canonical capture receipts/times for all 22 resources","six original Gregorian index fields/global widths/date uniqueness/25 validated original month rows and exact 24 adopted calendar","25 original daily fields/global widths/seven-digit ROC exact date/code uniqueness","22 canonical int64 fields/seven buy-sell-net relations/component total","140 selected daily rows/3500 original fields/3080 financial integers for all seven exact pinned identities","independent 5/20 expected inclusive session sums for all seven; all 42 investor/horizon net shares; no partial success"]},"limitations":["new independent seven-stock schemas/pins; old W8/calendar.2/default and old policy bytes immutable","original institutional executions before broker accounting corrections","no formalDB/purchase/accounts/trading","entire DAY-RANGE worktree/.range-ui-01a1106d excluded from ALL cleanup; private NO-RETRY fence persists","only one selected investor and one selected 5 or20 horizon lower-bound AND predicate, not ranking/strategy/backtest/trading or full M1/M2/M3","full monthly index validation through observed 2026-10-07; financial cutoff remains 2026-10-06; not ordinary stock close history"],"operation":"explicit eight RAW conditions -> explicit seven-identity retained saved-price validation -> trusted first institutional load in ONE NEW empty independently pinned seven-stock guarded producer -> all seven independently validated AND filters with exact signed int64 net threshold -> matching versus verified zero versus unavailable -> same-cutoff joint detail and full provenance -> return all eight original strings","predicate":{"detail_context":"exact as_of/from=price-saved-chips-focus-stock-scope-7/source_mode=private_saved plus focus_ prefixed all eight RAW inputs; cutoff equality required, unknown/duplicates rejected","excluded_price_symbols":[],"excluded_semantics":"all seven saved identities belong to the admitted joint universe; any missing or invalid identity/window makes the whole joint result unavailable, never zero","foreign_semantics":"official foreign and mainland investors excluding foreign dealers; existing source field mapping unchanged","horizons":["5","20"],"investors":["foreign","trust","dealer"],"joint_universe":["3105","3293","5274","5347","6488","6510","8069"],"minimum_net_lots":{"comparison":"selected independently verified window net shares >= signed threshold shares, inclusive exact integer comparison","conversion":"signed lot decimal scaled exactly by 1000 to canonical int64 shares; negative fractional -0.001 is valid; no float rounding","forbid":["plus","whitespace","comma","exponent","leading_zero","negative_zero"],"grammar":"-?(0|[1-9][0-9]*)([.][0-9]{1,3})?","max_raw_chars":21,"shares_max":"9223372036854775807","shares_min":"-9223372036854775808","zero":"0 and 0.000 allowed, RAW representation preserved"},"price_conditions":"exact existing min_lots AND day_move versus open AND min_turnover original int64 TWD AND min_range_pct inclusive aligned-integer range; old policies immutable","price_universe":["3105","3293","5274","5347","6488","6510","8069"],"result":"available count integer including zero only when ALL seven price identities and ALL seven institutional identities/full5+20/calendar/provenance validate BEFORE counting EVEN when price-only filter has zero matches; otherwise unavailable count null items empty","sort":"code_ascending"},"private_use":{"at_cap":true,"bounds":{"bundle_bytes":3170304,"capture_receipt_bytes":8192,"inherited_bundle_reads":35,"inherited_file_reads":105,"max_bundles":1,"max_files":3,"max_original_directories":3,"new_bundle_read_limit":29,"new_file_read_limit":87,"producer_new_snapshot_limit":26,"raw_bytes":3145728,"retained_graph_estimate_bytes":33554432,"root_new_snapshot_limit":3,"shared_bundle_read_limit":64,"shared_file_read_limit":192,"snapshot_cooperative_seconds":10,"storage_receipt_bytes":16384},"bundle":"tpex-11370-2026-10-06-m1-v1","cleanup":"prior automatic approval rejection before CreateProcess: strict NO-RETRY; no alternate tool/path/owner/file-by-file/rename/containing-tree bypass","files":[{"bytes":1788599,"mtime_ns":"1791329565505432100","name":"body.csv","sha256":"ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200"},{"bytes":1461,"mtime_ns":"1791329565507431000","name":"capture-receipt.json","sha256":"871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36"},{"bytes":1584,"mtime_ns":"1791329565509430100","name":"storage-receipt.json","sha256":"436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b"}],"forbid":["new_source_fetch","write","copy","export","publish","delete","new_disk_case","implicit_hydrate"],"purposes":["local_fetch","raw_store","summarize"],"root":"C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367","storage":"existing_private_disk_read_only_no_new_disk","use":"newly admitted finite read-only use of exact retained seven-stock bundle for the stock-scope-7 joint consumer; inherited 35 snapshots/105 logical files count against shared 64/192; producer max26 and ROOT reserve3","validation":["exact hard root and bundle/path lock","complete bytes SHA256 for all three files","canonical ORIGINAL capture/storage policy and receipts independent of augmented provenance","18 exact original price headers and global row widths","ROC1151006 and date/code uniqueness","all seven ordinary identities and original raw strings/int64 values","no partial success"]},"profile":"finite-explicit-saved-price-and-institutional-predicate-focus-stock-scope-7-v1","runtime_guards":{"diagnostics":"local ROOT-only read-only in-memory default receipt of pins/DB/stores/audit/quota/all22 body bytes+SHA/original receipt SHA/times/selected evidence <=8388608 bytes; per-capture chips/raw returns held original body+ORIGINAL canonical receipt <=3145728 response; no private full body in HTTP diagnostic, no fetch/snapshot/artifact/export; ROOT independent private disk observations counted in shared64_including_inherited35; new focus policy pin/eight-condition consumer counters/source readiness held only, no extra private reads","explicit_joint_opt_in":true,"failure":"any current private/chips/stock/provenance or joint consumer validation failure clears joint candidates/count and both detail numeric sources/chart/raw, one diagnostic and explicit read buttons retained, no fallback","failure_recovery":"same context/generation requires explicit NEW full private snapshot and explicit held institutional verification; joint consumer full successful revalidation does both, never external refetch; stale success cannot unmask; failedcapture no retry/restart","first_capture_requires":"successful explicit current new joint-focus seven-price validation before first institutional POST; server records readiness only from admitted successful consumer read, no source/private I/O at startup or after invalid conditions; UI token/generation and unchanged drafts prevent stale capture actions","focus_progress":"first explicit read can return validated saved-price readiness but no candidates/count before institutional evidence; all numeric result cards absent while incomplete or failed; explicit institutional load followed by explicitly authorized same-action joint consumer revalidation may read a NEW snapshot, all reads count shared quota","frontend_route":"/saved-price-chips-focus-stock-scope-7","identity_and_context":"VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7=m1-v1 and --saved-price-chips-focus-stock-scope-7-opt-in; mutually exclusive every old source/joint/focus flag; exact eight RAW inputs and 11-key detail context","joint_retained_graph_estimate_bytes":100663296,"network":"only during admitted chips request; exact22 method/URL and single-use gates before HTTP; TPEx443 DNS/connect only within that context; no other outbound/subprocess","old_live_source_opt_in":false,"post":"both API and preview independently allow only exact POST /api/stocks/TPEx/(3105|3293|5274|5347|6488|6510|8069)/institutional-windows/capture?as_of=2026-10-06; one query key once; nonempty wire body must parse to empty JSON object, whitespace allowed, <=4096 bytes; absent/null/array/scalar/keys/badJSON rejected422, oversized413; all other POST405 before router/upstream","requires":["serve","cutoff=2026-10-06","saved-source-only","all independent external policy version/digest pins","joint external policy version/digest pins","new independently external focus consumer policy version/digest pins"],"sensitive_get":{"body_bytes":0,"diagnostics":{"chips_raw":"/__price_validation/chips/raw: exactly one canonical decimal index=0..21; held only, no capture=404, response<=3145728 bytes","receipt":"/__price_validation/receipt: optional include_raw=false|true once; no capture/private snapshot"},"focus":{"optional_at_most_once":["day_move","min_turnover","min_range_pct"],"path":"/api/focus/price-saved","query_keys":["as_of","min_lots","day_move","min_turnover","min_range_pct"],"required_once":["as_of","min_lots"],"validation":"existing exact decimal/int64/default rules; valid unsupported dates unavailable/countnull/items[] before private I/O"},"joint_focus":{"body_bytes":0,"invalid":"unknown/duplicate/empty/invalid conditions422 before source/private I/O","path":"/api/focus/price-saved-chips-stock-scope-7","query_keys":["as_of","min_lots","day_move","min_turnover","min_range_pct","investor","horizon","min_net_lots"],"required_once":["as_of","min_lots","day_move","min_turnover","min_range_pct","investor","horizon","min_net_lots"],"unsupported":"valid dates other than2026-10-06 unavailable countnull items[] before private I/O"},"old_private_reader":"all /prices/saved405; sensitive suffix/wrong market/symbol cannot bypass scope","other_get":"read-only existing GET may remain only when no source load/private sensitive route bypass","stock":{"paths":["/api/stocks/TPEx/{seven}","/api/stocks/TPEx/{seven}/overview","/api/stocks/TPEx/{seven}/prices/saved-focus"],"query":"exactly one as_of=2026-10-06"},"unknown_or_duplicate_query":"reject422 before private/source I/O"},"startup":"no private data or metadata I/O before first explicit authorized saved snapshot; no automatic capture/read on entry/apply/back/held GET","stores":"fresh empty price/new chips/W8 Stores; finance seed rows zero; no formal DB"},"scope":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","identities":{"3105":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"穩懋","pit_membership":false,"security_type":"stock"},"3293":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"鈊象","pit_membership":false,"security_type":"stock"},"5274":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"信驊","pit_membership":false,"security_type":"stock"},"5347":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"世界","pit_membership":false,"security_type":"stock"},"6488":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"環球晶","pit_membership":false,"security_type":"stock"},"6510":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"精測","pit_membership":false,"security_type":"stock"},"8069":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","market":"TW","name":"元太","pit_membership":false,"security_type":"stock"}},"institutional_symbols":["3105","3293","5274","5347","6488","6510","8069"],"market":"TW","pit_membership":false,"saved_symbols":["3105","3293","5274","5347","6488","6510","8069"],"security_type":"stock"},"time_semantics":{"first_available":"unknown","institutional_capture":"ONE fresh stock-scope-7-v1 capture after explicit saved-read readiness; full original 22 capture receipts independently verified; no replay","limits":"deadlines are cooperative response/chunk or post-read checks, not OS preemption or hard wall; graph is retained estimate, not RSS/peak; received-header bound is not socket header preemption","point_in_time":"unsupported","price_captured_at":"2026-10-06T23:32:21.005311+00:00","price_saved_at":"2026-10-06T23:32:45.499432+00:00","price_started_at":"2026-10-06T23:32:17.666931+00:00","publication":"unknown","revision":"unknown"},"version":"m1-saved-price-chips-focus-stock-scope-7-tpex-2026-10-06.1"}''')
ENABLE_ENV = "STOCK_TPEX_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7"
VERSION_ENV = ENABLE_ENV + "_POLICY_VERSION"
DIGEST_ENV = ENABLE_ENV + "_POLICY_DIGEST"
JOINT_VERSION_ENV = ENABLE_ENV + "_JOINT_POLICY_VERSION"
JOINT_DIGEST_ENV = ENABLE_ENV + "_JOINT_POLICY_DIGEST"
CUTOFF = "2026-10-06"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
KEYS = ("as_of", "min_lots", "day_move", "min_turnover", "min_range_pct", "investor", "horizon", "min_net_lots")


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def focus_policy():
    return deepcopy(_POLICY)


def parse_net_lots(raw):
    if type(raw) is not str or len(raw) > 21 or not re.fullmatch(r"-?(0|[1-9][0-9]*)([.][0-9]{1,3})?", raw):
        raise ValueError("joint_focus_net_lots_invalid")
    integer, _, fraction = raw.lstrip("-").partition(".")
    value = int(integer) * 1000 + int(fraction.ljust(3, "0") or "0")
    if raw.startswith("-"):
        if value == 0:
            raise ValueError("joint_focus_negative_zero")
        value = -value
    if not -(2**63) <= value <= 2**63 - 1:
        raise ValueError("joint_focus_net_lots_out_of_range")
    return str(value)


def conditions(values):
    from .price_focus import parse_min_lots, parse_day_move, parse_min_turnover, parse_min_range_pct
    if set(values) != set(KEYS) or any(type(values[key]) is not str or not values[key] for key in KEYS):
        raise ValueError("joint_focus_eight_conditions_required")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", values["as_of"]):
        raise ValueError("joint_focus_date_invalid")
    date.fromisoformat(values["as_of"])
    parse_min_lots(values["min_lots"])
    parse_day_move(values["day_move"])
    parse_min_turnover(values["min_turnover"])
    parse_min_range_pct(values["min_range_pct"])
    if values["investor"] not in {"foreign", "trust", "dealer"} or values["horizon"] not in {"5", "20"}:
        raise ValueError("joint_focus_investor_or_horizon_invalid")
    return parse_net_lots(values["min_net_lots"])


def validate_admission(version, pin, independent):
    from . import saved_price_chips_scope7_entry as old
    if (version != POLICY_VERSION or pin != POLICY_DIGEST or len(canonical_bytes(_POLICY)) != POLICY_BYTES
            or "sha256:" + hashlib.sha256(canonical_bytes(_POLICY)).hexdigest() != POLICY_DIGEST):
        raise ValueError("joint_focus_external_policy_pin_mismatch")
    if set(independent) != set(_POLICY["independent_pins"]):
        raise ValueError("joint_focus_independent_pins_missing")
    expected = _POLICY["independent_pins"]["joint_entry"]
    encoded = canonical_bytes(old.entry_policy())
    if (independent["joint_entry"] != (expected["policy_version"], "sha256:" + expected["sha256"])
            or len(encoded) != expected["canonical_bytes"] or hashlib.sha256(encoded).hexdigest() != expected["sha256"]):
        raise ValueError("joint_focus_joint_entry_pin_mismatch")
    old.validate_admission(*independent["joint_entry"], {key: value for key, value in independent.items() if key != "joint_entry"})


def _gate(env):
    from . import price_saved_focus as price, tpex_price_saved as saved, tpex_price, institutional_windows_1006_scope7 as windows
    if env.get(ENABLE_ENV) != "1":
        return "joint_focus_not_enabled"
    pins = {"price_capture": (env.get(tpex_price.POLICY_VERSION_ENV), env.get(tpex_price.POLICY_DIGEST_ENV)),
            "price_storage": (env.get(saved.VERSION_ENV), env.get(saved.DIGEST_ENV)),
            "saved_focus": (env.get(price.VERSION_ENV), env.get(price.DIGEST_ENV)),
            "institutional": (env.get(windows.VERSION_ENV), env.get(windows.DIGEST_ENV)),
            "joint_entry": (env.get(JOINT_VERSION_ENV), env.get(JOINT_DIGEST_ENV))}
    try:
        validate_admission(env.get(VERSION_ENV), env.get(DIGEST_ENV), pins)
    except ValueError as error:
        return str(error)
    return None


class ConsumerState:
    def __init__(self):
        self._lock = Lock()
        self.reads = 0
        self.generation = 0
        self.price_ready = False
        self.last_conditions = None

    def begin(self):
        with self._lock:
            self.generation += 1
            self.reads += 1
            self.price_ready = False
            self.last_conditions = None
            return self.generation

    def current(self, ticket):
        with self._lock:
            return self.generation == ticket

    def observe(self, values=None, ready=False, ticket=None):
        with self._lock:
            if ticket is not None and ticket != self.generation:
                return False
            if ticket is None:
                self.generation += 1
            self.price_ready = ready
            self.last_conditions = dict(values) if ready else None
            return True

    def diagnostic(self):
        with self._lock:
            return {"version": VERSION, "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST,
                    "consumer_attempts": self.reads, "generation": self.generation, "price_ready": self.price_ready,
                    "last_conditions": deepcopy(self.last_conditions), "private_reads_by_diagnostic": 0}


STATE = ConsumerState()


def detail_path(symbol, values):
    return f"/stocks/TPEx/{symbol}?" + urlencode({"as_of": values["as_of"], "from": "price-saved-chips-focus-stock-scope-7",
        "source_mode": "private_saved", **{"focus_" + key: values[key] for key in KEYS}})


def _base(values):
    return {"version": VERSION, "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST,
            **values, "min_net_shares": parse_net_lots(values["min_net_lots"]), "status": "unavailable", "count": None,
            "items": [], "price": None, "institutional": [], "price_ready": False, "chips_ready": False,
            "capture_attempted": False, "can_capture": False, "reasons": [], "sort": "code_ascending",
            "supported_symbols": list(SYMBOLS), "excluded_price_symbols": _POLICY["predicate"]["excluded_price_symbols"],
            "historical_pit": "unsupported"}


def _full_chips(read, symbol):
    from worker import tpex_institutional_1006_scope7 as worker
    if (not isinstance(read, dict) or read.get("status") != "available" or read.get("symbol") != symbol
            or read.get("exchange") != "TPEx" or read.get("as_of") != CUTOFF
            or read.get("supported_scope") != worker.window_policy()["scope"]
            or read.get("schema_version") != "institutional-windows-read/chips-1006-stock-scope-7-v1"
            or read.get("version") != "institutional-windows/chips-1006-stock-scope-7-v1"
            or read.get("unit") != "shares" or read.get("quantity_encoding") != "canonical_integer_string"
            or read.get("policy", {}).get("version") != worker.POLICY_VERSION
            or read.get("policy", {}).get("digest") != worker.POLICY_DIGEST
            or read.get("calculation_version") != "independent-net-sum/expected-session-inclusive-v1"
            or read.get("calendar", {}).get("status") != "available"
            or read["calendar"].get("valid_dates") != [day.isoformat() for day in worker.EXPECTED_SESSIONS]
            or len(read.get("provenance", {}).get("captured_versions", [])) != 22):
        raise ValueError("joint_focus_full_chips_required")
    calendar = read["calendar"]
    originals = [day.isoformat() for day in worker.ORIGINAL_EXPECTED_SESSIONS]
    if (calendar.get("schema_version") != worker.CALENDAR_SCHEMA or calendar.get("version") != worker.CALENDAR_VERSION
            or calendar.get("observation_date") != worker.OBSERVATION_DATE.isoformat()
            or calendar.get("original_expected_dates") != originals or calendar.get("original_valid_dates") != originals
            or calendar.get("post_cutoff_dates") != ["2026-10-07"] or calendar.get("missing_dates") != []
            or len(calendar.get("original_rows", [])) != 25 or len(calendar.get("rows", [])) != 24
            or calendar["rows"] != calendar["original_rows"][:24]):
        raise ValueError("joint_focus_full_original_calendar_required")
    captured = read["provenance"]["captured_versions"]
    requests = [(worker.INDEX_SOURCE_ID, day) for day in worker.MONTH_REQUESTS] + [(worker.DAILY_SOURCE_ID, day) for day in worker.DAILY_REQUESTS]
    def receipt_valid(receipt, source, day):
        if (receipt.get("schema_version") != worker.CAPTURE_SCHEMA or receipt.get("source_id") != source
                or receipt.get("requested_date") != day.isoformat() or receipt.get("url") != worker.source_url(source, day)
                or receipt.get("method") != "GET" or receipt.get("policy_version") != worker.POLICY_VERSION
                or receipt.get("policy_digest") != worker.POLICY_DIGEST or receipt.get("profile") != worker.PROFILE
                or receipt.get("source_version") != worker.window_policy()["sources"][source]["source_version"]
                or not re.fullmatch("[0-9a-f]{64}", receipt.get("body_sha256", ""))
                or type(receipt.get("body_bytes")) is not int or not 0 < receipt["body_bytes"] <= (
                    worker.MAX_INDEX_BYTES if source == worker.INDEX_SOURCE_ID else worker.MAX_DAILY_BYTES)):
            raise ValueError("joint_focus_original_receipt_invalid")
    for receipt, (source, day) in zip(captured, requests):
        receipt_valid(receipt, source, day)
    evidence = calendar.get("evidence", [])
    if len(evidence) != 2:
        raise ValueError("joint_focus_calendar_receipts_required")
    original_keys = set(captured[0])
    for index, receipt in enumerate(evidence):
        if ({key: receipt.get(key) for key in original_keys} != captured[index]
                or receipt.get("candidate_count") != (20, 5)[index] or receipt.get("adopted_count") != (20, 4)[index]
                or receipt.get("post_cutoff_row_count") != (0, 1)[index]
                or receipt.get("validation_scope") != "all_returned_month_rows_including_valid_post_cutoff_rows"):
            raise ValueError("joint_focus_calendar_receipt_mismatch")
    for row, expected in zip(calendar["original_rows"], originals):
        fields = row.get("source_values", {})
        month = 0 if expected.startswith("2026-09") else 1
        if (row.get("date") != expected or set(fields) != set(worker.INDEX_HEADER)
                or fields[worker.INDEX_HEADER[0]] != expected.replace("-", "")
                or row.get("body_sha256") != captured[month]["body_sha256"]
                or type(row.get("row_ordinal")) is not int or not 1 <= row["row_ordinal"] <= (20, 5)[month]):
            raise ValueError("joint_focus_original_calendar_row_invalid")
        opening, high, low, close = (worker._decimal(fields[key], positive=True) for key in worker.INDEX_HEADER[1:5])
        worker._decimal(fields[worker.INDEX_HEADER[5]], positive=False)
        if not low <= min(opening, close) <= max(opening, close) <= high:
            raise ValueError("joint_focus_original_calendar_ohlc_invalid")
    for horizon in (5, 20):
        window = read.get("windows", {}).get(str(horizon), {})
        expected = [day.isoformat() for day in worker.DAILY_REQUESTS[-horizon:]]
        if (window.get("status") != "available" or window.get("required_dates") != expected
                or window.get("valid_dates") != expected or window.get("missing_dates") != []
                or window.get("invalid_dates") != [] or len(window.get("daily_evidence", [])) != horizon):
            raise ValueError("joint_focus_full_window_required")
        sums = {investor: 0 for investor in ("foreign", "trust", "dealer")}
        for evidence, day in zip(window["daily_evidence"], expected):
            row = evidence["row"]
            if (row["date"] != day or row["symbol"] != symbol
                    or row.get("company_name", "").strip() != worker.IDENTITIES[symbol]["name"]):
                raise ValueError("joint_focus_daily_identity_mismatch")
            raw = row.get("source_values", {})
            if (set(raw) != set(worker.DAILY_HEADER) or any(type(value) is not str for value in raw.values())
                    or raw[worker.DAILY_HEADER[1]] != symbol
                    or raw[worker.DAILY_HEADER[2]].strip() != worker.IDENTITIES[symbol]["name"]
                    or worker._market_date(raw[worker.DAILY_HEADER[0]], roc=True).isoformat() != day):
                raise ValueError("joint_focus_daily_original_fields_required")
            parsed = worker._financial_row([raw[key] for key in worker.DAILY_HEADER], row["row_ordinal"])
            if {**parsed, "source_values": raw} != row:
                raise ValueError("joint_focus_daily_original_relation_mismatch")
            original = captured[2 + worker.DAILY_REQUESTS.index(date.fromisoformat(day))]
            receipt = evidence["provenance"]
            if ({key: receipt.get(key) for key in original} != original
                    or receipt.get("selected_count") != 7
                    or receipt.get("validation_scope") != "all_row_structure_dates_unique_codes_names; selected_seven_exact_pinned_names_all_22_financial_fields"):
                raise ValueError("joint_focus_daily_receipt_mismatch")
            for investor in sums:
                item = row["investors"][investor]
                for field in ("buy", "sell", "net"):
                    raw = item[field]
                    if type(raw) is not str or not re.fullmatch(r"0|-?[1-9][0-9]*", raw) or not -(2**63) <= int(raw) <= 2**63-1:
                        raise ValueError("joint_focus_daily_integer_invalid")
                if int(item["buy"]) - int(item["sell"]) != int(item["net"]):
                    raise ValueError("joint_focus_daily_relation_invalid")
                sums[investor] += int(item["net"])
        if (any(not -(2**63) <= value <= 2**63-1 for value in sums.values())
                or window.get("values") != {key: str(value) for key, value in sums.items()}):
            raise ValueError("joint_focus_net_sum_mismatch")
    return read


def project(price, institutional, values):
    from . import price_saved_focus as saved
    conditions(values)
    result = _base(values)
    if price.get("status") != "available" or not price.get("consumer_provenance"):
        raise ValueError("joint_focus_full_price_required")
    checked = saved.derive_focus(price["reads"], saved._base(date.fromisoformat(values["as_of"]), values["min_lots"],
        values["day_move"], values["min_turnover"], values["min_range_pct"]))
    proof = price["consumer_provenance"]
    if (proof.get("policy_version") != saved.POLICY_VERSION or proof.get("policy_digest") != saved.POLICY_DIGEST
            or proof.get("projection_version") != saved.VERSION):
        raise ValueError("joint_focus_price_proof_invalid")
    if len(institutional) != 7:
        raise ValueError("joint_focus_seven_chips_required")
    chips = [_full_chips(read, symbol) for read, symbol in zip(institutional, SYMBOLS)]
    if any(read["calendar"] != chips[0]["calendar"] or read["provenance"] != chips[0]["provenance"] for read in chips[1:]):
        raise ValueError("joint_focus_chips_source_mismatch")
    minimum = int(result["min_net_shares"])
    items = []
    for item in checked["items"]:
        if item["symbol"] not in SYMBOLS:
            continue
        read = chips[SYMBOLS.index(item["symbol"])]
        net = read["windows"][values["horizon"]]["values"][values["investor"]]
        if int(net) >= minimum:
            items.append({**item, "investor": values["investor"], "horizon": values["horizon"],
                "net_shares": net, "min_net_lots": values["min_net_lots"], "min_net_shares": str(minimum),
                "reasons": item["reasons"] + ["selected_net_at_least_min_net_lots"], "detail_url": detail_path(item["symbol"], values)})
    result.update(status="available", count=len(items), items=items, price=price, institutional=chips,
                  price_ready=True, chips_ready=True, capture_attempted=True, can_capture=False)
    from worker.tpex_institutional_1006_scope7 import retained_graph_estimate
    if retained_graph_estimate(result) + proof.get("retained_graph_estimated_bytes", 0) > 100663296:
        raise ValueError("joint_focus_retained_graph_bound")
    return result


def build_focus(instruments, values, *, environment=None):
    from . import price_saved_focus as price, institutional_windows_1006_scope7 as windows
    conditions(values)
    ticket = STATE.begin()
    result = _base(values)
    env = os.environ if environment is None else environment
    reason = _gate(env)
    if values["as_of"] != CUTOFF:
        reason = "joint_focus_cutoff_not_supported"
    if reason:
        result["reasons"] = [reason]
        return result
    saved = price.build_saved_focus(instruments, date.fromisoformat(CUTOFF), *(values[key] for key in KEYS[1:5]), environment=env)
    if saved["status"] != "available":
        result["reasons"] = saved["reasons"] or ["joint_focus_saved_source_invalid"]
        return result
    if not STATE.observe(values, True, ticket):
        result["reasons"] = ["joint_focus_stale_consumer"]
        return result
    held = [windows.STORE.read("TPEx", symbol, date.fromisoformat(CUTOFF), environment=env) for symbol in SYMBOLS]
    attempted = any(read.get("capture_state", {}).get("attempted") for read in held)
    result.update(price_ready=True, capture_attempted=attempted, can_capture=not attempted)
    if not attempted:
        result["reasons"] = ["joint_focus_institutional_not_loaded"]
        return result
    try:
        projected = project(saved, held, values)
        if not STATE.current(ticket):
            result.update(price_ready=False, chips_ready=False, can_capture=False, reasons=["joint_focus_stale_consumer"])
            return result
        return projected
    except (ValueError, KeyError, TypeError, AttributeError):
        STATE.observe(ticket=ticket)
        result.update(price_ready=False, chips_ready=False, can_capture=False, reasons=["joint_focus_joint_evidence_invalid"])
        return result


def request_error(method, path, query, body):
    from . import saved_price_chips_scope7_entry as old
    if path == "/api/focus/price-saved-chips-stock-scope-7":
        if method != "GET":
            return 405, "joint_focus_method_outside_scope"
        if body:
            return 422, "joint_focus_get_body_forbidden"
        try:
            pairs = parse_qsl(query, keep_blank_values=True, encoding="utf-8", errors="strict")
            if len(pairs) != 8 or len(dict(pairs)) != 8:
                raise ValueError("joint_focus_exact_eight_query_required")
            conditions(dict(pairs))
            return None
        except (ValueError, TypeError, UnicodeError):
            return 422, "joint_focus_conditions_invalid"
    if path.startswith("/api/focus/price-saved-chips"):
        return 405, "joint_focus_other_consumer_outside_scope"
    if path == "/api/focus/price-saved":
        return 405, "use_the_new_joint_focus_consumer"
    refused = old.request_error(method, path, query, body)
    if refused:
        return refused
    if method == "POST":
        from .institutional_windows_1006_scope7 import STORE
        if STORE._attempted:
            return 409, "joint_focus_capture_already_attempted"
    if method == "POST" and not STATE.price_ready:
        return 409, "joint_focus_explicit_price_validation_required"
    return None


def install_request_gate(app):
    from starlette.responses import JSONResponse
    @app.middleware("http")
    async def scope(request, call_next):
        limit = 4096 if request.method == "POST" else 0
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                STATE.observe()
                return JSONResponse({"detail": "joint_focus_body_bound"}, status_code=413 if limit else 422)
            chunks.append(chunk)
        request._body = body = b"".join(chunks)
        error = request_error(request.method, request.url.path, request.url.query, body)
        if error:
            STATE.observe()
            return JSONResponse({"detail": error[1]}, status_code=error[0])
        return await call_next(request)
