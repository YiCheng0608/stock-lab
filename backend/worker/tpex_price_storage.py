"""Explicit private single-capture files. Import and policy inspection perform no I/O."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from .tpex_price_capture import (ENDPOINT, NEW_CUTOFF, SOURCE_ID, SEVENTH_SCOPE_POLICY_VERSION,
    PriceCapture, PriceCaptureError, admit_observed_price_capture, canonical_bytes,
    digest, price_policy, validate_policy)

STORAGE_POLICY_VERSION = "m1-price-save-tpex-11370-2026-10-06.1"
# Independently accepted in the coordinator's original task; hashing is not admission.
STORAGE_POLICY_DIGEST = "sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e"
CAPTURE_POLICY_DIGEST = "sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040"
RECEIPT_VERSION = "tpex-price-storage-receipt/m1-v1"
DIRECTORY = "tpex-11370-2026-10-06-m1-v1"
STAGING = ".pending-" + DIRECTORY
FILES = ("body.csv", "capture-receipt.json", "storage-receipt.json")
_source = price_policy(NEW_CUTOFF, policy_version=SEVENTH_SCOPE_POLICY_VERSION)
_STORAGE_POLICY = {
    "version": STORAGE_POLICY_VERSION, "profile": "free_public_local", "storage": "private_local",
    "purposes": ["local_fetch", "raw_store", "summarize"], "source_id": SOURCE_ID,
    "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/11370", "resource_url": ENDPOINT, "method": "GET",
    "capture_policy_version": SEVENTH_SCOPE_POLICY_VERSION, "capture_policy_digest": CAPTURE_POLICY_DIGEST,
    "capture_worker_version": "tpex-price-capture/m2-stock-scope-v5", "scope": deepcopy(_source["scope"]),
    "bounds": {"max_raw_bytes": 3145728, "max_capture_receipt_bytes": 8192,
        "max_storage_receipt_bytes": 16384, "max_bundle_bytes": 3170304, "max_bundles": 1,
        "max_files": 3, "max_directories": 3, "save_reopen_network_requests": 0},
    "validation": {"expected_body_sha256": _source["validation"]["expected_body_sha256"],
        "structural": "all_rows_header_width_date_unique_date_code", "financial": "selected_symbols_only",
        "capture_receipt": "exact_canonical_original", "storage_receipt": "exact_canonical_schema"},
    "attribution": deepcopy(_source["attribution"]), "limitations": list(_source["limitations"]),
    "source_use_evidence": {
        "dataset": {"url": "https://data.gov.tw/api/v2/rest/dataset/11370", "captured_at": "2026-10-06T23:03:24.327792Z",
            "body_sha256": "64950fc1b492ee223fe86e16fb7d49a27426d1697c0c1f4553330279ca09fbe4"},
        "license": {"url": "https://data.gov.tw/license", "captured_at": "2026-10-06T23:03:24.544792Z",
            "body_sha256": "f123f1949f22db90d61d8142051a91ab49b1887133c3d477648aec57256b3c9b"},
        "terms": {"url": "https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw", "captured_at": "2026-10-06T23:03:24.687792Z",
            "body_sha256": "ead63b3a74530eb996accdbf96c750e01769149c9d8a7622b6277855b79095d5"},
    },
}
del _source


class PriceStorageError(ValueError):
    pass


def storage_policy() -> dict:
    return deepcopy(_STORAGE_POLICY)


def validate_storage_policy(policy: dict, version: str, pin: str) -> None:
    if policy != _STORAGE_POLICY or version != STORAGE_POLICY_VERSION or pin != STORAGE_POLICY_DIGEST or digest(policy) != pin:
        raise PriceStorageError("price_storage_policy_pins_mismatch")
    source = price_policy(NEW_CUTOFF, policy_version=SEVENTH_SCOPE_POLICY_VERSION)
    try:
        validate_policy(source, policy["capture_policy_version"], policy["capture_policy_digest"])
    except PriceCaptureError as exc:
        raise PriceStorageError("price_storage_source_pins_mismatch") from exc
    if (source["scope"] != policy["scope"] or source["attribution"] != policy["attribution"]
            or source["limitations"] != policy["limitations"]
            or source["validation"]["expected_body_sha256"] != policy["validation"]["expected_body_sha256"]):
        raise PriceStorageError("price_storage_source_pins_mismatch")


def _json(encoded: bytes) -> dict:
    try:
        value = json.loads(encoded.decode("utf-8"))
        if type(value) is not dict or canonical_bytes(value) != encoded:
            raise ValueError()
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise PriceStorageError("price_saved_receipt_invalid") from exc


def _utc(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if type(value) is not str or result.utcoffset() != timezone.utc.utcoffset(result):
            raise ValueError()
        return result
    except (ValueError, TypeError) as exc:
        raise PriceStorageError("price_saved_time_invalid") from exc


def verified_capture(body: bytes, receipt_bytes: bytes, policy: dict) -> PriceCapture:
    bounds = policy["bounds"]
    if type(body) is not bytes or not 0 < len(body) <= bounds["max_raw_bytes"] or type(receipt_bytes) is not bytes or not 0 < len(receipt_bytes) <= bounds["max_capture_receipt_bytes"]:
        raise PriceStorageError("price_saved_size_invalid")
    receipt = _json(receipt_bytes)
    try:
        capture = admit_observed_price_capture(body=body, http_status=receipt["http_status"], endpoint=receipt["endpoint"],
            request_started_at=receipt["request_started_at"], captured_at=receipt["captured_at"],
            policy=price_policy(NEW_CUTOFF, policy_version=policy["capture_policy_version"]),
            expected_policy_version=policy["capture_policy_version"], expected_policy_digest=policy["capture_policy_digest"])
    except (ValueError, KeyError, TypeError) as exc:
        raise PriceStorageError("price_saved_capture_invalid") from exc
    if capture.receipt_bytes != receipt_bytes:
        raise PriceStorageError("price_saved_capture_invalid")
    return capture


def _receipt(capture: PriceCapture, policy: dict, saved_at: str) -> dict:
    original = capture.receipt
    if _utc(saved_at) < _utc(original["captured_at"]):
        raise PriceStorageError("price_saved_time_invalid")
    return {"version": RECEIPT_VERSION, "storage": "private_local", "storage_policy_version": policy["version"],
        "storage_policy_digest": digest(policy), "capture_policy_version": original["policy_version"],
        "capture_policy_digest": original["policy_digest"], "source_id": SOURCE_ID, "source_version": original["source_version"],
        "endpoint": ENDPOINT, "method": "GET", "as_of": NEW_CUTOFF.isoformat(),
        "selected_symbols": list(policy["scope"]["symbols"]), "body_sha256": original["body_sha256"],
        "body_bytes": len(capture.body), "capture_receipt_sha256": hashlib.sha256(capture.receipt_bytes).hexdigest(),
        "capture_receipt_bytes": len(capture.receipt_bytes), "captured_at": original["captured_at"],
        "request_started_at": original["request_started_at"], "saved_at": saved_at,
        "attribution": deepcopy(policy["attribution"]), "limitations": list(policy["limitations"])}


def _plain(path: Path, *, directory: bool) -> os.stat_result:
    info = path.lstat()
    if (getattr(info, "st_file_attributes", 0) & 1024 or stat.S_ISLNK(info.st_mode)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise PriceStorageError("price_storage_path_unsafe")
    return info


@contextmanager
def _hold_directory(path: Path):
    """Windows handles deny directory replacement while files are checked/opened."""
    _plain(path, directory=True)
    if os.name != "nt":
        raise PriceStorageError("price_storage_platform_unsupported")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    close = kernel.CloseHandle
    close.argtypes, close.restype = [ctypes.c_void_p], ctypes.c_int
    handle = create(str(path), 0x80, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise PriceStorageError("price_storage_path_unsafe")
    try:
        _plain(path, directory=True)
        yield
    finally:
        close(handle)


def _checked_handle(fd: int, path: Path) -> None:
    import msvcrt
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 1024:
        raise PriceStorageError("price_storage_path_unsafe")
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    function.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
    if not 0 < length < len(buffer) or os.path.normcase(buffer.value.removeprefix("\\\\?\\")) != os.path.normcase(str(path)):
        raise PriceStorageError("price_storage_path_unsafe")


@contextmanager
def _root_scope(root: str | Path, *, create: bool):
    path = Path(root)
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    base = local / "taiwan-stock-research"
    if (not local.is_absolute() or not path.is_absolute() or path.parent != base or not path.name
            or any(part in {".", ".."} or ":" in part for part in path.parts[1:]) or str(path).startswith("\\\\")):
        raise PriceStorageError("price_storage_root_invalid")
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            if not parent.exists():
                if create and parent == base:
                    parent.mkdir()
                else:
                    raise PriceStorageError("price_saved_capture_missing")
            stack.enter_context(_hold_directory(parent))
        if not path.exists():
            if create:
                path.mkdir()
            else:
                raise PriceStorageError("price_saved_capture_missing")
        stack.enter_context(_hold_directory(path))
        yield path


def _tree(root: Path) -> None:
    children = {item.name for item in root.iterdir()}
    if not children <= {DIRECTORY, STAGING}:
        raise PriceStorageError("price_storage_entries_invalid")
    if STAGING in children:
        raise PriceStorageError("price_storage_incomplete")


def _read(path: Path, cap: int) -> bytes:
    info = _plain(path, directory=False)
    if not 0 < info.st_size <= cap:
        raise PriceStorageError("price_saved_size_invalid")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        _checked_handle(fd, path)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(cap + 1)
        if len(body) != info.st_size or not 0 < len(body) <= cap:
            raise PriceStorageError("price_saved_size_invalid")
        return body
    finally:
        os.close(fd)


def _load(root: Path, policy: dict) -> tuple[PriceCapture, dict, str]:
    _tree(root)
    final = root / DIRECTORY
    if not final.exists():
        raise PriceStorageError("price_saved_capture_missing")
    with _hold_directory(final):
        if {item.name for item in final.iterdir()} != set(FILES):
            raise PriceStorageError("price_storage_entries_invalid")
        bounds = policy["bounds"]
        body = _read(final / FILES[0], bounds["max_raw_bytes"])
        encoded = _read(final / FILES[1], bounds["max_capture_receipt_bytes"])
        storage_bytes = _read(final / FILES[2], bounds["max_storage_receipt_bytes"])
        if len(body) + len(encoded) + len(storage_bytes) > bounds["max_bundle_bytes"]:
            raise PriceStorageError("price_saved_size_invalid")
        capture = verified_capture(body, encoded, policy)
        receipt = _json(storage_bytes)
        if canonical_bytes(_receipt(capture, policy, receipt.get("saved_at"))) != storage_bytes:
            raise PriceStorageError("price_saved_storage_receipt_invalid")
        return capture, receipt, hashlib.sha256(storage_bytes).hexdigest()


def reopen_capture(*, root: str | Path, policy: dict, expected_policy_version: str, expected_policy_digest: str):
    validate_storage_policy(policy, expected_policy_version, expected_policy_digest)
    with _root_scope(root, create=False) as path:
        return _load(path, policy)


def save_capture(capture: PriceCapture, *, root: str | Path, policy: dict, expected_policy_version: str,
                 expected_policy_digest: str, now=None):
    validate_storage_policy(policy, expected_policy_version, expected_policy_digest)
    if not isinstance(capture, PriceCapture):
        raise PriceStorageError("price_saved_capture_invalid")
    verified = verified_capture(capture.body, capture.receipt_bytes, policy)
    if capture.parsed != verified.parsed:
        raise PriceStorageError("price_saved_capture_invalid")
    saved_at = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).isoformat()
    encoded = canonical_bytes(_receipt(verified, policy, saved_at))
    if len(encoded) > policy["bounds"]["max_storage_receipt_bytes"]:
        raise PriceStorageError("price_saved_size_invalid")
    with _root_scope(root, create=True) as path:
        _tree(path)
        if (path / DIRECTORY).exists():
            result = _load(path, policy)
            if result[0].body != capture.body or result[0].receipt_bytes != capture.receipt_bytes:
                raise PriceStorageError("price_storage_existing_capture_mismatch")
            return (*result, "already_saved")
        staged = path / STAGING
        staged.mkdir()  # Exclusive; another writer or interrupted save is never replaced.
        created = []
        try:
            with _hold_directory(staged):
                for name, data in zip(FILES, (verified.body, verified.receipt_bytes, encoded)):
                    file = staged / name
                    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
                    created.append(file)
                    try:
                        _checked_handle(fd, file)
                        with os.fdopen(fd, "wb", closefd=False) as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(fd)
                    finally:
                        os.close(fd)
            # Windows rename is atomic and rejects an existing target directory.
            os.rename(staged, path / DIRECTORY)
        except BaseException:
            # Only this call's exact staging/files; never clean a prior interrupted save.
            if staged.exists():
                _plain(staged, directory=True)
                if {item.name for item in staged.iterdir()} != {item.name for item in created}:
                    raise PriceStorageError("price_storage_cleanup_incomplete") from None
                for file in created:
                    _plain(file, directory=False)
                    file.unlink()
                staged.rmdir()
            raise
        return (*_load(path, policy), "saved")
