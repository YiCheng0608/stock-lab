"""Schedule scripts (tools/Invoke-WorkerJob.ps1, tools/Register-WorkerSchedule.ps1).

The wrapper runs against a fake interpreter (a .cmd that logs its arguments and
exits with a chosen code), so no worker, DB, network or Claude call is involved.
The registration script is only ever run with -WhatIf: nothing is registered.
Windows PowerShell 5.1 is required, so these tests are skipped on other systems.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="Windows PowerShell is required"
)

TOOLS = Path(__file__).resolve().parents[2] / "tools"
INVOKE = TOOLS / "Invoke-WorkerJob.ps1"
REGISTER = TOOLS / "Register-WorkerSchedule.ps1"

# %5 is the worker subcommand: python.exe -X utf8 -m worker.cli <step>.
# Batch files need CRLF line endings for goto labels to work.
FAKE_PYTHON = r"""@echo off
>>"%FAKE_LOG%" echo step=%5 argv=%* claude_cli=%STOCK_CLAUDE_CLI%
if "%5"=="news-llm" goto llm
if "%5"=="news" goto news
echo {"status":"success","step":"%5"}
exit /b 0
:news
echo {"status":"success","step":"news"}
echo news-stderr-line 1>&2
exit /b %FAKE_NEWS_EXIT%
:llm
echo {"status":"failed","step":"news-llm"}
echo llm-stderr-line 1>&2
exit /b %FAKE_NEWS_LLM_EXIT%
"""


@pytest.fixture
def harness(tmp_path):
    fake = tmp_path / "fake_python.cmd"
    fake.write_text(FAKE_PYTHON, newline="\r\n")
    data = tmp_path / "job-data"
    data.mkdir()
    (data / "stock.db").touch()
    calls = tmp_path / "calls.log"

    def invoke(job, *args, news_exit=0, llm_exit=0, min_free_gb="0", env=None):
        environment = {
            **os.environ,
            "FAKE_LOG": str(calls),
            "FAKE_NEWS_EXIT": str(news_exit),
            "FAKE_NEWS_LLM_EXIT": str(llm_exit),
        }
        environment.pop("STOCK_CLAUDE_CLI", None)
        environment.update(env or {})
        completed = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INVOKE),
                "-Job",
                job,
                "-PythonPath",
                str(fake),
                "-DataDir",
                str(data),
                "-MinFreeMemoryGB",
                min_free_gb,
                *args,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            env=environment,
            timeout=120,
            check=False,
        )
        logs = sorted((data / "logs").glob(f"{job}-*.log"))
        lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
        return SimpleNamespace(
            code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            log="".join(path.read_text(encoding="utf-8") for path in logs),
            steps=[line.split()[0].removeprefix("step=") for line in lines],
            calls=lines,
        )

    def register(job, *args):
        completed = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REGISTER),
                "-Job",
                job,
                "-PythonPath",
                str(fake),
                "-DataDir",
                str(data),
                "-WhatIf",
                *args,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
        return SimpleNamespace(
            code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )

    return SimpleNamespace(invoke=invoke, register=register, root=tmp_path, fake=fake)


END_LINE = r"^===== \S+ end exit=(\d+) seconds=\d+ news_llm_exit=(\S+)$"


def end_line(log):
    return re.search(END_LINE, log, re.MULTILINE)


# AC-1: news-llm follows news, with separate exit codes and log sections -------


def test_news_job_runs_news_llm_after_news_with_separate_sections(harness):
    result = harness.invoke("news", "-ClaudeCli", r"C:\tools\claude.exe", llm_exit=1)
    assert result.steps == ["news", "news-llm"]
    assert "worker.cli news-llm" in result.calls[1]
    log = result.log
    positions = [
        log.index(marker)
        for marker in (
            "--- news stdout",
            "--- news stderr",
            "--- news end exit=0",
            "--- news-llm start claude_cli=C:\\tools\\claude.exe",
            "--- news-llm stdout",
            "--- news-llm stderr",
            "--- news-llm end exit=1",
        )
    ]
    assert positions == sorted(positions)
    assert '{"status":"success","step":"news"}' in log
    assert '{"status":"failed","step":"news-llm"}' in log
    assert log.index("news-stderr-line") < log.index("--- news-llm start")
    assert log.index("llm-stderr-line") > log.index("--- news-llm start")
    assert " news_llm=on" in log.splitlines()[0]
    # news-llm failing leaves the job's own exit code alone.
    assert result.code == 0
    assert end_line(log).groups() == ("0", "1")
    assert "news exit=0 news_llm_exit=1 log=" in result.stdout


def test_news_failure_still_runs_news_llm_and_keeps_the_job_exit_code(harness):
    result = harness.invoke("news", news_exit=1)
    assert result.steps == ["news", "news-llm"]
    assert result.code == 1
    assert "--- news end exit=1" in result.log
    assert "--- news-llm end exit=0" in result.log
    assert end_line(result.log).groups() == ("1", "0")


def test_news_llm_gets_no_date_and_the_claude_path_reaches_both_steps(harness):
    result = harness.invoke(
        "news", "-Date", "2026-10-16", "-ClaudeCli", r"C:\tools\claude.exe"
    )
    news_call, llm_call = result.calls
    assert "--date 2026-10-16" in news_call
    assert "--date" not in llm_call
    assert news_call.endswith(r"claude_cli=C:\tools\claude.exe")
    assert llm_call.endswith(r"claude_cli=C:\tools\claude.exe")


def test_stock_claude_cli_from_the_environment_is_passed_through(harness):
    result = harness.invoke("news", env={"STOCK_CLAUDE_CLI": r"D:\other\claude.exe"})
    assert result.calls[1].endswith(r"claude_cli=D:\other\claude.exe")
    assert r"claude_cli=D:\other\claude.exe" in result.log


def test_without_a_configured_path_the_worker_falls_back_to_path(harness):
    result = harness.invoke("news")
    assert result.calls[1].endswith("claude_cli=")
    assert "--- news-llm start claude_cli=claude (PATH)" in result.log


def test_news_llm_can_be_switched_off(harness):
    result = harness.invoke("news", "-SkipNewsLlm")
    assert result.steps == ["news"]
    assert " news_llm=off" in result.log.splitlines()[0]
    assert "--- news-llm" not in result.log
    assert end_line(result.log).groups() == ("0", "disabled")


def test_a_skipped_news_run_runs_neither_step(harness):
    result = harness.invoke("news", min_free_gb="1024")
    assert result.steps == []
    assert result.code == 0
    assert "===== skipped reason=low_memory" in result.log
    assert end_line(result.log).groups() == ("0", "not_run")


def test_daily_log_layout_is_unchanged(harness):
    result = harness.invoke("daily")
    assert result.steps == ["daily"]
    assert "--- stdout" in result.log and "--- stderr" not in result.log
    assert "news-llm" not in result.log
    assert re.search(r"^===== \S+ end exit=0 seconds=\d+$", result.log, re.MULTILINE)


@pytest.mark.parametrize(
    "option", [["-SkipNewsLlm"], ["-ClaudeCli", r"C:\x\claude.exe"]]
)
def test_news_only_options_are_refused_for_daily(harness, option):
    result = harness.invoke("daily", *option)
    assert result.code != 0 and result.steps == []
    assert "applies only to the news job" in result.stdout + result.stderr


# Registration (-WhatIf only) ---------------------------------------------------


def test_news_registration_names_the_claude_executable(harness):
    claude = harness.root / "claude.exe"
    claude.touch()
    result = harness.register("news", "-ClaudeCli", str(claude))
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude}".lower() in result.stdout.lower()
    command = next(
        line for line in result.stdout.splitlines() if line.startswith("Command:")
    )
    assert f'-ClaudeCli "{claude}"'.lower() in command.lower()
    assert "-SkipNewsLlm" not in command
    assert "-Job news" in command and "-GitPull" in command


def test_news_registration_without_news_llm(harness):
    result = harness.register("news", "-NoNewsLlm")
    assert result.code == 0, result.stderr
    command = next(
        line for line in result.stdout.splitlines() if line.startswith("Command:")
    )
    assert "-SkipNewsLlm" in command and "-ClaudeCli" not in command
    assert "Claude:   (news-llm off)" in result.stdout


def test_news_registration_refuses_a_missing_or_non_exe_claude(harness):
    shim = harness.root / "claude.cmd"
    shim.touch()
    for path, message in (
        (harness.root / "missing.exe", "not found"),
        (shim, "native .exe"),
    ):
        result = harness.register("news", "-ClaudeCli", str(path))
        assert result.code != 0
        assert message in result.stdout + result.stderr


def test_news_registration_takes_the_path_from_stock_claude_cli(harness, monkeypatch):
    claude = harness.root / "claude.exe"
    claude.touch()
    monkeypatch.setenv("STOCK_CLAUDE_CLI", str(claude))
    result = harness.register("news")
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude}".lower() in result.stdout.lower()


def test_daily_registration_has_no_news_llm_options(harness):
    result = harness.register("daily")
    assert result.code == 0, result.stderr
    assert "Claude:" not in result.stdout and "-SkipNewsLlm" not in result.stdout
    refused = harness.register("daily", "-NoNewsLlm")
    assert refused.code != 0
    assert "apply only to the news job" in refused.stdout + refused.stderr
