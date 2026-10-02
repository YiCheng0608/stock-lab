"""Explicit, bounded source capture. Independent from application/DB imports.

Run ``python -m worker.source_runtime capture --help``. A successful output is
one capture.zip containing body.bin and receipt.json. body.bin is the HTTP
entity body after transfer framing, before content decoding; non-identity
Content-Encoding is rejected. No parsing/re-encoding changes the saved bytes.
This is a per-invocation control, not a cross-process rate limiter.
``capture_memory`` shares the same fetch controls but returns bytes in memory;
its separate receipt schema does not claim a durable artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any
import zipfile

from .source_registry import MIN_CONDITIONS, RegistryError, decide_policy, load_manifest


ENDPOINTS = {
    "twse_stock_day_all": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "twse_holiday_schedule": "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
    "twse_twt48u_all": "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
    "tpex_spendi_history": "https://www.tpex.org.tw/openapi/v1/tpex_spendi_history",
    "tpex_3insti_daily_trading": "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_BODY_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 15.0
DEADLINE_SECONDS = 30.0


class CaptureError(ValueError):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _output_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser().resolve()
    if candidate == PROJECT_ROOT or candidate.is_relative_to(PROJECT_ROOT):
        raise CaptureError("output_inside_project")
    if candidate.exists():
        if not candidate.is_dir() or any(candidate.iterdir()):
            raise CaptureError("output_not_empty_directory")
    elif not candidate.parent.is_dir():
        raise CaptureError("output_parent_missing")
    return candidate


def _publish(output: Path, body: bytes, receipt: dict[str, Any]) -> None:
    """Publish a complete ZIP via an exclusive hard link, never replacement.

    Staging is a unique file. Link creation is atomic and fails if capture.zip
    already exists. Filesystems without hard links fail closed. Only our own
    staging/lock files are removed on failure; external files are untouched.
    """
    if _output_path(output) != output:
        raise CaptureError("output_path_changed")
    made_dir = False
    lock = None
    stage = None
    try:
        if not output.exists():
            output.mkdir()
            made_dir = True
        lock = output / ".capture.lock"
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(lock_fd)
    except Exception:
        # A competing lock is not owned by us.
        if made_dir:
            try:
                output.rmdir()
            except OSError:
                pass
        raise
    try:
        if list(output.iterdir()) != [lock]:
            raise CaptureError("output_conflict")
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("body.bin", body)
            archive.writestr("receipt.json", json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
        fd, name = tempfile.mkstemp(prefix=".capture-", suffix=".tmp", dir=output)
        stage = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(memory.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        if set(output.iterdir()) != {lock, stage}:
            raise CaptureError("output_conflict")
        os.link(stage, output / "capture.zip")
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
        if made_dir:
            try:
                output.rmdir()  # only removes our directory when empty
            except OSError:
                pass


def _capture(
    *,
    manifest: str | Path,
    profile: str,
    source_id: str,
    expected_registry_version: str,
    expected_digest: str,
    output_dir: str | Path | None = None,
    transport: Any = None,
    memory_only: bool = False,
) -> tuple[bytes | None, dict[str, Any]]:
    """Shared policy, request and receipt engine; storage is explicit."""
    body = None
    receipt: dict[str, Any] = {
        "schema_version": "source-memory-capture/v1" if memory_only else "source-capture/v1",
        "status": "rejected",
        "source_id": source_id,
        "request_count": 0,
        "http_status": None,
        "retry_after": None,
        "rate_limit_verified": False,
        "documented_numeric_rate_limit": "not_evaluated",
        "rate_limit_scope": "one invocation; no cross-process enforcement",
        "error_reason": None,
    }
    if memory_only:
        receipt["storage"] = "memory_only"
    try:
        if not expected_registry_version or not expected_digest or not profile or (memory_only and not manifest):
            raise CaptureError("explicit_pins_and_profile_required")
        if memory_only and source_id != "twse_twt48u_all":
            raise CaptureError("memory_source_not_supported")
        if source_id not in ENDPOINTS:
            raise CaptureError("source_not_supported")
        selected = load_manifest(manifest, expected_registry_version=expected_registry_version, expected_digest=expected_digest)
        source = next((item for item in selected["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise CaptureError("source_missing")
        receipt["rate_limit_evidence"] = source["access"]["rate_limit"]
        receipt["documented_numeric_rate_limit"] = source["access"]["rate_limit"]["status"]
        endpoint = ENDPOINTS[source_id]
        if source["exact_url"] != endpoint or source["method"] != "GET":
            raise CaptureError("endpoint_or_method_mismatch")
        decisions = {}
        for purpose in ("local_fetch", "raw_store"):
            decision = decide_policy(selected, source_id, purpose, profile=profile, endpoint=endpoint, method="GET")
            decisions[purpose] = decision.to_dict()
            if not decision.allowed:
                raise CaptureError(f"purpose_not_allowed:{purpose}")
            if set(decision.conditions) != MIN_CONDITIONS[purpose]:
                raise CaptureError(f"unimplemented_conditions:{purpose}")
        receipt["policy_decisions"] = decisions
        # Current executor understands no numeric quota syntax. A known quota
        # must never silently inherit this unknown-quota operational policy.
        if source["access"]["rate_limit"]["status"] != "unknown":
            raise CaptureError("documented_rate_limit_not_supported")
        output = None if memory_only else _output_path(output_dir)
        receipt.update({
            "endpoint": endpoint,
            "method": "GET",
            "profile": profile,
            "registry_version": selected["registry_version"],
            "manifest_digest": selected["content_digest"],
            "source_version": source["source_version"],
            "attribution": {
                "owner": source["owner"], "dataset_id": source["dataset_id"],
                "source_id": source_id, "source_url": endpoint,
                "terms": source["access"]["documented_terms"],
                "evidence": source["evidence"],
                "purpose_evidence": {p: source["purposes"][p]["evidence"] for p in decisions},
            },
            "condition_receipts": {
                "bounded_requests": {"max_requests": 1, "per_operation_timeout_seconds": TIMEOUT_SECONDS, "cooperative_deadline_seconds": DEADLINE_SECONDS, "deadline_scope": "checked between streamed chunks; not a hard total deadline", "max_body_bytes": MAX_BODY_BYTES},
                "respect_endpoint_limits": {"strategy": "single_get_stop_on_response", "retries": 0, "redirects": 0, "warmup_requests": 0, "numeric_quota_verified": False},
                "attribute_source": {"artifact": "memory:receipt.attribution" if memory_only else "receipt.json:attribution"},
                "preserve_source_integrity": {"artifact": "memory:body" if memory_only else "body.bin", "encoding": "identity HTTP entity bytes after transfer framing; no content decoding or JSON re-encoding"},
            },
            "executed_purposes": ["local_fetch", "raw_store"],
            "historical_pit": "unsupported",
        })
        import httpx

        chunks = bytearray()
        # trust_env=False disables ambient proxies, netrc/auth and CA overrides.
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            receipt["status"] = "capture_failed"
            receipt["request_started_at"] = _utc()
            started = time.monotonic()
            receipt["request_count"] = 1
            with client.stream("GET", endpoint, headers={"Accept-Encoding": "identity", "User-Agent": "taiwan-stock-research/source-capture-v1"}) as response:
                receipt["http_status"] = response.status_code
                receipt["retry_after"] = response.headers.get("Retry-After")
                if not 200 <= response.status_code < 300:
                    raise CaptureError(f"http_status:{response.status_code}")
                if response.headers.get("Content-Encoding", "identity").strip().lower() not in {"", "identity"}:
                    raise CaptureError("unsupported_content_encoding")
                for chunk in response.iter_raw():
                    if time.monotonic() - started > DEADLINE_SECONDS:
                        raise CaptureError("request_deadline_exceeded")
                    if len(chunks) + len(chunk) > MAX_BODY_BYTES:
                        raise CaptureError("body_limit_exceeded")
                    chunks.extend(chunk)
                if time.monotonic() - started > DEADLINE_SECONDS:
                    raise CaptureError("request_deadline_exceeded")
        body = bytes(chunks)
        try:
            json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError) as exc:
            raise CaptureError("invalid_json") from exc
        receipt.update({"captured_at": _utc(), "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(), "status": "capture_complete"})
        if not memory_only:
            receipt["artifact"] = str(output / "capture.zip")
            _publish(output, body, receipt)
    except Exception as exc:
        receipt["status"] = "capture_failed" if receipt["request_count"] else "rejected"
        receipt["error_reason"] = str(exc) if isinstance(exc, (CaptureError, RegistryError)) else type(exc).__name__
        receipt.pop("artifact", None)
        receipt["executed_purposes"] = []
        body = None
    return body, receipt


def capture(
    *, manifest: str | Path, profile: str, source_id: str,
    expected_registry_version: str, expected_digest: str,
    output_dir: str | Path, transport: Any = None,
) -> dict[str, Any]:
    """Capture one approved source to a ZIP; test-only transport injection."""
    _, receipt = _capture(manifest=manifest, profile=profile, source_id=source_id,
                          expected_registry_version=expected_registry_version,
                          expected_digest=expected_digest, output_dir=output_dir,
                          transport=transport)
    return receipt


def capture_memory(
    *, manifest: str | Path, profile: str, source_id: str,
    expected_registry_version: str, expected_digest: str, transport: Any = None,
) -> tuple[bytes | None, bytes]:
    """Return raw bytes and a memory-only receipt, with no filesystem mutation.

    This delivery admits only ``twse_twt48u_all`` in memory; other sources are
    rejected before any request. The disk capture allowlist is unchanged.
    Failure returns ``(None, receipt_bytes)``. Raw retention ends when the caller
    drops the bytes; no ZIP, durable publication or historical snapshot is claimed.
    Transport injection is only for local tests, as on ``capture``.
    """
    body, receipt = _capture(manifest=manifest, profile=profile, source_id=source_id,
                             expected_registry_version=expected_registry_version,
                             expected_digest=expected_digest, transport=transport,
                             memory_only=True)
    return body, json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    child = sub.add_parser("capture")
    child.add_argument("--manifest", required=True)
    child.add_argument("--profile", required=True)
    child.add_argument("--source", dest="source_id", required=True)
    child.add_argument("--expected-registry-version", required=True)
    child.add_argument("--expected-digest", required=True)
    child.add_argument("--output-dir", required=True)
    args = vars(parser.parse_args(argv))
    args.pop("command")
    result = capture(**args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "capture_complete" else 2


if __name__ == "__main__":
    sys.exit(_cli())
