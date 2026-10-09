"""Issue33 standalone, bounded, nominal TAIEX observation adapter (stdlib only).

No network or filesystem action occurs at import or construction. Real acquisition
requires the externally fetched 4096-byte policy and a separately reviewed external
financial-start seal. This module does not fetch that control-plane authorization.

Seal v1 has exact keys shown by SEAL_FIELDS. It binds candidate SHA, module/script/
loader/command hashes, actual independent top-level QA identity, owner, canonical
policy, use, URLs, cutoffs, consumer, caps, command argv and UTC validity. These are
the predeclared format, not an authorization or an actual financial-start seal.

OracleHooks callbacks independently parse the ENTIRE original bytearray and return
the entire normalized row list (all columns), not a boolean or sampled anchors.
They must put all retained copies/aliases in hooks.owner, including declared native
StringIO backing text. Original observer runs after EOF/hash and before parsing.

Exported price results are revocable handles. Inspect them only with visit(callback,
RootOwner); that owner declares every retained alias/copy. Supported source roots
are traversable, estimated with bounded work and cleared on release. Immutable
copies are dereferenced, not physically wiped; this is not an RSS/peak guarantee.
Every public result-operation failure, including pending use, terminally releases
the source even if caught inside a with block. Pending-negative tests therefore
need a distinct boundary source; the real positive source must use fresh external
objects and default real clocks. Both attempted wire intervals share cumulative20s.
Arbitrary Python callbacks are trusted to declare their roots; this is a cooperative
in-process lifecycle contract, not a sandbox against malicious Python introspection.
The caller must clear its own exception graph and exit the RAM-only QA process.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import http.client
import io
import json
import re
import ssl
import sys
import time
from urllib.parse import urlsplit


POLICY_PIN = "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-6085684135"
POLICY_SHA256 = "4b1f44b0e77950bcd12896f5e54f99c6262365fcf4965b4938420edb58e54eca"
NAMESPACE = "issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa1"
CONSUMER = "taiex-nominal-price-index-window-summary-v1"
SUPPORTED_USE = "local_personal_noncommercial_process_ram_nominal_observation_snapshot"
URLS = (
    "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=open_data",
    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX&start_date=2026-09-03&end_date=2026-10-06",
)
CAP_FIELDS = {"max_requests", "body_bytes", "total_raw_bytes", "declared_roots_estimate_bytes", "request_seconds", "batch_seconds", "redirects", "retries", "artifact_bytes"}
POLICY_FIELDS = {
    "schema", "issue", "namespace", "version", "symbol", "cutoffs", "observed_dates",
    "windows", "calendar_basis", "price_basis", "unit", "unit_kind", "provider_literal_unit",
    "scale", "consumer", "formula", "ratio_representation", "observation_count",
    "interval_count", "urls", "official_schema", "official_date_grammar",
    "official_required_dates", "official_month", "official_gate_before_finmind",
    "anchor_relation", "supported_use", "unsupported", "rights", "calendar_fact_reference",
    "primary_route_evidence", "caps", "identity_encoding_only", "credentials_cookie_proxy",
    "first_failure_stop_spent", "no_retry", "financial_start_required",
}
SEAL_FIELDS = {
    "schema", "issue", "namespace", "policy_sha256", "policy_pin", "candidate_sha",
    "module_sha256", "script_sha256", "loader_sha256", "command_sha256", "command",
    "qa_thread", "qa_session", "parent_thread", "owner_thread", "authorized_by",
    "financial_start", "issued_at_utc", "expires_at_utc", "consumer", "supported_use",
    "urls", "cutoffs", "caps",
}
BINDING_FIELDS = {"candidate_sha", "module_sha256", "script_sha256", "loader_sha256", "command_sha256", "command", "qa_thread", "qa_session", "owner_thread"}
FINMIND_FIELDS = {"date", "stock_id", "Trading_Volume", "Trading_money", "open", "max", "min", "close", "spread", "Trading_turnover"}
INTEGER_FIELDS = {"Trading_Volume", "Trading_money", "Trading_turnover"}
NUMBER_FIELDS = {"open", "max", "min", "close", "spread"}
NUMERIC_LEXICAL_LIMIT = 64
NUMERIC_EXPONENT_LIMIT = 18
ROOT_NODE_LIMIT = 200_000
DIAGNOSTIC_LIMIT = 64
MAX_OFFICIAL_ROWS = 31


class TaiexSourceError(Exception):
    """Only static bounded codes are retained; provider text is never diagnostic."""

    def __init__(self, code: str, phase: str = "guard"):
        self.code = code[:64]
        self.phase = phase[:48]
        super().__init__(self.code)


def fail(code, phase="guard"):
    raise TaiexSourceError(code, phase)


def _cleanup_note(notes, code):
    if notes is not None and code not in notes and len(notes) < 16:
        notes.append(code)


def clear_error_graph(error, *, notes=None):
    """Detach supported exception/payload aliases and slots without reading frames.

    Custom dict/slot payloads and builtin UnicodeError.object/OSError.filename etc.
    are included. Unknown payload owners are detached and explicitly reported.
    Immutable copies are dereferenced; no physical-wipe guarantee is made.
    """
    todo, seen, containers, views, buffers, cleanup = [error], set(), [], [], [], []
    while todo:
        current = todo.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        kind = type(current)
        if isinstance(current, BaseException):
            todo.extend((current.__cause__, current.__context__, current.args, current.__dict__))
            current.__traceback__ = None
            current.__cause__ = None
            current.__context__ = None
            current.args = ()
            attributes = {"object", "reason", "encoding", "filename", "filename2", "text", "msg", "code"}
            for base in kind.__mro__:
                slots = base.__dict__.get("__slots__", ())
                attributes.update((slots,) if type(slots) is str else slots)
            for name in attributes - {"__dict__", "__weakref__"}:
                try:
                    value = getattr(current, name)
                except AttributeError:
                    continue
                except BaseException as attribute_error:
                    cleanup.append("exception_attribute_read")
                    attribute_error.__traceback__ = attribute_error.__cause__ = attribute_error.__context__ = None
                    attribute_error.args = ()
                    continue
                todo.append(value)
                try:
                    setattr(current, name, b"" if name == "object" and type(value) is bytes else None)
                except BaseException as attribute_error:
                    cleanup.append("exception_slot_release")
                    attribute_error.__traceback__ = attribute_error.__cause__ = attribute_error.__context__ = None
                    attribute_error.args = ()
        elif kind is dict:
            todo.extend(current.keys())
            todo.extend(current.values())
            containers.append(current)
        elif kind in (list, tuple, set, frozenset):
            todo.extend(current)
            if kind in (list, set):
                containers.append(current)
        elif kind is memoryview:
            try:
                todo.append(current.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
            else:
                views.append(current)
        elif kind is bytearray:
            buffers.append(current)
        elif kind is io.StringIO:
            current.close()
        elif kind not in (str, bytes, int, float, bool, type(None), Decimal, Fraction, date, datetime):
            cleanup.append("opaque_exception_payload_detached")
    for view in views:
        try:
            view.release()
        except (BufferError, ValueError):
            cleanup.append("exception_view_release")
    for buffer in buffers:
        try:
            buffer[:] = b"\0" * len(buffer)
            buffer.clear()
        except BufferError:
            cleanup.append("exception_buffer_release")
    for container in reversed(containers):
        container.clear()
    todo.clear()
    seen.clear()
    return cleanup[:16]


def _decimal(value):
    if type(value) is bool or type(value) not in (str, int, Decimal):
        fail("numeric_type", "numeric")
    text = str(value)
    if len(text) > NUMERIC_LEXICAL_LIMIT:
        fail("numeric_lexical_limit", "numeric")
    try:
        result = Decimal(text)
    except InvalidOperation:
        fail("numeric_invalid", "numeric")
    parts = result.as_tuple()
    if (not result.is_finite() or not isinstance(parts.exponent, int)
            or abs(parts.exponent) > NUMERIC_EXPONENT_LIMIT
            or len(parts.digits) > NUMERIC_LEXICAL_LIMIT
            or abs(result.adjusted()) > NUMERIC_EXPONENT_LIMIT):
        fail("numeric_range", "numeric")
    return result


def _integer_literal(text):
    if len(text) > NUMERIC_LEXICAL_LIMIT:
        fail("integer_lexical_limit", "json")
    value = int(text)
    if abs(value) > 10 ** NUMERIC_EXPONENT_LIMIT:
        fail("integer_range", "json")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "json")
        result[key] = value
    return result


def strict_json(text, *, numeric=False):
    if type(text) is not str or len(text) > 1_048_576:
        fail("json_size", "json")
    # Bound nesting before the stdlib parser: strings/escapes do not affect depth.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 16:
                fail("json_depth", "json")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_int=_integer_literal,
                          parse_float=_decimal if numeric else _decimal,
                          parse_constant=lambda value: fail("json_nonfinite", "json"))
    except (ValueError, RecursionError):
        fail("json_invalid", "json")


def _string_list(value, *, length=None):
    if type(value) is not list or (length is not None and len(value) != length):
        fail("policy_list_type", "policy")
    if not all(type(item) is str and 0 < len(item) <= 1024 for item in value):
        fail("policy_list_member", "policy")


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _utc(text):
    if type(text) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", text):
        fail("seal_utc_grammar", "seal")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        fail("seal_utc_invalid", "seal")


class ExternalPolicy:
    def __init__(self, raw, document):
        self.raw = raw
        self.document = document
        self.sha256 = POLICY_SHA256
        self.pin = POLICY_PIN

    @classmethod
    def from_external(cls, raw_utf8, external_sha256, external_pin):
        if (type(raw_utf8) is not bytes or len(raw_utf8) != 4096
                or external_sha256 != POLICY_SHA256 or external_pin != POLICY_PIN
                or hashlib.sha256(raw_utf8).hexdigest() != external_sha256):
            fail("external_policy_pin", "policy")
        try:
            document = strict_json(raw_utf8.decode("utf-8"))
        except UnicodeDecodeError:
            fail("external_policy_utf8", "policy")
        if type(document) is not dict or document.keys() != POLICY_FIELDS:
            fail("policy_full_keys", "policy")
        bools = {"provider_literal_unit", "official_gate_before_finmind", "identity_encoding_only", "credentials_cookie_proxy", "first_failure_stop_spent", "no_retry", "financial_start_required"}
        ints = {"scale", "observation_count", "interval_count"}
        lists = {"cutoffs", "observed_dates", "urls", "official_schema", "official_date_grammar", "official_required_dates", "unsupported", "rights"}
        for key, value in document.items():
            if key in bools:
                if type(value) is not bool:
                    fail("policy_boolean_type", "policy")
            elif key in ints:
                if type(value) is not int:
                    fail("policy_integer_type", "policy")
            elif key in lists:
                _string_list(value)
            elif key == "caps":
                if type(value) is not dict or value.keys() != CAP_FIELDS or any(type(item) is not int for item in value.values()):
                    fail("policy_caps_type", "policy")
            elif key == "windows":
                if type(value) is not dict or set(value) != set(document["cutoffs"]):
                    fail("policy_windows_type", "policy")
                for window in value.values():
                    _string_list(window, length=21)
            elif type(value) is not str:
                fail("policy_string_type", "policy")
        _string_list(document["observed_dates"], length=22)
        _string_list(document["cutoffs"], length=2)
        if document["namespace"] != NAMESPACE or tuple(document["urls"]) != URLS:
            fail("policy_query_binding", "policy")
        # Hash authenticates ALL literal values; the full external document is retained.
        return cls(raw_utf8, document)


class FinancialStartSeal:
    def __init__(self, raw, document, pin, sha256):
        self.raw, self.document, self.pin, self.sha256 = raw, document, pin, sha256

    @classmethod
    def from_external(cls, raw_utf8, external_sha256, external_pin, policy, binding):
        if type(policy) is not ExternalPolicy:
            fail("seal_policy_type", "seal")
        canonical = ExternalPolicy.from_external(policy.raw, policy.sha256, policy.pin)
        if not _typed_equal(canonical.document, policy.document):
            fail("seal_policy_mutated", "seal")
        if (type(raw_utf8) is not bytes or not 0 < len(raw_utf8) <= 32768
                or type(external_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", external_sha256)
                or hashlib.sha256(raw_utf8).hexdigest() != external_sha256
                or type(external_pin) is not str
                or not re.fullmatch(r"https://github\.com/YiCheng0608/stock-lab/issues/33#issuecomment-[0-9]+", external_pin)):
            fail("external_seal_pin", "seal")
        try:
            document = strict_json(raw_utf8.decode("utf-8"))
        except UnicodeDecodeError:
            fail("external_seal_utf8", "seal")
        if type(document) is not dict or document.keys() != SEAL_FIELDS:
            fail("seal_full_keys", "seal")
        if type(binding) is not dict or binding.keys() != BINDING_FIELDS:
            fail("binding_full_keys", "seal")
        for key in BINDING_FIELDS:
            if not _typed_equal(document[key], binding[key]):
                fail("seal_execution_binding", "seal")
        for key in ("module_sha256", "script_sha256", "loader_sha256", "command_sha256"):
            if type(document[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", document[key]):
                fail("seal_hash_type", "seal")
        if type(document["candidate_sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", document["candidate_sha"]):
            fail("seal_candidate_type", "seal")
        _string_list(document["command"])
        if hashlib.sha256(json.dumps(document["command"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest() != document["command_sha256"]:
            fail("seal_command_hash", "seal")
        for key in ("qa_thread", "qa_session", "owner_thread", "authorized_by"):
            if type(document[key]) is not str or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", document[key]):
                fail("seal_identity_type", "seal")
        if (document["parent_thread"] is not None or document["qa_thread"] != document["qa_session"]
                or document["qa_thread"] == document["owner_thread"]
                or document["qa_thread"] == document["authorized_by"]):
            fail("seal_independent_top_qa", "seal")
        expected = {"schema": "issue33-financial-start-seal/v1", "issue": "YiCheng0608/stock-lab#33",
                    "namespace": NAMESPACE, "policy_sha256": policy.sha256, "policy_pin": policy.pin,
                    "financial_start": True, "consumer": CONSUMER, "supported_use": SUPPORTED_USE,
                    "urls": policy.document["urls"], "cutoffs": policy.document["cutoffs"], "caps": policy.document["caps"]}
        for key, value in expected.items():
            if not _typed_equal(document[key], value):
                fail("seal_policy_binding", "seal")
        if _utc(document["issued_at_utc"]) >= _utc(document["expires_at_utc"]):
            fail("seal_validity_order", "seal")
        return cls(raw_utf8, document, external_pin, external_sha256)


class NativeText:
    """Explicit StringIO owner + original immutable backing + native estimate."""

    def __init__(self, stream, backing_text):
        if type(stream) is not io.StringIO or type(backing_text) is not str:
            fail("native_text_owner", "roots")
        self.stream, self.backing = stream, backing_text
        self.native_bytes = 4 * len(backing_text) + 256


class NativeTransport:
    """Declared stdlib response/socket backing estimate; closed before root release.

    The allowance covers the HTTP buffered reader and TLS record buffers. It is a
    declared native backing estimate, not a measurement of all native allocations.
    Injected boundary transports must declare their own source buffers separately.
    """

    def __init__(self, response=None):
        self.response = response
        self.native_bytes = 262_144


class NativeParseReservation:
    """Conservative declared estimate for transient stdlib parser allocations.

    Raw text remains separately tracked. Input is <=1MiB/depth16; row/schema and
    lexical bounds then constrain retained documents. This 8MiB allowance covers
    transient decoder/csv cells prior to registration, and is not an RSS claim.
    """

    def __init__(self):
        self.native_bytes = 8_388_608


class NativeReadReservation:
    """Separate declared maximum one-read bytes allocation; not TLS/parser storage."""

    def __init__(self):
        self.native_bytes = 65_536


class NativeAuditReservation:
    """Bounded temporary non-price audit copies/serialization allowance."""

    def __init__(self):
        self.native_bytes = 65_536


class RootOwner:
    def __init__(self, name):
        if type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
            fail("root_owner_name", "roots")
        self.name, self.roots = name, {}

    def track(self, name, value):
        if type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name):
            fail("root_name", "roots")
        self.roots[name] = value
        return value

    def stringio(self, name, backing_text):
        stream = io.StringIO(backing_text, newline="")
        self.track(name, NativeText(stream, backing_text))
        return stream

    def declared_roots(self):
        return self.roots


def estimate_roots(owners, *, notes=None):
    """Bounded supported union estimate, including memoryview.obj/native backing."""
    stack = [owner.roots for owner in owners]
    seen, total, nodes = set(), 0, 0
    native_stream_owners, native_stream_aliases = set(), set()
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        nodes += 1
        if nodes > ROOT_NODE_LIMIT:
            fail("root_work_limit", "roots")
        total += sys.getsizeof(value)
        kind = type(value)
        if kind is dict:
            if len(value) > ROOT_NODE_LIMIT:
                fail("root_container_limit", "roots")
            stack.extend(value.keys())
            stack.extend(value.values())
        elif kind in (list, tuple, set, frozenset):
            if len(value) > ROOT_NODE_LIMIT:
                fail("root_container_limit", "roots")
            stack.extend(value)
        elif kind is memoryview:
            try:
                stack.append(value.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
        elif kind is NativeText:
            stack.append(value.backing)
            native_stream_owners.add(id(value.stream))
            if id(value.stream) not in seen:
                total += sys.getsizeof(value.stream)
                seen.add(id(value.stream))
            total += value.native_bytes
        elif kind is io.StringIO:
            # A normal alias can precede its NativeText owner in graph traversal.
            # Resolve it against the complete declared union, never an opaque shell.
            native_stream_aliases.add(id(value))
        elif kind is NativeTransport:
            total += sys.getsizeof(value.response) + value.native_bytes
            if value.response is not None:
                stack.append(value.response.headers)
        elif kind in (NativeParseReservation, NativeReadReservation, NativeAuditReservation):
            total += value.native_bytes
        elif kind is Fraction:
            stack.extend((value.numerator, value.denominator))
        elif kind is Decimal:
            total += len(value.as_tuple().digits) * 8 + 64
        elif kind not in (str, bytes, bytearray, int, float, bool, type(None), date, datetime):
            fail("opaque_source_root", "roots")
        if total > 33_554_432:
            fail("root_bytes_limit", "roots")
    if not native_stream_aliases <= native_stream_owners:
        fail("opaque_source_root", "roots")
    return total, nodes


def _release_roots(owners, *, notes=None):
    stack = [owner.roots for owner in owners]
    seen, containers, buffers, views, natives, native_streams, errors = set(), [], [], [], [], [], []
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        kind = type(value)
        if kind is dict:
            stack.extend(value.keys())
            stack.extend(value.values())
            containers.append(value)
        elif kind in (list, tuple, set, frozenset):
            stack.extend(value)
            if kind in (list, set):
                containers.append(value)
        elif kind is memoryview:
            try:
                stack.append(value.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
            else:
                views.append(value)
        elif kind is bytearray:
            buffers.append(value)
        elif kind is NativeText:
            natives.append(value)
        elif kind is io.StringIO:
            native_streams.append(value)
        elif kind is NativeTransport:
            value.response = None
            value.native_bytes = 0
        elif kind in (NativeParseReservation, NativeReadReservation, NativeAuditReservation):
            value.native_bytes = 0
        elif isinstance(value, BaseException):
            errors.extend(clear_error_graph(value, notes=notes))
    for view in views:
        try:
            view.release()
        except BaseException as error:
            errors.append("memoryview_release")
            clear_error_graph(error)
    for native in natives:
        try:
            native.stream.close()
        except BaseException as error:
            errors.append("stringio_close")
            clear_error_graph(error)
        native.backing, native.native_bytes = "", 0
    for stream in native_streams:
        try:
            stream.close()
        except BaseException as error:
            errors.append("stringio_alias_close")
            errors.extend(clear_error_graph(error, notes=notes))
    for buffer in buffers:
        try:
            buffer[:] = b"\0" * len(buffer)
            buffer.clear()
        except BaseException as error:
            errors.append("buffer_release")
            clear_error_graph(error)
    for container in reversed(containers):
        container.clear()
    return errors[:16]


class OracleHooks:
    def __init__(self, observer, official, finmind, owner):
        if not all(callable(item) for item in (observer, official, finmind)) or type(owner) is not RootOwner:
            fail("oracle_hooks", "constructor")
        self.observer, self.official, self.finmind, self.owner = observer, official, finmind, owner


class AttemptLedger:
    def __init__(self):
        self.attempted_urls = []

    @property
    def spent(self):
        return bool(self.attempted_urls)


_REAL_LEDGER = AttemptLedger()


class _HTTPSResponse:
    def __init__(self, connection, response):
        self.connection, self.response = connection, response
        self.status = response.status
        self.headers = response.getheaders()

    def read(self, count, timeout):
        if count <= 0:
            fail("zero_read_forbidden", "transport")
        sock = self.connection.sock
        if sock is None and self.response.fp is not None:
            sock = getattr(getattr(self.response.fp, "raw", None), "_sock", None)
        if sock is None:
            fail("transport_timeout_socket", "transport")
        sock.settimeout(timeout)
        return self.response.read(count)

    @property
    def framing_eof(self):
        return self.response.isclosed() or self.response.length == 0

    def close(self):
        try:
            self.response.close()
        finally:
            self.connection.close()


class HTTPSOneShot:
    """Real stdlib HTTPS, identity, system CA, no redirect/retry/cookie/proxy/auth."""

    def open(self, url, timeout):
        parts = urlsplit(url)
        if url not in URLS or parts.scheme != "https" or parts.username or parts.password:
            fail("transport_url", "transport")
        connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout, context=ssl.create_default_context())
        try:
            connection.request("GET", parts.path + "?" + parts.query,
                               headers={"Accept-Encoding": "identity", "Connection": "close"})
            return _HTTPSResponse(connection, connection.getresponse())
        except BaseException:
            connection.close()
            raise


class RevocableHandle:
    def __init__(self, batch, key):
        self._batch, self._key = batch, key

    def visit(self, callback, owner):
        return self._batch._result_operation("result_visit", "RevocableHandle.visit",
                                             lambda: self._visit(callback, owner))

    def _visit(self, callback, owner):
        batch = self._batch
        batch._guard("handle_visit", available=True)
        if type(owner) is not RootOwner or owner not in batch.owners:
            fail("unregistered_result_owner", "consumer")
        if not callable(callback):
            fail("result_callback", "consumer")
        # Callback aliases/copies must be tracked by owner; no immutable result is exported.
        batch._callback("result_visit", callback, batch.product.roots[self._key])
        batch._measure("result_visit")
        batch._guard("handle_visit_done", available=True)

    def declared_roots(self):
        return self._batch._result_operation("handle_roots", "RevocableHandle.declared_roots", self._declared_roots)

    def _declared_roots(self):
        self._batch._guard("handle_roots", available=True)
        return {self._key: self._batch.product.roots[self._key]}


class TaiexNominalSource:
    """Use as a context manager; acquisition is atomic after both full oracles."""

    def __init__(self, policy, seal, hooks, *, binding, supported_use=SUPPORTED_USE,
                 consumer=CONSUMER, transport=None, boundary_only=False, ledger=None,
                 monotonic=time.monotonic, utc_now=None):
        if type(policy) is not ExternalPolicy or type(seal) is not FinancialStartSeal or type(hooks) is not OracleHooks:
            fail("typed_source_inputs", "constructor")
        if type(boundary_only) is not bool:
            fail("boundary_flag_type", "constructor")
        if (transport is not None or ledger is not None) and not boundary_only:
            fail("injected_transport_requires_boundary", "constructor")
        if boundary_only and transport is None:
            fail("boundary_transport_required", "constructor")
        self.policy, self.seal, self.hooks = policy, seal, hooks
        self.binding, self.supported_use, self.consumer = binding, supported_use, consumer
        self.transport = transport if transport is not None else HTTPSOneShot()
        self.boundary_only = boundary_only
        self.ledger = ledger if ledger is not None else _REAL_LEDGER
        self.monotonic = monotonic
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.product = RootOwner("product")
        self.owners = [self.product, hooks.owner]
        self.product.track("policy_raw", policy.raw)
        self.product.track("policy_document", policy.document)
        self.product.track("seal_raw", seal.raw)
        self.product.track("seal_document", seal.document)
        self.product.track("binding", binding)
        self.state, self.batch_start = "pending", None
        self.raw_total, self.responses = 0, []
        self.request_seconds_used, self.active_request_started = 0.0, None
        self.receipts, self.diagnostics = [], []
        self.first_failure, self.secondary, self.cleanup_failures = None, [], []
        self.cleanup_notes = []
        self.product.track("capture_receipts", self.receipts)
        self.product.track("diagnostics", self.diagnostics)
        self.product.track("secondary", self.secondary)
        self.product.track("cleanup_failures", self.cleanup_failures)
        self.product.track("cleanup_notes", self.cleanup_notes)
        self._final_audit = None
        self.high_water, self.measure_seconds, self.measure_calls = 0, 0.0, 0
        self._acquired = False

    def register_owner(self, owner):
        if self.state != "pending" or self.batch_start is not None or type(owner) is not RootOwner:
            fail("late_root_owner", "roots")
        if owner not in self.owners:
            if any(item.name == owner.name for item in self.owners) or len(self.owners) >= 8:
                fail("root_owner_duplicate_or_limit", "roots")
            self.owners.append(owner)

    def _event(self, code, phase, location):
        if len(self.diagnostics) < DIAGNOSTIC_LIMIT:
            self.diagnostics.append({"code": code[:64], "phase": phase[:48], "location": location,
                                     "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start)})

    def _failure(self, code, phase, location):
        current_request = 0.0 if self.active_request_started is None else max(0.0, self.monotonic() - self.active_request_started)
        entry = {"code": code[:64], "phase": phase[:48], "location": location,
                 "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start),
                 "cumulative_request_elapsed_seconds": self.request_seconds_used + current_request,
                 "request_deadline_seconds": 20, "batch_deadline_seconds": 180}
        if self.first_failure is None:
            self.first_failure = entry
            self.product.track("first_failure", entry)
        elif len(self.secondary) < 16:
            self.secondary.append(entry)

    def _guard(self, phase, *, available=False):
        if self.state in ("released", "failed", "expired"):
            fail("lease_" + self.state, phase)
        if available and self.state != "available":
            fail("lease_pending", phase)
        if self.batch_start is not None:
            elapsed = self.monotonic() - self.batch_start
            now = self.utc_now()
            if type(now) is not datetime or now.tzinfo is None:
                fail("clock_utc_type", phase)
            if elapsed < 0 or elapsed >= 180 or now >= _utc(self.seal.document["expires_at_utc"]):
                self.state = "expired"
                fail("lease_expired", phase)
            if now < _utc(self.seal.document["issued_at_utc"]):
                fail("seal_not_yet_valid", phase)

    def _measure(self, phase):
        started = time.perf_counter()
        size, nodes = estimate_roots(self.owners, notes=self.cleanup_notes)
        elapsed = max(0.0, time.perf_counter() - started)
        self.measure_seconds += elapsed
        self.measure_calls += 1
        self.high_water = max(self.high_water, size)
        self._event("root_measure", phase, "TaiexNominalSource._measure")
        self._guard(phase)
        return size, nodes

    def _callback(self, phase, callback, *args):
        self._guard(phase)
        try:
            return callback(*args)
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "callback_failure"
            self._failure(code, phase, "TaiexNominalSource._callback")
            self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            raise TaiexSourceError(code, phase) from None

    def _result_operation(self, phase, location, operation):
        """Any public result-operation failure terminally revokes the whole batch.

        Catching a callback/measurement error inside the consumer's with block must
        never let that caller resume getters, summaries or previously issued handles.
        """
        try:
            return operation()
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "result_operation_failure"
            origin_phase = error.phase if type(error) is TaiexSourceError else phase
            if self._final_audit is None:
                self._failure(code, origin_phase, location)
                self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
                self.release(failed=True)
            else:
                # Refusal after terminal release preserves the original audit and
                # cannot recreate a declared source root or replace the first cause.
                clear_error_graph(error)
            raise TaiexSourceError(code, origin_phase) from None

    def _preflight(self):
        if self.supported_use != SUPPORTED_USE or self.consumer != CONSUMER:
            fail("unsupported_use_preget", "preflight")
        # Revalidate external bytes and execution bindings, preventing mutable-policy drift.
        policy = ExternalPolicy.from_external(self.policy.raw, self.policy.sha256, self.policy.pin)
        if not _typed_equal(policy.document, self.policy.document):
            fail("policy_mutated", "preflight")
        seal = FinancialStartSeal.from_external(self.seal.raw, self.seal.sha256, self.seal.pin, policy, self.binding)
        if not _typed_equal(seal.document, self.seal.document):
            fail("seal_mutated", "preflight")
        if self.ledger.spent or self._acquired:
            fail("namespace_spent", "preflight")
        self._guard("preflight")
        self._measure("preflight")

    def _request_remaining(self, started):
        self._guard("request")
        remaining = 20.0 - self.request_seconds_used - (self.monotonic() - started)
        if remaining <= 0:
            self._failure("request_deadline", "request", "TaiexNominalSource._request_remaining")
            fail("request_deadline", "request")
        return min(remaining, 180.0 - (self.monotonic() - self.batch_start))

    def _capture(self, ordinal):
        started = self.monotonic()
        self.active_request_started = started
        try:
            raw, receipt = self._capture_wire(ordinal, started)
        finally:
            # Count each attempted wire interval, including failures. Parsing,
            # independent oracles and result use remain under the separate batch
            # lease; they cannot reset or extend the cumulative20s request budget.
            self.request_seconds_used += max(0.0, self.monotonic() - started)
            self.active_request_started = None
            self._event("request_interval_end", "capture", "TaiexNominalSource._capture")
        if self.request_seconds_used >= 20:
            self._failure("request_deadline", "request", "TaiexNominalSource._capture")
            fail("request_deadline", "request")
        self._measure("captured")
        hook_receipt = self.hooks.owner.track("observer_receipt_" + str(ordinal), dict(receipt))
        self._callback("original_observer", self.hooks.observer, raw, hook_receipt)
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            fail("original_observer_mutated_raw", "observer")
        self._measure("observed")
        return raw, receipt

    def _capture_wire(self, ordinal, started):
        url = URLS[ordinal]
        self._guard("capture")
        if len(self.ledger.attempted_urls) != ordinal or len(self.ledger.attempted_urls) >= 2:
            fail("attempt_order", "capture")
        # Attempt is SPENT before opening any transport; first failure never retries.
        self.ledger.attempted_urls.append(url)
        pending_transport = self.product.track("transport_" + str(ordinal), NativeTransport())
        self._measure("transport_pending")
        response = self.transport.open(url, self._request_remaining(started))
        self.responses.append(response)
        if type(response) is _HTTPSResponse:
            pending_transport.response = response
        self._request_remaining(started)
        if type(response.status) is not int or response.status != 200:
            fail("http_status_stop", "capture")
        headers = {}
        if type(response.headers) is not list or len(response.headers) > 128:
            fail("http_headers", "capture")
        for pair in response.headers:
            if type(pair) is not tuple or len(pair) != 2 or not all(type(item) is str for item in pair):
                fail("http_header_type", "capture")
            key, value = pair[0].lower(), pair[1]
            if key in headers:
                fail("duplicate_http_header", "capture")
            headers[key] = value
        if headers.get("content-encoding", "identity").lower() != "identity":
            fail("identity_encoding_required", "capture")
        if "location" in headers or "set-cookie" in headers:
            fail("redirect_cookie_stop", "capture")
        length = None
        if "content-length" in headers:
            token = headers["content-length"]
            if not re.fullmatch(r"[0-9]{1,8}", token):
                fail("content_length_invalid", "capture")
            length = int(token)
        transfer = headers.get("transfer-encoding")
        if transfer is not None and (transfer.lower() != "chunked" or length is not None):
            fail("http_framing", "capture")
        if length is not None and (length > 1_048_576 or length > 2_097_152 - self.raw_total):
            fail("declared_body_limit", "capture")
        raw = self.product.track("raw_" + str(ordinal), bytearray())
        digest = hashlib.sha256()
        self.product.track("read_allowance_" + str(ordinal), NativeReadReservation())
        self._measure("read_ready")
        block_key = "active_read_block_" + str(ordinal)
        while True:
            self._request_remaining(started)
            body_remaining = 1_048_576 - len(raw)
            aggregate_remaining = 2_097_152 - self.raw_total
            remaining = min(body_remaining, aggregate_remaining)
            if remaining <= 0:
                if length is None or not response.framing_eof:
                    fail("exact_cap_without_framing_eof", "capture")
                break
            if response.framing_eof:
                break
            wanted = min(65_536, remaining)
            if length is not None:
                wanted = min(wanted, length - len(raw))
                if wanted <= 0:
                    fail("content_length_framing_eof", "capture")
            block = response.read(wanted, self._request_remaining(started))
            self.product.track(block_key, block)
            self._request_remaining(started)
            if type(block) is not bytes or len(block) > wanted:
                fail("transport_read_contract", "capture")
            if not block:
                if length is not None and len(raw) != length:
                    fail("truncated_body", "capture")
                if not response.framing_eof:
                    fail("eof_without_framing", "capture")
                self.product.roots.pop(block_key, None)
                break
            raw.extend(block)
            self.raw_total += len(block)
            digest.update(block)
            self.product.roots.pop(block_key, None)
            block = None
        if not raw or (length is not None and len(raw) != length):
            fail("body_empty_or_truncated", "capture")
        now = self.utc_now()
        capture_date = (now.astimezone(timezone.utc) + timedelta(hours=8)).date().isoformat()
        receipt = {"ordinal": ordinal, "url": url, "body_bytes": len(raw), "sha256": digest.hexdigest(),
                   "eof": True, "capture_utc": now.astimezone(timezone.utc).isoformat(),
                   "capture_taipei_date": capture_date, "request_elapsed_seconds": self.monotonic() - started,
                   "cumulative_request_elapsed_seconds": self.request_seconds_used + self.monotonic() - started,
                   "boundary_only": self.boundary_only}
        self.receipts.append(receipt)
        return raw, receipt

    def _official(self, raw, receipt):
        self.product.track("official_parser_reservation", NativeParseReservation())
        self._measure("official_parse_reservation")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            fail("official_utf8", "official_parse")
        self.product.track("official_text", text)
        stream = self.product.stringio("official_native_text", text)
        rows = self.product.track("official_rows", [])
        scratch = self.product.track("official_parser_scratch", {})
        found_header = False
        try:
            for cells in csv.reader(stream, strict=True):
                scratch["cells"] = cells
                if not cells:
                    continue
                if not found_header:
                    if cells != self.policy.document["official_schema"]:
                        fail("official_schema", "official_parse")
                    found_header = True
                    continue
                if len(cells) != 5 or len(rows) >= MAX_OFFICIAL_ROWS:
                    fail("official_row_width_or_count", "official_parse")
                token = cells[0]
                match = re.fullmatch(r"([0-9]{3})/([0-9]{2})/([0-9]{2})", token) or re.fullmatch(r"([0-9]{3})([0-9]{2})([0-9]{2})", token)
                if match is None:
                    fail("official_roc_date", "official_parse")
                try:
                    actual = date(int(match[1]) + 1911, int(match[2]), int(match[3]))
                except ValueError:
                    fail("official_invalid_date", "official_parse")
                iso = actual.isoformat()
                if iso[:7] != "2026-10" or actual.weekday() >= 5 or iso > receipt["capture_taipei_date"]:
                    fail("official_month_weekday_future", "official_parse")
                if any(item["date"] == iso for item in rows):
                    fail("official_duplicate_date", "official_parse")
                values = []
                scratch["values"] = values
                for token in cells[1:]:
                    if len(token) > NUMERIC_LEXICAL_LIMIT or not re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,18})?", token):
                        fail("official_numeric_grammar", "official_parse")
                    value = _decimal(token.replace(",", ""))
                    if value <= 0:
                        fail("official_positive_ohlc", "official_parse")
                    values.append(value)
                opening, high, low, close = values
                if not low <= min(opening, close) <= max(opening, close) <= high:
                    fail("official_ohlc_range", "official_parse")
                rows.append({"date": iso, "open": opening, "high": high, "low": low, "close": close})
        except csv.Error:
            fail("official_csv_invalid", "official_parse")
        finally:
            stream.close()
        if not found_header or not rows:
            fail("official_empty", "official_parse")
        if not all(sum(item["date"] == cutoff for item in rows) == 1 for cutoff in self.policy.document["cutoffs"]):
            fail("official_missing_anchor", "official_parse")
        return rows

    def _finmind(self, raw):
        self.product.track("finmind_parser_reservation", NativeParseReservation())
        self._measure("finmind_parse_reservation")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            fail("finmind_utf8", "finmind_parse")
        self.product.track("finmind_text", text)
        document = self.product.track("finmind_document", strict_json(text, numeric=True))
        if type(document) is not dict or document.keys() != {"status", "msg", "data"}:
            fail("finmind_document_schema", "finmind_parse")
        if type(document["status"]) is not int or document["status"] != 200 or type(document["msg"]) is not str or document["msg"] != "success":
            fail("finmind_status_msg", "finmind_parse")
        rows = document["data"]
        if type(rows) is not list or len(rows) != 22:
            fail("finmind_exact_22", "finmind_parse")
        seen = set()
        normalized = self.product.track("finmind_rows", [])
        for row in rows:
            if type(row) is not dict or row.keys() != FINMIND_FIELDS:
                fail("finmind_full_row_schema", "finmind_parse")
            token = row["date"]
            if type(token) is not str or not re.fullmatch(r"2026-[0-9]{2}-[0-9]{2}", token):
                fail("finmind_date_grammar", "finmind_parse")
            try:
                actual = date.fromisoformat(token)
            except ValueError:
                fail("finmind_invalid_date", "finmind_parse")
            if token not in self.policy.document["observed_dates"] or actual.weekday() >= 5 or token in seen:
                fail("finmind_date_set_or_duplicate", "finmind_parse")
            seen.add(token)
            if type(row["stock_id"]) is not str or row["stock_id"] != "TAIEX":
                fail("finmind_stock_id", "finmind_parse")
            result = {"date": token, "stock_id": "TAIEX"}
            for field in INTEGER_FIELDS:
                value = row[field]
                if type(value) is not int or not 0 <= value <= 10 ** NUMERIC_EXPONENT_LIMIT:
                    fail("finmind_integer_range", "finmind_parse")
                result[field] = value
            for field in NUMBER_FIELDS:
                value = row[field]
                if type(value) not in (int, Decimal):
                    fail("finmind_numeric_type", "finmind_parse")
                value = _decimal(value)
                if field != "spread" and value <= 0:
                    fail("finmind_positive_ohlc", "finmind_parse")
                result[field] = value
            if not result["min"] <= min(result["open"], result["close"]) <= max(result["open"], result["close"]) <= result["max"]:
                fail("finmind_ohlc_range", "finmind_parse")
            normalized.append(result)
        if seen != set(self.policy.document["observed_dates"]):
            fail("finmind_complete_dates", "finmind_parse")
        return normalized

    def acquire(self):
        self._guard("acquire")
        if self.batch_start is not None:
            fail("acquire_once", "preflight")
        self.batch_start = self.monotonic()
        self._event("batch_begin", "preflight", "TaiexNominalSource.acquire")
        try:
            self._preflight()
            official_raw, official_receipt = self._capture(0)
            self._event("parse_begin", "official_parse", "TaiexNominalSource._official")
            official = self._official(official_raw, official_receipt)
            oracle_receipt = self.hooks.owner.track("official_oracle_receipt", dict(official_receipt))
            oracle = self._callback("official_full_oracle", self.hooks.official, official_raw, oracle_receipt)
            self.hooks.owner.track("official_oracle_return", oracle)
            if hashlib.sha256(official_raw).hexdigest() != official_receipt["sha256"]:
                fail("official_oracle_mutated_raw", "official_oracle")
            self._measure("official_oracle")
            if not _typed_equal(oracle, official):
                fail("official_full_oracle_mismatch", "official_oracle")
            # Official complete rows + independent oracle + both anchors precede GET2.
            raw, receipt = self._capture(1)
            self._event("parse_begin", "finmind_parse", "TaiexNominalSource._finmind")
            rows = self._finmind(raw)
            oracle_receipt = self.hooks.owner.track("finmind_oracle_receipt", dict(receipt))
            oracle = self._callback("finmind_full_oracle", self.hooks.finmind, raw, oracle_receipt)
            self.hooks.owner.track("finmind_oracle_return", oracle)
            if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                fail("finmind_oracle_mutated_raw", "finmind_oracle")
            self._measure("finmind_oracle")
            if not _typed_equal(oracle, rows):
                fail("finmind_full_oracle_mismatch", "finmind_oracle")
            close_by_date = self.product.track("closes", {row["date"]: row["close"] for row in rows})
            for cutoff in self.policy.document["cutoffs"]:
                anchor = next(item["close"] for item in official if item["date"] == cutoff)
                if anchor != close_by_date[cutoff]:
                    fail("anchor_exact_scale1", "anchor")
            self._guard("atomic_available")
            self._measure("atomic_available")
            self.state, self._acquired = "available", True
            self._event("available", "available", "TaiexNominalSource.acquire")
            return self
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "source_failure"
            phase = error.phase if type(error) is TaiexSourceError else "acquire"
            self._failure(code, phase, "TaiexNominalSource.acquire")
            self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            self.release(failed=True)
            raise TaiexSourceError(code, phase) from None

    def _provenance(self):
        policy = self.policy.document
        return {"symbol": "TAIEX", "policy_pin": self.policy.pin, "policy_sha256": self.policy.sha256,
                "seal_pin": self.seal.pin, "seal_sha256": self.seal.sha256, "namespace": NAMESPACE,
                "sources": ["Taiwan Stock Exchange (TWSE), government data11755 OGL1.0", "FinMind (personal noncommercial attribution; no mirror/raw redistribution)"],
                "rights": list(policy["rights"]), "calendar_fact_reference": policy["calendar_fact_reference"],
                "primary_route_evidence": policy["primary_route_evidence"],
                "external_calendar_basis": policy["calendar_basis"], "external_price_basis": policy["price_basis"],
                "output_alias_mapping": {"calendar_basis": "cross_market_candidate_inference", "price_basis": "nominal_index_level"},
                "unit": "index_points", "unit_kind": policy["unit_kind"], "provider_literal_unit": False,
                "scale": 1, "supported_use": SUPPORTED_USE, "unsupported": list(policy["unsupported"]),
                "publication_time": "unsupported", "first_availability": "unsupported", "revision_history": "unsupported",
                "verified_twse_calendar": False, "adjusted_basis": False, "total_return": False,
                "capture_receipts": [dict(item) for item in self.receipts], "boundary_only": self.boundary_only,
                "execution_binding": dict(self.binding)}

    def _cutoff(self, cutoff):
        if type(cutoff) is not str or cutoff not in self.policy.document["cutoffs"]:
            fail("unsupported_cutoff", "consumer")

    def get_taiex_nominal21(self, cutoff, *, supported_use=SUPPORTED_USE):
        return self._result_operation("getter", "TaiexNominalSource.get_taiex_nominal21",
                                      lambda: self._get_taiex_nominal21(cutoff, supported_use=supported_use))

    def _get_taiex_nominal21(self, cutoff, *, supported_use):
        self._guard("getter", available=True)
        if supported_use != SUPPORTED_USE:
            fail("unsupported_getter_use", "consumer")
        self._cutoff(cutoff)
        dates = self.policy.document["windows"][cutoff]
        payload = {"cutoff": cutoff, "observations": [{"date": day, "close": self.product.roots["closes"][day]} for day in dates],
                   "first_date": dates[0], "last_date": dates[-1], "observation_count": 21, "interval_count": 20,
                   "calendar_basis": "cross_market_candidate_inference", "price_basis": "nominal_index_level",
                   "benchmark20d_ready": False, "provenance": self._provenance()}
        key = "getter_" + cutoff
        self.product.track(key, payload)
        self._measure("getter")
        return RevocableHandle(self, key)

    def summarize(self, cutoff, *, consumer=CONSUMER, supported_use=SUPPORTED_USE):
        return self._result_operation("summary", "TaiexNominalSource.summarize",
                                      lambda: self._summarize(cutoff, consumer=consumer, supported_use=supported_use))

    def _summarize(self, cutoff, *, consumer, supported_use):
        self._guard("summary", available=True)
        if consumer != CONSUMER or supported_use != SUPPORTED_USE:
            fail("unsupported_consumer_use", "consumer")
        self._cutoff(cutoff)
        dates = self.policy.document["windows"][cutoff]
        first = self.product.roots["closes"][dates[0]]
        last = self.product.roots["closes"][dates[-1]]
        # Numeric lexical/exponent bounds were checked before Fraction construction.
        ratio = (Fraction(last) - Fraction(first)) / Fraction(first)
        payload = {"consumer": CONSUMER, "cutoff": cutoff, "first_date": dates[0], "last_date": dates[-1],
                   "observation_count": 21, "interval_count": 20, "return": ratio,
                   "return_numerator": ratio.numerator, "return_denominator": ratio.denominator,
                   "formula": "(C_end-C_start)/C_start", "calendar_basis": "cross_market_candidate_inference",
                   "price_basis": "nominal_index_level", "benchmark20d_ready": False, "provenance": self._provenance()}
        key = "summary_" + cutoff
        self.product.track(key, payload)
        self._measure("summary")
        return RevocableHandle(self, key)

    def declared_roots(self):
        return {owner.name: owner.declared_roots() for owner in self.owners}

    def _audit_snapshot(self):
        # Bounded, non-price primitives owned by product. No serializer is needed
        # for the retained fallback; its temporary allocation has its own allowance.
        return {"capture_receipts": [dict(item) for item in self.receipts],
                "first_product_failure": None if self.first_failure is None else dict(self.first_failure),
                "secondary": [dict(item) for item in self.secondary],
                "events": [dict(item) for item in self.diagnostics]}

    def release(self, *, failed=False):
        # Trace/profile are turned off FIRST. No frame/f_locals/response is recorded.
        sys.settrace(None)
        sys.setprofile(None)
        if self.state in ("released", "failed") and self._final_audit is not None:
            return
        cleanup, notes, audit = list(self.cleanup_failures), list(self.cleanup_notes), None
        self.product.track("release_audit_allowance", NativeAuditReservation())
        try:
            try:
                audit_text = json.dumps(self._audit_snapshot(), separators=(",", ":"))
                if type(audit_text) is not str or len(audit_text) > 65_536:
                    fail("audit_serialization_contract", "release_audit")
                self.product.track("release_diagnostic_serialization", audit_text)
            except BaseException as error:
                cleanup.append("audit_serialization_failure")
                if len(self.secondary) < 16:
                    self.secondary.append({"code": "audit_serialization_failure", "phase": "release_audit",
                                           "location": "TaiexNominalSource.release", "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start)})
                cleanup.extend(clear_error_graph(error, notes=notes))
            try:
                started = time.perf_counter()
                size, nodes = estimate_roots(self.owners, notes=notes)
                self.measure_seconds += max(0.0, time.perf_counter() - started)
                self.measure_calls += 1
                self.high_water = max(self.high_water, size)
            except BaseException as error:
                self._failure(error.code if type(error) is TaiexSourceError else "release_measure_failure",
                              "release_measure", "TaiexNominalSource.release")
                cleanup.extend(clear_error_graph(error, notes=notes))
            # Independent of json.dumps/json.loads, including serializer failure.
            audit = self._audit_snapshot()
        finally:
            # No audit failure may skip ANY response close or declared-root attempt.
            if audit is None:
                audit = {"capture_receipts": [], "first_product_failure": None if self.first_failure is None else dict(self.first_failure),
                         "secondary": [{"code": "audit_snapshot_failure", "phase": "release_audit", "location": "TaiexNominalSource.release"}], "events": []}
            for response in self.responses:
                try:
                    response.close()
                except BaseException as error:
                    if len(cleanup) < 16:
                        cleanup.append("transport_close")
                    cleanup.extend(clear_error_graph(error, notes=notes))
            self.responses.clear()
            try:
                cleanup.extend(_release_roots(self.owners, notes=notes))
            except BaseException as error:
                cleanup.append("root_release_failure")
                cleanup.extend(clear_error_graph(error, notes=notes))
                # Last-resort detachment still visits every declared owner.
                for owner in self.owners:
                    owner.roots.clear()
            self.cleanup_failures, self.cleanup_notes = cleanup[:16], notes[:16]
            self.policy.raw, self.seal.raw = b"", b""
            self.binding = {}
            self.hooks.observer = self.hooks.official = self.hooks.finmind = None
            self.transport = None
            self.state = "failed" if failed else "released"
            self._final_audit = audit

    def diagnostic_report(self):
        audit = self._final_audit or {"capture_receipts": self.receipts, "first_product_failure": self.first_failure,
                                     "secondary": self.secondary, "events": self.diagnostics}
        return {"state": self.state, "namespace": NAMESPACE, "namespace_spent": self.ledger.spent,
                "attempted_urls": list(self.ledger.attempted_urls), "complete_eof_raw_bytes": self.raw_total,
                "cumulative_request_elapsed_seconds": self.request_seconds_used,
                "capture_receipts": [dict(item) for item in audit["capture_receipts"]], "first_product_failure": audit["first_product_failure"],
                "secondary": list(audit["secondary"]), "cleanup_failures": list(self.cleanup_failures),
                "cleanup_notes": list(self.cleanup_notes),
                "events": list(audit["events"]), "declared_roots_estimate_high_water": self.high_water,
                "measurement_seconds": self.measure_seconds, "measurement_calls": self.measure_calls,
                "declared_roots_empty": all(not owner.roots for owner in self.owners),
                "artifact_bytes": 0, "boundary_only": self.boundary_only}

    def __enter__(self):
        return self.acquire()

    def __exit__(self, kind, error, traceback):
        if error is not None:
            if self._final_audit is None:
                self._failure(error.code if type(error) is TaiexSourceError else "consumer_failure", "consumer", "TaiexNominalSource.__exit__")
                self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            else:
                clear_error_graph(error)
        self.release(failed=error is not None)
        return False
