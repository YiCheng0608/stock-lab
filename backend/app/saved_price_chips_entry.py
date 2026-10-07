"""Pinned, import-safe joint entry; request admission precedes source/private I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from urllib.parse import parse_qsl

VERSION = "saved-price-chips-entry/m1-v1"
POLICY_VERSION = "m1-saved-price-chips-integration-tpex-2026-10-06.1"
POLICY_DIGEST = "sha256:a5e6ecda19952e4f6dc44ad9660e4cbbcc2e4a0a3670229ab63900cf74678d14"
POLICY_BYTES = 10702
PRODUCER_READ_LIMIT = 61
ROOT_OBSERVATION_RESERVE = 3
MAX_POST_BYTES = 4096
MAX_RAW_RESPONSE_BYTES = 3145728
MAX_RECEIPT_BYTES = 8388608
_POLICY = json.loads(r'''{"consumer_schema":"saved-price-chips-entry/m1-v1","independent_pins":{"institutional":{"api_schema":"institutional-windows/chips-1006-v1","calculation_version":"independent-net-sum/expected-session-inclusive-v1","calendar_schema":"tpex-observed-calendar/chips-1006-v1","calendar_version":"tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1","canonical_bytes":4264,"capture_schema":"tpex-institutional-memory-capture/chips-1006-v1","daily_source_id":"dataset-11856-dated-csv-observed-2026-10-07/chips-v1","index_source_id":"dataset-11391-month-csv-observed-2026-10-07/chips-v1","policy_version":"m1-chips-cutoff-tpex-2026-10-06.1","read_schema":"institutional-windows-read/chips-1006-v1","sha256":"36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5","summary_schema":"tpex-institutional-window-summary/chips-1006-v1","worker_schema":"tpex-institutional-window/chips-1006-v1"},"price_capture":{"canonical_bytes":1548,"memory_schema":"stock-price-memory/m2-stock-scope-v5","policy_version":"m2-stock-scope-tpex-11370-2026-10-06.5","sha256":"5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040","worker_schema":"tpex-price-capture/m2-stock-scope-v5"},"price_storage":{"canonical_bytes":2437,"policy_version":"m1-price-save-tpex-11370-2026-10-06.1","projection_schema":"stock-price-saved/m1-v1","receipt_schema":"tpex-price-storage-receipt/m1-v1","sha256":"0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e"},"saved_focus":{"canonical_bytes":2677,"policy_version":"m1-saved-price-focus-tpex-11370-2026-10-06.1","projection_schema":"price-saved-focus/m1-v1","sha256":"93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b"}},"institutional_use":{"attribution":"existing dataset11856/11391 OGL1.0 scope and TPEx terms section7 government data exception retained; no new metadata request","bounds":{"aggregate_body_bytes":44040192,"batch_cooperative_seconds":180,"capture_attempts":1,"daily_bytes":2097152,"disk_writes":0,"financial_get_requests":22,"index_bytes":1048576,"metadata_get_requests":0,"per_request_seconds":15,"producer_processes":1,"received_response_header_bytes":16384,"redirects":0,"retained_graph_estimate_bytes":67108864,"retries":0},"closed_dates":["2026-09-25","2026-09-28"],"closure_notice":"11503027221","daily_base_url":"https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php","daily_dates":["2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"daily_query_template":"l=zh-tw&se=EW&t=D&o=data&d=115%2FMM%2FDD","expected_calendar_dates":["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09","2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18","2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"five_day_dates":["2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06"],"forbid":["preloaded","replay","fixture_as_actual","date_guess","legacy_retry","ordinary_price_fetch","history_or_PIT_claim"],"index_base_url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx","index_queries":["response=data&date=2026%2F09%2F01","response=data&date=2026%2F10%2F01"],"purposes":["local_fetch","raw_store","summarize"],"storage":"process_memory_only","use":"necessary new bounded fresh source acquisition for first joint institutional load","validation":["full body SHA256 and original canonical capture receipts/times for all 22 resources","six original Gregorian index fields/global widths/date uniqueness/exact 24 observed calendar","25 original daily fields/global widths/seven-digit ROC exact date/code uniqueness","22 canonical int64 fields/seven buy-sell-net relations/component total","40 selected daily rows/1000 original fields/880 financial integers for both identities","independent 5/20 expected inclusive session sums"]},"limitations":["existing independent schemas/pins, oldW8/calendar/default unchanged","original institutional executions before broker accounting corrections","no formalDB/purchase/accounts/trading","entire DAY-RANGE worktree/.range-ui-01a1106d excluded from ALL cleanup; private NO-RETRY fence persists"],"operation":"saved-focus -> explicit 2026-10-06 TPEx3105/6488 detail -> trusted first institutional capture -> saved OHLC and independently summed 5/20 day nets in one new guarded producer -> switch identity/raw provenance -> return identical five original condition strings","private_use":{"at_cap":true,"bounds":{"bundle_bytes":3170304,"capture_receipt_bytes":8192,"max_bundles":1,"max_files":3,"max_original_directories":3,"raw_bytes":3145728,"retained_graph_estimate_bytes":33554432,"shared_bundle_read_limit":64,"shared_file_read_limit":192,"snapshot_cooperative_seconds":10,"storage_receipt_bytes":16384},"bundle":"tpex-11370-2026-10-06-m1-v1","cleanup":"prior automatic approval rejection before CreateProcess: strict NO-RETRY; no alternate tool/path/owner/file-by-file/rename/containing-tree bypass","files":[{"bytes":1788599,"mtime_ns":"1791329565505432100","name":"body.csv","sha256":"ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200"},{"bytes":1461,"mtime_ns":"1791329565507431000","name":"capture-receipt.json","sha256":"871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36"},{"bytes":1584,"mtime_ns":"1791329565509430100","name":"storage-receipt.json","sha256":"436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b"}],"forbid":["new_source_fetch","write","copy","export","publish","delete","new_disk_case","implicit_hydrate"],"purposes":["local_fetch","raw_store","summarize"],"root":"C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367","storage":"existing_private_disk_read_only_no_new_disk","use":"necessary derived read-only joint consumer of existing retained bundle","validation":["exact hard root and bundle/path lock","complete bytes SHA256 for all three files","canonical ORIGINAL capture/storage policy and receipts independent of augmented provenance","18 exact original price headers and global row widths","ROC1151006 and date/code uniqueness","all seven ordinary identities and original raw strings/int64 values","no partial success"]},"profile":"finite-explicit-saved-focus-and-institutional-joint-entry","runtime_guards":{"diagnostics":"local ROOT-only read-only in-memory default receipt of pins/DB/stores/audit/quota/all22 body bytes+SHA/original receipt SHA/times/selected evidence <=8388608 bytes; per-capture chips/raw returns held original body+ORIGINAL canonical receipt <=3145728 response; no private full body in HTTP diagnostic, no fetch/snapshot/artifact/export; ROOT independent private disk observations counted in shared64","explicit_joint_opt_in":true,"failure":"current private read/chips capture/stock read or refetch/provenance validation failure masks both sources prices/chart/raw and institutional nets/calendar/daily raw; one diagnostic retained; no fallback; explicit successful revalidation required","failure_recovery":"same current context/generation requires two successful revalidations after failure: explicit new private snapshot plus explicit held institutional read/refetch; held means no external refetch; failed capture attempt has no retry/restart, absent valid held capture stays unavailable; previous generation success cannot unmask","identity_and_context":"new UI compile flag checks exact saved-focus detail context and five original strings before sensitive actions; other five saved identities cannot capture chips","joint_retained_graph_estimate_bytes":100663296,"network":"only during admitted chips request; exact22 method/URL and single-use gates before HTTP; TPEx443 DNS/connect only within that context; no other outbound/subprocess","old_live_source_opt_in":false,"post":"both API and preview independently allow only exact POST /api/stocks/TPEx/(3105|6488)/institutional-windows/capture?as_of=2026-10-06; one query key once; nonempty wire body must parse to empty JSON object, whitespace allowed, <=4096 bytes; absent/null/array/scalar/keys/badJSON rejected422, oversized413; all other POST405 before router/upstream","requires":["serve","cutoff=2026-10-06","saved-source-only","all independent external policy version/digest pins","joint external policy version/digest pins"],"sensitive_get":{"body_bytes":0,"diagnostics":{"chips_raw":"/__price_validation/chips/raw: exactly one canonical decimal index=0..21; held only, no capture=404, response<=3145728 bytes","receipt":"/__price_validation/receipt: optional include_raw=false|true once; no capture/private snapshot"},"focus":{"optional_at_most_once":["day_move","min_turnover","min_range_pct"],"path":"/api/focus/price-saved","query_keys":["as_of","min_lots","day_move","min_turnover","min_range_pct"],"required_once":["as_of","min_lots"],"validation":"existing exact decimal/int64/default rules; valid unsupported dates unavailable/countnull/items[] before private I/O"},"old_private_reader":"all /prices/saved405; sensitive suffix/wrong market/symbol cannot bypass scope","other_get":"read-only existing GET may remain only when no source load/private sensitive route bypass","stock":{"paths":["/api/stocks/TPEx/{seven}","/api/stocks/TPEx/{seven}/overview","/api/stocks/TPEx/{seven}/prices/saved-focus"],"query":"exactly one as_of=2026-10-06"},"unknown_or_duplicate_query":"reject422 before private/source I/O"},"startup":"no private data or metadata I/O before first explicit authorized saved snapshot; no automatic capture/read on entry/apply/back/held GET","stores":"fresh empty price/new chips/W8 Stores; finance seed rows zero; no formal DB"},"scope":{"as_of":"2026-10-06","currency":"TWD","exchange":"TPEx","institutional_symbols":["3105","6488"],"market":"TW","pit_membership":false,"saved_symbols":["3105","3293","5274","5347","6488","6510","8069"],"security_type":"stock"},"time_semantics":{"first_available":"unknown","institutional_capture":"new current request timestamps independently retained","limits":"deadlines are cooperative response/chunk or post-read checks, not OS preemption or hard wall; graph is retained estimate, not RSS/peak; received-header bound is not socket header preemption","point_in_time":"unsupported","price_captured_at":"2026-10-06T23:32:21.005311+00:00","price_saved_at":"2026-10-06T23:32:45.499432+00:00","price_started_at":"2026-10-06T23:32:17.666931+00:00","publication":"unknown","revision":"unknown"},"version":"m1-saved-price-chips-integration-tpex-2026-10-06.1"}''')
SAVED_SYMBOLS = tuple(_POLICY["scope"]["saved_symbols"])
CHIPS_SYMBOLS = tuple(_POLICY["scope"]["institutional_symbols"])
CUTOFF = _POLICY["scope"]["as_of"]


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def entry_policy():
    return deepcopy(_POLICY)


def validate_admission(version, pin, independent):
    """Every external pin must independently match the immutable source policy."""
    if (version != POLICY_VERSION or pin != POLICY_DIGEST or len(canonical_bytes(_POLICY)) != POLICY_BYTES
            or "sha256:" + hashlib.sha256(canonical_bytes(_POLICY)).hexdigest() != POLICY_DIGEST):
        raise ValueError("joint_external_policy_pin_mismatch")
    if set(independent) != set(_POLICY["independent_pins"]):
        raise ValueError("joint_independent_policy_pins_missing")
    from app import price_saved_focus as focus
    from worker import tpex_price_capture as price, tpex_price_storage as storage, tpex_institutional_1006 as chips
    policies = {"price_capture": price.price_policy(date.fromisoformat(CUTOFF), policy_version=independent["price_capture"][0]),
                "price_storage": storage.storage_policy(), "saved_focus": focus.focus_policy(), "institutional": chips.window_policy()}
    for name, expected in _POLICY["independent_pins"].items():
        encoded = canonical_bytes(policies[name])
        if (independent[name] != (expected["policy_version"], "sha256:" + expected["sha256"])
                or len(encoded) != expected["canonical_bytes"]
                or hashlib.sha256(encoded).hexdigest() != expected["sha256"]):
            raise ValueError("joint_independent_policy_pin_mismatch:" + name)


def source_urls():
    from worker import tpex_institutional_1006 as chips
    return tuple(chips.source_url(chips.INDEX_SOURCE_ID, day) for day in chips.MONTH_REQUESTS) + tuple(
        chips.source_url(chips.DAILY_SOURCE_ID, day) for day in chips.DAILY_REQUESTS)


def static_request_error(method, path):
    if path.endswith("/prices/saved"):
        return 405, "use_the_admitted_saved_focus_reader"
    if method == "POST" and not re.fullmatch(r"/api/stocks/TPEx/(3105|6488)/institutional-windows/capture", path):
        return 405, "joint_post_outside_scope"
    if method not in {"GET", "POST", "OPTIONS"}:
        return 405, "joint_method_outside_scope"
    return None


def request_error(method, path, query, body):
    """Return an HTTP refusal, or None; no source/private reads happen here."""
    if type(body) is not bytes:
        return 422, "joint_request_body_invalid"
    refused = static_request_error(method, path)
    if refused:
        return refused
    try:
        pairs = parse_qsl(query, keep_blank_values=True, encoding="utf-8", errors="strict")
    except UnicodeError:
        return 422, "joint_request_conditions_invalid"
    def params(allowed, required=()):
        if any(key not in allowed for key, _ in pairs) or any(sum(key == item for item, _ in pairs) > 1 for key in allowed):
            raise ValueError("joint_unknown_or_duplicate_query")
        values = dict(pairs)
        if any(key not in values for key in required):
            raise ValueError("joint_required_query_missing")
        return values
    try:
        if path.endswith("/prices/saved"):
            return 405, "use_the_admitted_saved_focus_reader"
        if method == "POST":
            if not re.fullmatch(r"/api/stocks/TPEx/(3105|6488)/institutional-windows/capture", path):
                return 405, "joint_post_outside_scope"
            if params(("as_of",), ("as_of",))["as_of"] != CUTOFF:
                return 422, "joint_cutoff_not_supported"
            if len(body) > MAX_POST_BYTES:
                return 413, "joint_request_body_bound"
            value = json.loads(body.decode("utf-8", errors="strict")) if body else None
            if type(value) is not dict or value:
                return 422, "joint_empty_json_object_required"
            return None
        if method not in {"GET", "OPTIONS"}:
            return 405, "joint_method_outside_scope"
        if body:
            return 422, "joint_get_body_forbidden"
        if method == "OPTIONS":
            return None
        if path == "/api/focus/price-saved":
            values = params(("as_of", "min_lots", "day_move", "min_turnover", "min_range_pct"), ("as_of", "min_lots"))
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", values["as_of"]):
                raise ValueError("joint_focus_date_invalid")
            date.fromisoformat(values["as_of"])
            from app.price_focus import parse_min_lots, parse_day_move, parse_min_turnover, parse_min_range_pct
            parse_min_lots(values["min_lots"])
            parse_day_move(values.get("day_move", "all"))
            parse_min_turnover(values.get("min_turnover", "0"))
            parse_min_range_pct(values.get("min_range_pct", "0"))
            return None  # Valid unsupported dates retain unavailable/count-null before private I/O.
        stock = re.fullmatch(r"/api/stocks/([^/]+)/([^/]+)(/(overview|prices/saved-focus))?", path)
        if stock:
            if stock[1] != "TPEx" or stock[2] not in SAVED_SYMBOLS:
                return 405, "joint_stock_outside_scope"
            if params(("as_of",), ("as_of",))["as_of"] != CUTOFF:
                return 422, "joint_cutoff_not_supported"
            return None
        if "/prices/saved-focus" in path or "/prices/saved" in path:
            return 405, "joint_sensitive_path_outside_scope"
        if path == "/__price_validation/receipt":
            values = params(("include_raw",))
            if values.get("include_raw", "false") not in {"false", "true"}:
                return 422, "joint_diagnostic_query_invalid"
        elif path == "/__price_validation/chips/raw":
            if not re.fullmatch(r"(0|[1-9]|1[0-9]|2[01])", params(("index",), ("index",))["index"]):
                return 422, "joint_raw_index_invalid"
        return None
    except (ValueError, TypeError, UnicodeError):
        return 422, "joint_request_conditions_invalid"


def install_request_gate(app):
    from starlette.responses import JSONResponse
    @app.middleware("http")
    async def joint_scope(request, call_next):
        refused = static_request_error(request.method, request.url.path)
        if refused:
            return JSONResponse({"detail": refused[1]}, status_code=refused[0])
        limit = MAX_POST_BYTES if request.method == "POST" else 0
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return JSONResponse({"detail": "joint_request_body_bound" if limit else "joint_get_body_forbidden"},
                                    status_code=413 if limit else 422)
            chunks.append(chunk)
        body = b"".join(chunks)
        request._body = body  # Starlette's cached request replays only this bounded body.
        try:
            error = request_error(request.method, request.url.path, request.url.query, body)
        except UnicodeError:
            error = 422, "joint_request_conditions_invalid"
        if error:
            return JSONResponse({"detail": error[1]}, status_code=error[0])
        return await call_next(request)


def held_diagnostic(store):
    """Snapshot validation and original receipts only; never loads or opens private files."""
    from worker import tpex_institutional_1006 as chips
    reads = {symbol: store.read("TPEx", symbol, date.fromisoformat(CUTOFF)) for symbol in CHIPS_SYMBOLS}
    captures = store.raw_captures
    original = []
    for ordinal, item in enumerate(captures):
        receipt = item.receipt()
        encoded = canonical_bytes(receipt)
        original.append({"index": ordinal, "receipt": receipt, "original_receipt_sha256": hashlib.sha256(encoded).hexdigest()})
    estimate = chips.retained_graph_estimate((captures, reads))
    if estimate > _POLICY["institutional_use"]["bounds"]["retained_graph_estimate_bytes"]:
        raise ValueError("joint_chips_retained_graph_bound")
    return {"schema_version": VERSION, "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST,
            "independent_pins": deepcopy(_POLICY["independent_pins"]), "institutional": reads,
            "original_captures": original, "chips_retained_graph_estimated_bytes": estimate,
            "private_retained_graph_estimate_limit": 33554432, "joint_retained_graph_estimate_limit": 100663296,
            "estimate_semantics": "retained_graph_estimate_not_RSS_or_peak", "root_shared_bundle_limit": 64,
            "root_shared_file_limit": 192, "root_observation_reserve": ROOT_OBSERVATION_RESERVE,
            "producer_snapshot_ceiling": PRODUCER_READ_LIMIT}


def held_raw(store, index):
    import base64
    captures = store.raw_captures
    if not 0 <= index < len(captures):
        return None
    from worker import tpex_institutional_1006 as chips
    item = captures[index]
    chips._checked_capture(item)
    original = canonical_bytes(item.receipt())
    result = {"schema_version": VERSION, "index": index, "body_base64": base64.b64encode(item.body).decode("ascii"),
              "original_receipt_base64": base64.b64encode(original).decode("ascii"),
              "body_sha256": hashlib.sha256(item.body).hexdigest(), "original_receipt_sha256": hashlib.sha256(original).hexdigest(),
              "origin": "held_process_memory", "source_requests": 0}
    if len(canonical_bytes(result)) > MAX_RAW_RESPONSE_BYTES:
        raise ValueError("joint_raw_response_bound")
    return result
