"""Issue 36: bounded, ephemeral TPEx six-day source and two five-day consumers.

Import and construction perform no network, file, DB or service operations.
Native acquisition requires the independently read external policy, a fresh
external financial seal pin and separately reviewed runtime/candidate binding.
The runtime binding names the Claude Code session that runs the capture
(CLAUDE_CODE_SESSION_ID, CLAUDE_EFFORT); see ReviewBinding. This module does
not authenticate GitHub or replace that external review.

Use ``with RAMCapture(...) as capture`` and call capture.capture() once. While
available, inspect seven getter handles, fourteen consumer handles and original
body/receipt views in the SAME scope. Declare QA oracle/parser/results/aliases
in mutable holders with declare_root(). Declare EVERY derived memoryview (the
graph also follows .obj). Immutable copies must be held in declared mutable
containers; arbitrary objects, functions and live frames are unsupported.
The caller must drop its lexical aliases and exit its RAM process afterwards.
No physical erasure, RSS/peak bound, hard OS deadline or historical PIT is claimed.
SyntheticHTTPSProvider is explicitly a synthetic boundary and never real evidence.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import http.client
import io
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import TracebackType
from urllib.parse import urlsplit

VERSION = "issue36-institutional-five-day-source/v1"
CONSUMER_VERSION = "institutional-five-day-net-summary-two-cutoffs-v1"
POLICY_VERSION = "issue36-tpex-institutional-six-days-two-cutoffs-2026-10-10.1"
POLICY_SHA256 = "93d8e746eccbed035d5a79ffbf178b5f89877017c2aea69e6b841d178c1b51a3"
POLICY_BYTES = 7500
BASE_SHA = "d8918bc6491ec8ef65874979cf88d1322df2da43"
# Runtime identity is never defaulted here: every actor, model and effort value
# comes from the reviewed seal, and the live runtime must match it.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
EFFORT_ENV = "CLAUDE_EFFORT"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
UUID_PATTERN = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
MODEL_PATTERN = r"claude-[a-z0-9][a-z0-9.-]{0,62}"
COMMAND_SWITCHES = " -I -B -X utf8 -c "
COMMAND_MAX_UNITS = 32766  # CreateProcess: 32,767 UTF-16 units including the NUL.
# Historical fixed field of the spent issue #36 qa2 seal ("cwd" must equal it); never a read or write target.
WORKTREE = "C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-36-institutional-five-day-source"
# One-shot source-use quota "qa2", granted by the user in the receipt below (qa1 is SPENT / NO-RETRY and
# is never re-armed). The SHA-256 covers that comment's body as returned by the GitHub API (UTF-8, 1,859 B).
QA_NAMESPACE = "issue36-seven-institutional-five-day-two-cutoffs-v1/qa2"
SOURCE_USE_RECEIPT = "https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110215172"
SOURCE_USE_RECEIPT_SHA256 = "3c5b61b7f79b7e2c238350b51d5329e81b087ef36204141ff185cbb5626619f1"
SOURCE_ID = "tpex_government_institutional_csv"
SOURCE_VERSION = "dataset-11856-dated-csv/issue36-two-cutoffs-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
DATES = ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
WINDOWS = {"2026-10-05": DATES[:5], "2026-10-06": DATES[1:]}
URLS = tuple(
    "https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php"
    "?l=zh-tw&se=EW&t=D&o=data&d=115%2F" + day[5:7] + "%2F" + day[8:10]
    for day in DATES
)
DAILY_HEADER = (
    "資料日期", "代號", "名稱",
    "外資及陸資不含外資自營商買進股數", "外資及陸資不含外資自營商賣出股數", "外資及陸資不含外資自營商買賣超股數",
    "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數",
    "外資及陸資買進股數", "外資及陸資賣出股數", "外資及陸資買賣超股數",
    "投信買進股數", "投信賣出股數", "投信買賣超股數",
    "自營商自行買賣買進股數", "自營商自行買賣賣出股數", "自營商自行買賣買賣超股數",
    "自營商避險買進股數", "自營商避險賣出股數", "自營商避險買賣超股數",
    "自營商買進股數", "自營商賣出股數", "自營商買賣超股數", "三大法人買賣超股數合計",
)
INVESTOR_INDICES = {"foreign": 5, "trust": 14, "dealer": 23}
MAX_INTEGER = 9223372036854775807
BODY_CAP = 1048576
RAW_CAP = 6291456
ROOT_CAP = 33554432
URL_SECONDS = 20
BATCH_SECONDS = 180
CHUNK_BYTES = 16384
# Response headers that carry framing/content identity. Only a repeat of one of
# these is refused; any other repeated header (e.g. Set-Cookie) is ignored.
IDENTITY_HEADERS = ("content-length", "transfer-encoding", "content-encoding", "content-type")
# Explicit supported-estimate allowances for native TLS/HTTP and CSV buffers.
# These are accounting estimates, not bounds on native allocations or peak RSS.
NATIVE_ALLOWANCE = 65536
PARSER_ALLOWANCE = 65536
HANDLE_ALLOWANCE = 512


class SourceError(ValueError):
    """A code-only error. No raw row/body is inserted into diagnostics."""


def _require(condition, code):
    if not condition:
        raise SourceError(code)


def _text(value, pattern, code):
    _require(type(value) is str and re.fullmatch(pattern, value) is not None, code)
    return value


def _bounded(value):
    _require(type(value) is int and abs(value) <= MAX_INTEGER, "integer_overflow")
    return value


def _add(left, right):
    return _bounded(_bounded(left) + _bounded(right))


def _subtract(left, right):
    return _bounded(_bounded(left) - _bounded(right))


def _sum(values):
    total = 0
    for value in values:
        total = _add(total, value)
    return total


def _shares(value, *, gross=False):
    _require(isinstance(value, str) and len(value) <= 20
             and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "share_quantity_invalid")
    number = _bounded(int(value))
    _require(not gross or number >= 0, "negative_buy_or_sell")
    return number


def _market_date(value):
    _require(re.fullmatch(r"[0-9]{7}", value) is not None, "csv_date_invalid")
    try:
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:])).isoformat()
    except ValueError:
        raise SourceError("csv_date_invalid") from None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _json(raw):
    return json.loads(bytes(raw).decode("utf-8", "strict"), object_pairs_hook=_no_duplicate_keys)


def _utc(value):
    _require(isinstance(value, str) and value.endswith("Z"), "utc_invalid")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise SourceError("utc_invalid") from None
    _require(result.utcoffset().total_seconds() == 0, "utc_invalid")
    return result


def _utc_text(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Clock:
    def monotonic(self):
        return time.monotonic()

    def utcnow(self):
        return datetime.now(timezone.utc)


class ExternalPolicy:
    """Only the independently supplied exact external literal is admitted."""

    def __init__(self, raw, *, expected_sha256):
        _require(expected_sha256 == POLICY_SHA256, "external_policy_pin_invalid")
        _require(type(raw) in (bytes, bytearray) and len(raw) == POLICY_BYTES, "policy_length_invalid")
        _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "policy_digest_invalid")
        facts = _json(raw)
        _require(_canonical(facts) == raw, "policy_not_canonical")
        self.raw = bytearray(raw)
        self.facts = facts
        self.released = False

    def validate(self):
        _require(not self.released and len(self.raw) == POLICY_BYTES
                 and hashlib.sha256(self.raw).hexdigest() == POLICY_SHA256, "policy_unavailable")
        _require(_canonical(self.facts) == self.raw, "policy_facts_conflict")


@dataclass(frozen=True)
class ReviewBinding:
    """Independent external review input; never inferred from the old policy actor.

    No field has a default, and no value is taken from this module, the policy or
    the environment: the reviewers supply every field, and each must equal the
    same-named key of the fresh Issue seal (FinancialStartSeal checks that). The
    owner/global verify the values against the QA/engineer Issue receipts before
    this pure validator is invoked.

    Runtime identity (Claude Code, as read back by the QA and recorded in its receipt):
      qa_actual    the QA process's CLAUDE_CODE_SESSION_ID (UUID). validate() compares
                   it with the live environment variable; a missing, empty or
                   different value is refused.
      effort       the QA's CLAUDE_EFFORT (one of EFFORTS), compared the same way.
      model        the ``claude-*`` model id of the assistant entries in the QA
                   transcript. The environment does not carry it, so it is only
                   format-checked here; the owner/global compare it with the receipt.
      runtime_id   UUID of the Orca runtime (``_meta.runtimeId`` of ``orca terminal
                   show --json``); format-checked only.
      terminal_handle  the QA's visible Orca terminal handle (``term_...``).
      global_actual / owner_actual / engineer_actual   session IDs (UUID) of the
                   global coordinator, the task coordinator and the engineer.
    qa_actual, global_actual, owner_actual and engineer_actual are four distinct IDs.

    Binding hashes are lowercase SHA-256 hex over exactly these bytes:
      source_sha256, tests_sha256   the two whitelist files (this module and its test
                   file) as stored in the tree of ``candidate_sha`` (the bytes a clean
                   checkout of that commit has on disk).
      script_sha256   the UTF-8 bytes of the QA payload source text that the loader
                   compiles and executes: the N bytes after the ``QA1 <N> <sha256>``
                   stdin frame header, i.e. the bytes that frame digest covers (the
                   loader hands the same digest to the payload as ``__qa_sha256__``).
      loader_sha256   the UTF-8 bytes of the fixed loader source passed as the single
                   argument after ``-c`` (not the frame, not the payload).
      typed_input_sha256   SHA-256 of ``_canonical(core)``, i.e. ``json.dumps(core,
                   ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")``, where ``core`` is the run
                   descriptor (candidate, file pins and other run parameters) that the
                   QA caller types to the payload besides the script, fixed BEFORE the
                   seal exists.
    command is stored verbatim and not hashed: the QA process command line text,
    ``subprocess.list2cmdline(argv)`` with ``argv = [python, "-I", "-B", "-X", "utf8",
    "-c", loader]`` (what GetCommandLineW() returns in that process). It must fit the
    CreateProcess limit and keep the fixed ``-I -B -X utf8 -c`` switches, so a payload
    can never travel in argv.

    The seal embeds all of these, so none of them may cover the seal raw bytes, the
    seal pin or the receipt URL (that would be circular). Those three are runtime
    inputs of FinancialStartSeal, authenticated by it (digest == pin, receipt URL ==
    seal key and comment-URL form), and the QA caller must deliver them outside the
    script and ``core``. This module never reads files or processes to recompute a hash.
    """

    qa_actual: str
    model: str
    effort: str
    runtime_id: str
    terminal_handle: str
    global_actual: str
    owner_actual: str
    engineer_actual: str
    candidate_sha: str
    source_sha256: str
    tests_sha256: str
    script_sha256: str
    loader_sha256: str
    typed_input_sha256: str
    command: str

    def fields(self):
        return dict(vars(self))

    def check(self):
        """Format and independence rules for a reviewer-supplied binding."""
        ids = ("qa_actual", "runtime_id", "global_actual", "owner_actual", "engineer_actual")
        for name in ids:
            _text(getattr(self, name), UUID_PATTERN, "runtime_identity_invalid")
        _require(self.qa_actual not in (self.global_actual, self.owner_actual, self.engineer_actual),
                 "qa_not_independent")
        _require(len({self.global_actual, self.owner_actual, self.engineer_actual}) == 3,
                 "role_actors_not_distinct")
        _text(self.model, MODEL_PATTERN, "model_invalid")
        _require(type(self.effort) is str and self.effort in EFFORTS, "effort_invalid")
        _text(self.terminal_handle, r"term_.+", "runtime_binding_invalid")
        # A non-blank loader must follow the fixed switches. UTF-16 units are counted
        # arithmetically: a codec lookup would lazily import a module (file I/O).
        _require(type(self.command) is str and bool(self.command.partition(COMMAND_SWITCHES)[2].strip())
                 and len(self.command) + sum(ord(char) > 0xFFFF for char in self.command) <= COMMAND_MAX_UNITS,
                 "command_invalid")
        _text(self.candidate_sha, r"[a-f0-9]{40}", "candidate_invalid")
        for name, value in self.fields().items():
            if name.endswith("sha256"):
                _text(value, r"[a-f0-9]{64}", "candidate_hash_invalid")


class FinancialStartSeal:
    """Validate an already issued seal against a separately fixed external pin.

    There is intentionally no seal producer, default seal, default identity or
    authority derived from policy.admission_authority.global_actual. Passing a pin
    is an external trust boundary, not cryptographic authentication of a GitHub
    actor. The seal carries the global/owner/engineer/QA actors, model and effort
    of ``reviewed``; validate() additionally requires the live process to expose
    the same CLAUDE_CODE_SESSION_ID and CLAUDE_EFFORT. A missing variable is
    refused (never replaced by a default), and so is the legacy Codex thread variable.
    The QA caller must forward the two variables it read from its own Claude
    runtime and must not synthesize them.
    """

    kind = "native_https"

    def __init__(self, raw, *, expected_sha256, receipt_url, reviewed):
        _require(isinstance(reviewed, ReviewBinding), "review_binding_missing")
        _require(re.fullmatch(r"[a-f0-9]{64}", expected_sha256 or "") is not None, "seal_pin_missing")
        _require(re.fullmatch(r"https://github\.com/YiCheng0608/stock-lab/issues/36#issuecomment-[0-9]+",
                             receipt_url or "") is not None, "seal_receipt_invalid")
        _require(type(raw) in (bytes, bytearray) and 0 < len(raw) <= BODY_CAP, "seal_length_invalid")
        _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "seal_digest_invalid")
        facts = _json(raw)
        fixed = {
            "schema": "stock-lab-financial-start-seal/v1", "issue": 36,
            "base_sha": BASE_SHA,
            "namespace": QA_NAMESPACE, "policy_sha256": POLICY_SHA256,
            "source_use_receipt": SOURCE_USE_RECEIPT, "source_use_receipt_sha256": SOURCE_USE_RECEIPT_SHA256,
            "cwd": WORKTREE, "parent_thread_id": None,
            "urls": list(URLS), "dates": list(DATES), "symbols": list(SYMBOLS),
            "body_bytes": BODY_CAP, "aggregate_raw_bytes": RAW_CAP, "retained_estimate_bytes": ROOT_CAP,
            "per_url_seconds": URL_SECONDS, "batch_seconds": BATCH_SECONDS,
            "requests": 6, "per_url_attempts": 1, "redirects": 0, "retries": 0,
            "metadata_requests": 0, "calendar_requests": 0, "artifacts_bytes": 0,
            "accept_encoding": "identity", "credentials": False, "token": False, "cookie": False, "proxy": False,
            "receipt_url": receipt_url,
        }
        _require(set(facts) == set(fixed) | set(reviewed.fields()) | {"issued_at", "expires_at"}, "seal_fields_invalid")
        _require(all(facts[key] == value for key, value in fixed.items()), "seal_scope_conflict")
        _require(all(facts[key] == value for key, value in reviewed.fields().items()), "seal_review_conflict")
        _require(_canonical(facts) == raw, "seal_not_canonical")
        reviewed.check()
        self.issued_at = _utc(facts["issued_at"])
        self.expires_at = _utc(facts["expires_at"])
        _require(self.issued_at < self.expires_at, "seal_interval_invalid")
        self.raw = bytearray(raw)
        self.facts = facts
        self.sha256 = expected_sha256
        self.reviewed = reviewed
        self.spent = set()
        self.started = False

    def validate(self, clock):
        _require(self.raw and hashlib.sha256(self.raw).hexdigest() == self.sha256
                 and _canonical(self.facts) == self.raw, "seal_unavailable")
        _require(self.issued_at <= clock.utcnow() < self.expires_at, "seal_expired_or_pending")
        # The live Claude runtime must be the reviewed one. No default is ever used.
        session, effort = os.environ.get(SESSION_ENV), os.environ.get(EFFORT_ENV)
        _require(bool(session) and bool(effort), "runtime_env_missing")
        _require(session == self.reviewed.qa_actual, "actual_binding_conflict")
        _require(effort == self.reviewed.effort, "runtime_effort_conflict")
        _require(not self.started, "seal_already_spent")


class SyntheticAuthorization:
    """RAM boundary only. This is never a financial-start seal."""

    kind = "synthetic_boundary"

    def __init__(self, namespace, *, expires_at):
        _require(namespace.startswith("synthetic:") and namespace != QA_NAMESPACE, "synthetic_namespace_invalid")
        self.namespace = namespace
        self.expires_at = expires_at
        self.started = False
        self.spent = set()

    def validate(self, clock):
        _require(clock.utcnow() < self.expires_at, "synthetic_expired")
        _require(not self.started, "synthetic_already_spent")


class HTTPSProvider:
    kind = "native_https"

    def connection(self, host, timeout):
        # HTTPSConnection connects lazily. No urllib proxy/cookie/auth machinery.
        return http.client.HTTPSConnection(host, timeout=timeout)

    def roots(self):
        return []


class SyntheticHTTPSProvider:
    kind = "synthetic_boundary"

    def __init__(self, factory, *, roots):
        self.factory = factory
        # Factory closures are unsupported roots: explicitly declare their data.
        self.holders = roots

    def connection(self, host, timeout):
        return self.factory(host, timeout)

    def roots(self):
        return [self.holders]


def _children(value):
    if isinstance(value, dict):
        return tuple(value.keys()) + tuple(value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    if isinstance(value, memoryview):
        return (value.obj,)
    if isinstance(value, BaseException):
        return (value.args, value.__cause__, value.__context__, value.__traceback__, vars(value))
    if isinstance(value, TracebackType):
        # Traceback frames are cleared separately; active caller lexical scopes
        # must declare their aliases and exit. No locals snapshot is retained.
        return (value.tb_next,)
    if type(value) in (str, bytes, bytearray, int, bool, float, type(None)):
        return ()
    raise SourceError("unsupported_root_type")


def _graph(roots):
    seen, nodes = set(), []
    stack = list(roots)
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        nodes.append(value)
        stack.extend(_children(value))
    return nodes


class SupportedRoots:
    """Deduplicated supported-object graph, with actual in-place revocation."""

    def __init__(self):
        self.holders = {}

    def declare(self, name, holder):
        _require(isinstance(name, str) and name and name not in self.holders, "root_name_invalid")
        _require(isinstance(holder, (dict, list, set, bytearray, memoryview, BaseException)), "mutable_root_required")
        _graph([holder])  # Validate the graph before accepting responsibility.
        self.holders[name] = holder

    def _adopt_initial(self, name, holder):
        # Constructor ownership includes supported siblings of a rejected graph.
        # Retain the mutable holder before validation so failure cleanup can walk
        # it all-attempt, recording unsupported nodes rather than skipping it.
        _require(isinstance(name, str) and name and name not in self.holders, "root_name_invalid")
        _require(isinstance(holder, (dict, list, set, bytearray, memoryview, BaseException)), "mutable_root_required")
        self.holders[name] = holder
        _graph([holder])

    def estimate(self, *, allowance=0):
        nodes = _graph([self.holders])
        # Active caller lexical aliases must be declared separately. Native
        # traceback/frame overhead has a stated estimate allowance; inactive
        # frame locals are cleared before releasing backing stores.
        return allowance + sum(sys.getsizeof(value) for value in nodes) + NATIVE_ALLOWANCE * sum(
            isinstance(value, TracebackType) for value in nodes)

    def release(self):
        failures = []
        try:
            nodes = _graph([self.holders])
        except Exception:
            # Do not skip supported siblings if a caller mutated in an unsupported
            # object after declaration. Walk every supported node independently.
            nodes, stack, seen = [], [self.holders], set()
            while stack:
                value = stack.pop()
                if id(value) in seen:
                    continue
                seen.add(id(value))
                nodes.append(value)
                try:
                    stack.extend(_children(value))
                except Exception:
                    failures.append("unsupported_root_type")
        # Clear inactive traceback frames first, including views reachable only
        # from their locals. Keep the collected graph so args/cause/context and
        # separately declared aliases still get explicit revocation below.
        for value in nodes:
            if isinstance(value, TracebackType):
                try:
                    traceback.clear_frames(value)
                except Exception:
                    failures.append("traceback_clear_failed")
        for value in nodes:
            if isinstance(value, memoryview):
                try:
                    value.release()
                except Exception:
                    failures.append("view_release_failed")
        for value in nodes:
            try:
                if isinstance(value, bytearray):
                    # Revocation is emptiness/backing release, not physical wipe.
                    value.clear()
                elif isinstance(value, (dict, list, set)):
                    value.clear()
                elif isinstance(value, BaseException):
                    if value.__traceback__ is not None:
                        traceback.clear_frames(value.__traceback__)
                    value.__traceback__ = value.__cause__ = value.__context__ = None
                    value.args = ()
                    vars(value).clear()
            except Exception:
                failures.append("root_release_failed")
        self.holders.clear()
        return tuple(failures)


class ResultHandle:
    def __init__(self, owner, payload):
        self._owner = owner
        self._payload = payload

    @property
    def value(self):
        _require(self._owner is not None, "result_revoked")
        self._owner._available()
        return self._payload

    def revoke(self):
        self._owner = None
        self._payload.clear()


class _MemoryReader(io.RawIOBase):
    def __init__(self, body):
        super().__init__()
        self.view = memoryview(body)
        self.offset = 0

    def readable(self):
        return True

    def readinto(self, target):
        count = min(len(target), len(self.view) - self.offset)
        target[:count] = self.view[self.offset:self.offset + count]
        self.offset += count
        return count

    def close(self):
        try:
            self.view.release()
        finally:
            super().close()


def _fail_closed(method):
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            code = str(exc) if isinstance(exc, SourceError) else "source_failure:" + type(exc).__name__
            self._discard_error(exc)
            if self.state not in ("pending", "failed", "expired", "released"):
                self.failure_code = code
                self._cleanup("failed")
            raise SourceError(code) from None
    return guarded


class RAMCapture:
    """One attempt, all-six availability, managed roots and revocable results."""

    def __init__(self, policy, authorization=None, *, provider=None, clock=None):
        self.policy = policy
        self.authorization = authorization
        self.provider = HTTPSProvider() if provider is None else provider
        _require(type(self.provider) in (HTTPSProvider, SyntheticHTTPSProvider), "provider_not_supported")
        _require(clock is None or type(self.provider) is SyntheticHTTPSProvider, "native_clock_override_forbidden")
        self.clock = Clock() if clock is None else clock
        self.state = "pending"
        self.failure_code = None
        self.attempts = []  # Non-raw outcome metadata; attempted always SPENT.
        self.originals = []
        self.selected = {}
        self._row_pins = {}
        self.results = []
        self.resources = []
        self.roots = SupportedRoots()
        self.cleanup_failures = ()
        self.raw_bytes = 0
        self.batch_start = None
        try:
            self.roots._adopt_initial("capture", self.originals)
            self.roots._adopt_initial("parser", self.selected)
            self.roots._adopt_initial("selected_integrity", self._row_pins)
            if isinstance(policy, ExternalPolicy):
                self.roots._adopt_initial("policy_raw", policy.raw)
                self.roots._adopt_initial("policy", policy.facts)
            if isinstance(authorization, FinancialStartSeal):
                self.roots._adopt_initial("seal_raw", authorization.raw)
                self.roots._adopt_initial("seal", authorization.facts)
            for index, holder in enumerate(self.provider.roots()):
                self.roots._adopt_initial("synthetic_provider_" + str(index), holder)
            self._limit()
        except BaseException as exc:
            code = str(exc) if isinstance(exc, SourceError) else "source_failure:" + type(exc).__name__
            if code == "retained_estimate_cap":
                code = "constructor_retained_estimate_cap"
            self.failure_code = code
            self._discard_error(exc)
            self._cleanup("failed")
            failure = SourceError(code)
            failure.cleanup_failures = self.cleanup_failures
            raise failure from None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.declare_root("scope_error_chain", exc)
        self.close()
        return False

    def _limit(self, *, extra=0):
        allowance = PARSER_ALLOWANCE + NATIVE_ALLOWANCE * len(self.resources) + HANDLE_ALLOWANCE * len(self.results)
        _require(self.roots.estimate(allowance=allowance) + extra <= ROOT_CAP, "retained_estimate_cap")

    def declare_root(self, name, holder):
        _require(self.state != "released", "root_scope_released")
        try:
            self.roots.declare(name, holder)
            self._limit()
        except Exception:
            self._cleanup("failed")
            raise SourceError("root_declaration_failed") from None
        return holder

    def supported_roots(self):
        return tuple(self.roots.holders)

    def retained_estimate(self):
        return self.roots.estimate(allowance=PARSER_ALLOWANCE + NATIVE_ALLOWANCE * len(self.resources)
                                  + HANDLE_ALLOWANCE * len(self.results))

    def _remaining(self, started):
        now = self.clock.monotonic()
        remaining = min(URL_SECONDS - (now - started), BATCH_SECONDS - (now - self.batch_start))
        _require(remaining > 0, "cooperative_deadline")
        _require(self.clock.utcnow() < self.authorization.expires_at, "authorization_expired")
        return remaining

    def _batch_check(self):
        _require(self.clock.monotonic() - self.batch_start < BATCH_SECONDS, "cooperative_batch_deadline")
        _require(self.clock.utcnow() < self.authorization.expires_at, "authorization_expired")

    def _timeout(self, connection, started):
        remaining = self._remaining(started)
        connection.timeout = remaining
        if getattr(connection, "sock", None) is not None:
            connection.sock.settimeout(remaining)
        return remaining

    def _close_attempt(self, resource):
        self._disable_observers()
        failures = []
        for key in ("response", "connection"):
            obj = resource.get(key)
            if obj is not None:
                try:
                    obj.close()
                    resource[key] = None
                except Exception:
                    failures.append(key + "_close_failed")
        return failures

    def _fetch(self, ordinal):
        url, expected_date = URLS[ordinal], DATES[ordinal]
        _require(url not in self.authorization.spent and len(self.attempts) < 6, "attempt_spent")
        self.authorization.spent.add(url)
        outcome = {"url": url, "date": expected_date, "spent": True, "completed": False}
        self.attempts.append(outcome)
        started = self.clock.monotonic()
        request_utc = self.clock.utcnow()
        resource = {"connection": None, "response": None}
        self.resources.append(resource)
        original = {"body": bytearray(), "receipt": bytearray(), "receipt_sha256": None}
        self.originals.append(original)
        connection = response = None
        try:
            parts = urlsplit(url)
            connection = self.provider.connection(parts.hostname, self._remaining(started))
            resource["connection"] = connection
            self._timeout(connection, started)
            connection.connect()
            self._timeout(connection, started)
            connection.request("GET", parts.path + "?" + parts.query, headers={
                "Accept": "text/csv", "Accept-Encoding": "identity", "Connection": "close",
                "User-Agent": "stock-lab-issue36-local-ram/1",
            })
            self._timeout(connection, started)
            response = connection.getresponse()
            resource["response"] = response
            self._remaining(started)
            _require(response.status == 200, "http_status_rejected")
            headers = response.getheaders()
            normalized = {}
            for key, value in headers:
                key = key.lower()
                if key in IDENTITY_HEADERS:  # Failure code carries the fixed name only, never the value.
                    _require(key not in normalized, "duplicate_response_header:" + key)
                    normalized[key] = value
            _require(normalized.get("content-encoding", "identity").lower() == "identity", "encoding_rejected")
            content_type = normalized.get("content-type", "")
            mime = [part.strip().lower() for part in content_type.split(";")]
            _require(mime[0] in ("text/csv", "application/csv") and all(
                part in ("charset=utf-8", 'charset="utf-8"') for part in mime[1:]), "content_type_rejected")
            length_text = normalized.get("content-length")
            transfer = normalized.get("transfer-encoding")
            _require(not (length_text is not None and transfer is not None), "ambiguous_framing")
            _require(transfer is None or transfer.lower() == "chunked", "transfer_encoding_rejected")
            length = None
            if length_text is not None:
                _require(re.fullmatch(r"(?:0|[1-9][0-9]*)", length_text) is not None, "content_length_invalid")
                length = int(length_text)
                _require(0 < length <= BODY_CAP and length <= RAW_CAP - self.raw_bytes, "declared_length_cap")
                _require(getattr(response, "length", None) == length and not response.chunked, "framing_identity_conflict")
            elif transfer == "chunked":
                _require(response.chunked, "framing_identity_conflict")
            else:
                _require(not response.chunked, "framing_identity_conflict")
            body = original["body"]
            eof = False
            while not eof:
                body_remaining = BODY_CAP - len(body)
                aggregate_remaining = RAW_CAP - self.raw_bytes
                _require(body_remaining > 0 and aggregate_remaining > 0, "unknown_length_at_cap")
                amount = min(CHUNK_BYTES, body_remaining, aggregate_remaining)
                if length is not None:
                    amount = min(amount, length - len(body))
                _require(amount > 0, "read_zero_forbidden")
                self._limit(extra=amount * 2)  # read result and bytearray growth scratch
                self._timeout(connection, started)
                chunk = response.read(amount)
                self._remaining(started)
                _require(type(chunk) is bytes and len(chunk) <= amount, "read_contract_invalid")
                body.extend(chunk)
                self.raw_bytes += len(chunk)
                if length is not None:
                    if len(body) == length:
                        _require(response.length == 0, "framing_eof_missing")
                        eof = True  # Existing Content-Length framing; no extra read.
                    elif not chunk:
                        raise SourceError("premature_eof")
                elif not chunk:
                    _require(response.isclosed(), "framing_eof_missing")
                    eof = True
                elif response.isclosed():
                    eof = True  # Existing connection/chunk parser EOF evidence.
                chunk = None
                self._limit()
            _require(bool(body), "empty_body")
            self._validate_utf8(body)
            self._remaining(started)
            captured_utc = self.clock.utcnow()
            _require(request_utc <= captured_utc, "capture_time_invalid")
            receipt = {
                "schema": "stock-lab-issue36-original-receipt/v1", "kind": self.provider.kind,
                "module_version": VERSION, "policy_version": POLICY_VERSION, "policy_sha256": POLICY_SHA256,
                "source_id": SOURCE_ID, "source_version": SOURCE_VERSION, "url": url, "method": "GET",
                "requested_date": expected_date, "status": response.status, "headers": [list(h) for h in headers],
                "content_type": content_type, "content_encoding": "identity", "framing": "length" if length is not None else (
                    "chunked" if response.chunked else "connection_eof"), "declared_length": length,
                "complete_eof": True, "body_length": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                "request_utc": _utc_text(request_utc), "capture_utc": _utc_text(captured_utc),
                "namespace": self.authorization.namespace if isinstance(self.authorization, SyntheticAuthorization) else QA_NAMESPACE,
            }
            original["receipt"].extend(_canonical(receipt))
            original["receipt_sha256"] = hashlib.sha256(original["receipt"]).hexdigest()
            outcome["completed"] = True
            self._limit()
        finally:
            errors = self._close_attempt(resource)
            if errors:
                outcome["close_failures"] = list(errors)
                if sys.exc_info()[0] is None:
                    raise SourceError("transport_close_failed") from None

    def _validate_utf8(self, body):
        _require(not body.startswith(codecs.BOM_UTF8), "bom_rejected")
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        view = memoryview(body)
        try:
            for offset in range(0, len(body), CHUNK_BYTES):
                decoder.decode(view[offset:offset + CHUNK_BYTES], final=False)
            decoder.decode(b"", final=True)
        except UnicodeError:
            raise SourceError("utf8_invalid") from None
        finally:
            self._disable_observers()
            view.release()
            decoder.reset()

    def _original(self, ordinal):
        original = self.originals[ordinal]
        body, receipt_raw = original["body"], original["receipt"]
        _require(hashlib.sha256(receipt_raw).hexdigest() == original["receipt_sha256"], "receipt_digest_conflict")
        receipt = _json(receipt_raw)
        _require(_canonical(receipt) == receipt_raw, "receipt_not_canonical")
        _require(receipt["url"] == URLS[ordinal] and receipt["requested_date"] == DATES[ordinal]
                 and receipt["method"] == "GET" and receipt["kind"] == self.provider.kind
                 and receipt["source_id"] == SOURCE_ID and receipt["source_version"] == SOURCE_VERSION
                 and receipt["policy_sha256"] == POLICY_SHA256 and receipt["policy_version"] == POLICY_VERSION
                 and receipt["module_version"] == VERSION and receipt["complete_eof"] is True
                 and receipt["status"] == 200 and receipt["content_encoding"] == "identity", "receipt_identity_conflict")
        _require(receipt["body_length"] == len(body) and 0 < len(body) <= BODY_CAP
                 and receipt["body_sha256"] == hashlib.sha256(body).hexdigest(), "body_digest_conflict")
        _require(receipt["framing"] in ("length", "chunked", "connection_eof"), "receipt_framing_invalid")
        _require(receipt["declared_length"] is None or receipt["declared_length"] == len(body), "receipt_length_conflict")
        _require(_utc(receipt["request_utc"]) <= _utc(receipt["capture_utc"]) <= self.clock.utcnow(), "receipt_time_invalid")
        self._validate_utf8(body)
        return receipt

    def _parse(self, ordinal):
        receipt = self._original(ordinal)
        scratch = {"seen": set(), "row": [], "numbers": []}
        self.roots.declare("parser_scratch", scratch)
        raw = _MemoryReader(self.originals[ordinal]["body"])
        self.roots.declare("parser_view", raw.view)
        text = io.TextIOWrapper(io.BufferedReader(raw, buffer_size=8192), encoding="utf-8", errors="strict", newline="")
        try:
            reader = csv.reader(text, strict=True)
            _require(tuple(next(reader, ())) == DAILY_HEADER, "header_invalid")
            selected = {}
            self.selected[DATES[ordinal]] = selected
            for position, row in enumerate(reader, start=2):
                scratch["row"] = row
                _require(len(row) == 25, "row_width_invalid")
                source_date = _market_date(row[0])
                _require(source_date == DATES[ordinal], "source_date_conflict")
                _require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None, "code_invalid")
                _require(row[1] not in scratch["seen"], "duplicate_code")
                scratch["seen"].add(row[1])
                _require(bool(row[2].strip()), "name_empty")
                if row[1] in SYMBOLS:
                    numbers = [_shares(row[index], gross=index in (3, 4, 6, 7, 9, 10, 12, 13, 15, 16, 18, 19, 21, 22))
                               for index in range(3, 25)]
                    scratch["numbers"] = numbers
                    for offset in (3, 6, 9, 12, 15, 18, 21):
                        _require(numbers[offset - 1] == _subtract(numbers[offset - 3], numbers[offset - 2]), "daily_net_mismatch")
                    for first, second, total in ((3, 6, 9), (15, 18, 21)):
                        for metric in range(3):
                            _require(_add(numbers[first - 3 + metric], numbers[second - 3 + metric])
                                     == numbers[total - 3 + metric], "daily_component_mismatch")
                    _require(_sum(numbers[index - 3] for index in INVESTOR_INDICES.values()) == numbers[21], "daily_total_mismatch")
                    selected[row[1]] = {
                        "symbol": row[1], "name": row[2], "date": source_date, "source_date": row[0], "row_ordinal": position,
                        "original_fields": row, "header": list(DAILY_HEADER), "financial_integers": numbers,
                        "unit": "shares", "source_id": SOURCE_ID, "source_version": SOURCE_VERSION,
                        "policy_version": POLICY_VERSION, "policy_sha256": POLICY_SHA256, "module_version": VERSION,
                        "capture_utc": receipt["capture_utc"], "url": receipt["url"],
                        "body_sha256": receipt["body_sha256"], "receipt_sha256": self.originals[ordinal]["receipt_sha256"],
                    }
                    self._row_pins[(DATES[ordinal], row[1])] = hashlib.sha256(_canonical(selected[row[1]])).hexdigest()
                scratch["row"] = []
                scratch["numbers"] = []
                self._limit()
            _require(set(selected) == set(SYMBOLS), "selected_missing")
        finally:
            self._disable_observers()
            text.close()
            scratch.clear()
            self.roots.holders.pop("parser_scratch", None)
            self.roots.holders.pop("parser_view", None)

    def capture(self):
        _require(self.state == "pending", "capture_not_pending")
        try:
            _require(isinstance(self.policy, ExternalPolicy), "policy_missing")
            self.policy.validate()
            expected = FinancialStartSeal if type(self.provider) is HTTPSProvider else SyntheticAuthorization
            _require(type(self.authorization) is expected, "authorization_missing_or_kind_conflict")
            self.authorization.validate(self.clock)
            self.authorization.started = True
            self.state = "capturing"
            self.batch_start = self.clock.monotonic()
            for ordinal in range(6):
                self._fetch(ordinal)
            _require(self.raw_bytes == sum(len(item["body"]) for item in self.originals) <= RAW_CAP, "aggregate_conflict")
            # All six EOF/identity/UTF8/digests checked BEFORE any source parse.
            for ordinal in range(6):
                self._original(ordinal)
            for ordinal in range(6):
                self._parse(ordinal)
                self._batch_check()
            _require(set(self.selected) == set(DATES), "all_six_required")
            self._limit()
            self.state = "available"
        except BaseException as exc:
            self.failure_code = str(exc) if isinstance(exc, SourceError) else "source_failure:" + type(exc).__name__
            # Remove inactive parser/transport frames and exception chains; never
            # return the original exception/raw-bearing traceback to the caller.
            self._discard_error(exc)
            self._cleanup("failed")
        return self

    @_fail_closed
    def _available(self):
        if self.state == "available" and self.clock.utcnow() >= self.authorization.expires_at:
            self._cleanup("expired")
        _require(self.state == "available", "profile_unavailable:" + self.state)
        self.policy.validate()
        self._batch_check()
        _require(set(self.selected) == set(DATES) and len(self._row_pins) == 42, "selected_integrity_conflict")
        for ordinal, day in enumerate(DATES):
            self._original(ordinal)
            _require(set(self.selected[day]) == set(SYMBOLS), "selected_integrity_conflict")
            for symbol in SYMBOLS:
                _require(hashlib.sha256(_canonical(self.selected[day][symbol])).hexdigest()
                         == self._row_pins[(day, symbol)], "selected_integrity_conflict")
        self._batch_check()
        self._limit()

    def _handle(self, name, payload):
        self.declare_root(name + ":" + str(len(self.results)), payload)
        handle = ResultHandle(self, payload)
        self.results.append(handle)
        self._limit()
        return handle

    @_fail_closed
    def profile(self):
        self._available()
        return self._handle("profile", {
            "available": True, "kind": self.provider.kind, "market": "TPEx", "instrument": "ordinary_stock",
            "symbols": list(SYMBOLS), "dates": list(DATES), "cutoffs": list(WINDOWS), "unit": "shares",
            "selected_rows": 42, "original_strings": 1050, "financial_integers": 924,
            "source_id": SOURCE_ID, "source_version": SOURCE_VERSION, "policy_version": POLICY_VERSION,
            "policy_sha256": POLICY_SHA256, "module_version": VERSION, "consumer_version": CONSUMER_VERSION,
            "attribution": self.policy.facts["rights"]["attribution"],
            "unsupported": list(self.policy.facts["unsupported"]),
        })

    @_fail_closed
    def getter(self, symbol):
        self._available()
        _require(symbol in SYMBOLS, "symbol_not_admitted")
        for ordinal in range(6):
            self._original(ordinal)
        return self._handle("getter", {
            "symbol": symbol, "kind": self.provider.kind, "unit": "shares",
            "dates": list(DATES), "rows": [self.selected[day][symbol] for day in DATES],
            "policy_sha256": POLICY_SHA256, "module_version": VERSION,
            "attribution": self.policy.facts["rights"]["attribution"], "historical_pit": "unsupported",
        })

    @_fail_closed
    def consumer(self, symbol, cutoff):
        self._available()
        _require(symbol in SYMBOLS and cutoff in WINDOWS, "consumer_scope_invalid")
        days = WINDOWS[cutoff]
        for ordinal in range(6):
            self._original(ordinal)
        rows = [self.selected[day][symbol] for day in days]
        sums = {key: str(_sum(_shares(row["original_fields"][index]) for row in rows))
                for key, index in INVESTOR_INDICES.items()}
        total = _sum(_shares(sums[key]) for key in INVESTOR_INDICES)
        _require(total == _sum(_shares(row["original_fields"][24]) for row in rows), "window_total_conflict")
        return self._handle("consumer", {
            "symbol": symbol, "cutoff": cutoff, "inclusive": True, "dates": list(days), "source_rows": rows,
            "kind": self.provider.kind, "unit": "shares", "category_net": sums, "total_net": str(total),
            "policy_sha256": POLICY_SHA256, "policy_version": POLICY_VERSION, "module_version": VERSION,
            "consumer_version": CONSUMER_VERSION, "attribution": self.policy.facts["rights"]["attribution"],
            "denominator": "unsupported", "amount": "unsupported", "strategy": "unsupported", "historical_pit": "unsupported",
        })

    @_fail_closed
    def original_view(self, ordinal, *, receipt=False):
        self._available()
        _require(type(ordinal) is int and 0 <= ordinal < 6, "original_scope_invalid")
        self._original(ordinal)
        view = memoryview(self.originals[ordinal]["receipt" if receipt else "body"]).toreadonly()
        self.declare_root("original_view:" + str(len(self.roots.holders)), view)
        return view

    def _disable_observers(self):
        failures = []
        for operation in (sys.settrace, sys.setprofile):
            try:
                operation(None)
            except Exception:
                failures.append("trace_profile_disable_failed")
        self.cleanup_failures = tuple(dict.fromkeys(self.cleanup_failures + tuple(failures)))

    def _discard_error(self, exc):
        self._disable_observers()
        try:
            if exc.__traceback__ is not None:
                traceback.clear_frames(exc.__traceback__)
        except Exception:
            self.cleanup_failures = tuple(dict.fromkeys(self.cleanup_failures + ("traceback_clear_failed",)))
        exc.__traceback__ = exc.__cause__ = exc.__context__ = None

    def _cleanup(self, final_state):
        # Disable before the first transport/frame/view/backing release, including
        # constructor failure and caller audit/output finally. Earlier local
        # finally blocks use the same boundary before releasing their resources.
        self._disable_observers()
        failures = []
        for resource in self.resources:
            failures.extend(self._close_attempt(resource))
        failures.extend(self.roots.release())
        for handle in self.results:
            try:
                handle.revoke()
            except Exception:
                failures.append("result_revoke_failed")
        self.results.clear()
        self.originals.clear()
        self.selected.clear()
        self._row_pins.clear()
        self.resources.clear()
        if isinstance(self.policy, ExternalPolicy):
            self.policy.released = True
        self.raw_bytes = 0
        self.state = final_state
        # Idempotent close must never erase an earlier unsuccessful release.
        self.cleanup_failures = tuple(dict.fromkeys(self.cleanup_failures + tuple(failures)))
        return self.cleanup_failures

    def close(self):
        return self._cleanup("released")


def run_in_ram(capture, action, *, audit=None, output=None):
    """Run caller oracle/getters/consumers under one finally, including I/O errors.

    The caller registers its complete mutable state and aliases before using raw
    evidence. action/audit/output are not kept by capture; their lexical scopes
    must finish and the QA process must exit. Returned managed payloads are
    revoked on this function's return. No source data is printed here.
    """
    try:
        capture.capture()
        capture._available()
        result = action(capture)
        capture._available()
        if audit is not None:
            audit(result)
            capture._available()
        if output is not None:
            output(result)
            capture._available()
        return result
    except BaseException as exc:
        capture.declare_root("run_error_chain", exc)
        raise
    finally:
        capture.close()
