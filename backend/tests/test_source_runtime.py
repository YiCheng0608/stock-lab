from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
import zipfile
from types import SimpleNamespace

import httpx
import pytest

from worker import source_registry as registry
from worker import source_runtime as runtime


@pytest.fixture
def setup_capture(tmp_path):
    manifest = json.loads(registry.REGISTRY_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    args = dict(manifest=path, profile="free_public_local", source_id="twse_stock_day_all",
                expected_registry_version=manifest["registry_version"],
                expected_digest=manifest["content_digest"], output_dir=tmp_path / "capture")
    def save():
        manifest["content_digest"] = registry.manifest_digest(manifest)
        args["expected_digest"] = manifest["content_digest"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
    save()
    return manifest, args, save


def fake_transport(body=b'[ { "Code": "2330" } ]\n', status=200, headers=None):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers or {})
    return httpx.MockTransport(handler), calls


@pytest.mark.parametrize("source_id", runtime.ENDPOINTS)
def test_exact_sources_preserve_bytes_and_attribution(setup_capture, source_id):
    manifest, args, _ = setup_capture
    args["source_id"] = source_id
    body = b'[ { "name": "test", "v": 1.00 } ]\n'
    transport, calls = fake_transport(body)
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_complete", result
    assert len(calls) == result["request_count"] == 1
    assert str(calls[0].url) == runtime.ENDPOINTS[source_id]
    assert calls[0].method == "GET"
    assert calls[0].headers["Accept-Encoding"] == "identity"
    assert "authorization" not in calls[0].headers
    assert result["rate_limit_verified"] is False
    assert result["documented_numeric_rate_limit"] == "unknown"
    assert result["historical_pit"] == "unsupported"
    assert result["executed_purposes"] == ["local_fetch", "raw_store"]
    assert datetime.fromisoformat(result["request_started_at"]).utcoffset().total_seconds() == 0
    assert datetime.fromisoformat(result["captured_at"]).utcoffset().total_seconds() == 0
    assert result["body_sha256"] == hashlib.sha256(body).hexdigest()
    source = next(s for s in manifest["sources"] if s["source_id"] == source_id)
    assert result["attribution"]["owner"] == source["owner"]
    assert result["attribution"]["terms"] == source["access"]["documented_terms"]
    assert result["attribution"]["evidence"] == source["evidence"]
    with zipfile.ZipFile(result["artifact"]) as archive:
        assert archive.namelist() == ["body.bin", "receipt.json"]
        assert archive.read("body.bin") == body
        assert json.loads(archive.read("receipt.json")) == result
    assert [p.name for p in args["output_dir"].iterdir()] == ["capture.zip"]


@pytest.mark.parametrize("case", ["digest", "version", "profile", "source", "endpoint", "method", "fetch_denied", "store_unknown", "condition", "quota", "prohibited_quota", "project_output", "file_output", "nonempty", "missing_parent"])
def test_preflight_rejects_with_zero_network_and_output_mutation(setup_capture, case, tmp_path):
    manifest, args, save = setup_capture
    source = manifest["sources"][0]
    if case == "digest": args["expected_digest"] = "sha256:bad"
    elif case == "version": args["expected_registry_version"] = "bad"
    elif case == "profile": args["profile"] = "bad"
    elif case == "source": args["source_id"] = "bad"
    elif case == "endpoint": source["exact_url"] = "http://127.0.0.1/secret"; save()
    elif case == "method": source["method"] = "POST"; save()
    elif case == "fetch_denied": source["purposes"]["local_fetch"]["status"] = "denied"; save()
    elif case == "store_unknown": source["purposes"]["raw_store"]["status"] = "unknown"; save()
    elif case == "condition": source["purposes"]["raw_store"]["conditions"].append("new_condition"); save()
    elif case == "quota": source["access"]["rate_limit"] = {"status": "known", "value": "1/minute"}; save()
    elif case == "prohibited_quota": source["access"]["rate_limit"] = {"status": "explicitly_prohibited", "reason": "stop"}; save()
    elif case == "project_output": args["output_dir"] = runtime.PROJECT_ROOT
    elif case == "file_output": args["output_dir"].write_text("untouched")
    elif case == "nonempty": args["output_dir"].mkdir(); (args["output_dir"] / "existing").write_text("untouched")
    elif case == "missing_parent": args["output_dir"] = tmp_path / "absent" / "child"
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    dirs = {str(p) for p in tmp_path.rglob("*") if p.is_dir()}
    transport, calls = fake_transport()
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "rejected"
    assert result["request_count"] == 0 and calls == []
    assert result["error_reason"]
    if case in {"quota", "prohibited_quota"}:
        assert result["rate_limit_evidence"] == source["access"]["rate_limit"]
        assert result["documented_numeric_rate_limit"] == source["access"]["rate_limit"]["status"]
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert {str(p) for p in tmp_path.rglob("*") if p.is_dir()} == dirs


@pytest.mark.parametrize("status", [301, 307, 400, 429, 500, 503])
def test_http_errors_stop_without_retries_or_artifacts(setup_capture, status):
    _, args, _ = setup_capture
    transport, calls = fake_transport(status=status, headers={"Retry-After": "Wed, 16 Sep 2026 10:00:00 GMT", "Location": "http://127.0.0.1/"})
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_failed"
    assert result["http_status"] == status
    assert result["retry_after"] == "Wed, 16 Sep 2026 10:00:00 GMT"
    assert len(calls) == result["request_count"] == 1
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("body,headers,reason", [(b"not json", {}, "invalid_json"), (b"NaN", {}, "invalid_json"), (b"[]", {"Content-Encoding": "gzip"}, "unsupported_content_encoding"), (b"[123456789]", {}, "body_limit_exceeded")])
def test_body_failure_never_publishes(setup_capture, monkeypatch, body, headers, reason):
    _, args, _ = setup_capture
    monkeypatch.setattr(runtime, "MAX_BODY_BYTES", 10)
    transport, calls = fake_transport(body, headers=headers)
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_failed"
    assert result["error_reason"] == reason
    assert len(calls) == 1
    assert not args["output_dir"].exists()


def test_timeout_has_single_attempt(setup_capture):
    _, args, _ = setup_capture
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("fixture", request=request)
    result = runtime.capture(**args, transport=httpx.MockTransport(handler))
    assert result["error_reason"] == "ReadTimeout"
    assert len(calls) == 1
    assert not args["output_dir"].exists()


def test_publish_failure_cleans_owned_staging(setup_capture, monkeypatch):
    _, args, _ = setup_capture
    transport, _ = fake_transport()
    def denied(*args): raise OSError("no hardlinks")
    monkeypatch.setattr(runtime.os, "link", denied)
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_failed" and "artifact" not in result
    assert not args["output_dir"].exists()


def test_racing_file_is_not_overwritten(setup_capture):
    _, args, _ = setup_capture
    def handler(request):
        args["output_dir"].mkdir()
        (args["output_dir"] / "capture.zip").write_bytes(b"other owner")
        return httpx.Response(200, stream=httpx.ByteStream(b"[]"))
    result = runtime.capture(**args, transport=httpx.MockTransport(handler))
    assert result["status"] == "capture_failed"
    assert (args["output_dir"] / "capture.zip").read_bytes() == b"other owner"
    assert len(list(args["output_dir"].iterdir())) == 1


def test_empty_output_is_supported(setup_capture):
    _, args, _ = setup_capture
    args["output_dir"].mkdir()
    transport, _ = fake_transport()
    assert runtime.capture(**args, transport=transport)["status"] == "capture_complete"


def test_deadline_is_checked_between_chunks(setup_capture, monkeypatch):
    _, args, _ = setup_capture
    clock = iter([0.0, runtime.DEADLINE_SECONDS + 1])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    transport, calls = fake_transport()
    result = runtime.capture(**args, transport=transport)
    assert result["error_reason"] == "request_deadline_exceeded"
    assert result["condition_receipts"]["bounded_requests"]["deadline_scope"].endswith("not a hard total deadline")
    assert len(calls) == 1 and not args["output_dir"].exists()


def test_client_disables_ambient_environment_and_redirects(setup_capture, monkeypatch):
    _, args, _ = setup_capture
    original = httpx.Client
    options = []
    def checked_client(**kwargs):
        options.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(httpx, "Client", checked_client)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("SSL_CERT_FILE", "nonexistent-cert-file")
    transport, _ = fake_transport()
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_complete"
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"] == runtime.TIMEOUT_SECONDS


def test_exclusive_publication_does_not_overwrite_racing_destination(setup_capture, monkeypatch):
    _, args, _ = setup_capture
    original = runtime.os.link
    def race(source, destination):
        Path(destination).write_bytes(b"competing artifact")
        return original(source, destination)
    monkeypatch.setattr(runtime.os, "link", race)
    transport, _ = fake_transport()
    result = runtime.capture(**args, transport=transport)
    assert result["status"] == "capture_failed" and "artifact" not in result
    assert (args["output_dir"] / "capture.zip").read_bytes() == b"competing artifact"
    assert [p.name for p in args["output_dir"].iterdir()] == ["capture.zip"]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction_into_project_rejected(setup_capture, tmp_path):
    _, args, _ = setup_capture
    junction = tmp_path / "project-junction"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(runtime.PROJECT_ROOT)], capture_output=True)
    assert created.returncode == 0, created.stderr
    try:
        assert junction.resolve() == runtime.PROJECT_ROOT
        args["output_dir"] = junction / "forbidden-capture"
        transport, calls = fake_transport()
        result = runtime.capture(**args, transport=transport)
        assert result["error_reason"] == "output_inside_project" and calls == []
    finally:
        # Remove only the junction entry itself, never recurse into its target.
        os.rmdir(junction)


def test_symlink_into_project_rejected(setup_capture, tmp_path):
    _, args, _ = setup_capture
    link = tmp_path / "link"
    try:
        link.symlink_to(runtime.PROJECT_ROOT, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    args["output_dir"] = link / "forbidden-capture"
    transport, calls = fake_transport()
    result = runtime.capture(**args, transport=transport)
    assert result["error_reason"] == "output_inside_project" and calls == []


def test_import_help_and_invalid_cli_are_app_independent(setup_capture, tmp_path):
    _, args, _ = setup_capture
    env = os.environ.copy()
    env.update(STOCK_DATA_DIR=str(tmp_path / "isolated-data"), STOCK_DB_PATH=str(tmp_path / "isolated.db"), STOCK_RAW_DIR=str(tmp_path / "isolated-raw"), PYTHONDONTWRITEBYTECODE="1")
    code = "import sys; import worker.source_runtime; assert not any(x == 'app' or x.startswith('app.') or x in ('worker.pipeline','worker.sources','httpx') for x in sys.modules)"
    imported = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    help_result = subprocess.run([sys.executable, "-m", "worker.source_runtime", "capture", "--help"], env=env, capture_output=True, text=True)
    assert help_result.returncode == 0
    cli = [sys.executable, "-m", "worker.source_runtime", "capture"]
    for key, value in args.items():
        cli.extend(["--source" if key == "source_id" else "--" + key.replace("_", "-"), str(value)])
    cli[cli.index("--expected-digest") + 1] = "invalid"
    rejected = subprocess.run(cli, env=env, capture_output=True, text=True)
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["request_count"] == 0
    assert not any(Path(env[k]).exists() for k in ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR"))
    assert not args["output_dir"].exists()
