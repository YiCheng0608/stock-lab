"""Schedule scripts (tools/Invoke-WorkerJob.ps1, tools/Register-WorkerSchedule.ps1).

The wrapper runs against a fake interpreter (a .cmd that logs its arguments and
exits with a chosen code), so no worker, DB, network or Claude call is involved.
The registration script is only ever run with -WhatIf: nothing is registered.
Windows PowerShell 5.1 is required, so the tests that run a script are skipped
on other systems.

The wrapper inspects the git dir of the checkout it lives in (index.lock or
MERGE_HEAD means a git operation is in progress and the job is skipped). Run from
the real checkout, that made the tests depend on whoever else was using it: an
uncommitted merge failed six of them every time, and a git command holding
index.lock for a moment failed a few at random. So the harness copies the scripts
into a project tree of its own under tmp_path, with a clean .git, and only the
tests that mean to exercise git_busy put a marker there.

The wrapper also used to read free memory through WMI (Get-CimInstance). On a
busy machine WMI cancels those calls (0x80041032 in the WMI-Activity event log),
the wrapper stopped before its first log line, and 13 to 15 of these tests failed
in whole-suite runs; it looked like interference from the test file before this
one (#246). Every wrapper run here has Get-CimInstance and Get-WmiObject replaced
by a module that throws, so the wrapper must work without WMI; a source check that
also runs on Linux CI refuses WMI cmdlets in the wrapper.
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

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SCRIPTS = ("Invoke-WorkerJob.ps1", "Register-WorkerSchedule.ps1")

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

# Found first on PSModulePath, so command lookup picks these over CimCmdlets and
# Microsoft.PowerShell.Management: any WMI call fails the way a cancelled one does.
WMI_CANCELLED = "Call cancelled (WMI 0x80041032, simulated by the test harness)"
NO_WMI_MODULE = f"""
function Get-CimInstance {{ throw '{WMI_CANCELLED}' }}
function Get-WmiObject {{ throw '{WMI_CANCELLED}' }}
Export-ModuleMember -Function Get-CimInstance, Get-WmiObject
"""


@pytest.fixture
def harness(tmp_path):
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    # The project tree the scripts run in: their own copies (the wrapper finds its
    # checkout through its own location) and a clean .git. Never the real checkout.
    project = tmp_path / "project"
    tools = project / "tools"
    tools.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copyfile(TOOLS / name, tools / name)
    git_dir = project / ".git"
    git_dir.mkdir()
    invoke_script = tools / "Invoke-WorkerJob.ps1"
    register_script = tools / "Register-WorkerSchedule.ps1"

    fake = tmp_path / "fake_python.cmd"
    fake.write_text(FAKE_PYTHON, newline="\r\n")
    data = tmp_path / "job-data"
    data.mkdir()
    (data / "stock.db").touch()
    calls = tmp_path / "calls.log"
    no_wmi = tmp_path / "no-wmi"
    (no_wmi / "NoWmi").mkdir(parents=True)
    (no_wmi / "NoWmi" / "NoWmi.psm1").write_text(NO_WMI_MODULE, encoding="utf-8")
    # os.environ keys are upper case on Windows.
    module_path = os.pathsep.join([str(no_wmi), os.environ.get("PSMODULEPATH", "")])

    def git_state(marker, *, linked=False):
        """Leave `marker` (index.lock, MERGE_HEAD) in the project's git dir.

        `linked` makes `.git` a file pointing at a git dir elsewhere, the layout of
        a linked worktree (and of every Orca task worktree). Returns the git dir.
        """
        target = git_dir
        if linked:
            target = tmp_path / "linked-git-dir"
            target.mkdir()
            shutil.rmtree(git_dir)
            git_dir.write_text(f"gitdir: {target.as_posix()}\n", encoding="utf-8")
        (target / marker).touch()
        return target

    def invoke(job, *args, news_exit=0, llm_exit=0, min_free_gb="0", env=None):
        environment = {
            **os.environ,
            "FAKE_LOG": str(calls),
            "FAKE_NEWS_EXIT": str(news_exit),
            "FAKE_NEWS_LLM_EXIT": str(llm_exit),
            "PSMODULEPATH": module_path,
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
                str(invoke_script),
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
                str(register_script),
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

    return SimpleNamespace(
        invoke=invoke,
        register=register,
        git_state=git_state,
        root=tmp_path,
        fake=fake,
        module_path=module_path,
    )


END_LINE = r"^===== \S+ end exit=(\d+) seconds=\d+ news_llm_exit=(\S+)$"
SKIPPED_LINE = r"^===== skipped reason=(\w+) \(min_free_mb=\d+, git_dir=(.+)\)$"


def end_line(log):
    return re.search(END_LINE, log, re.MULTILINE)


def skipped_line(log):
    return re.search(SKIPPED_LINE, log, re.MULTILINE)


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


# A git operation in progress in the checkout skips the job ---------------------


@pytest.mark.parametrize("linked", [False, True], ids=["git-dir", "linked-worktree"])
@pytest.mark.parametrize("marker", ["MERGE_HEAD", "index.lock"])
def test_a_git_operation_in_progress_skips_the_news_job(harness, marker, linked):
    git_dir = harness.git_state(marker, linked=linked)
    result = harness.invoke("news")
    assert result.steps == []
    assert result.code == 0
    skipped = skipped_line(result.log)
    assert skipped.group(1) == "git_busy"
    # The marker that counted is the harness's own, not the real checkout's.
    assert Path(skipped.group(2)) == git_dir
    assert end_line(result.log).groups() == ("0", "not_run")


def test_a_daily_run_blocked_by_git_still_runs_the_cli_to_record_the_skip(harness):
    harness.git_state("MERGE_HEAD")
    result = harness.invoke("daily")
    assert result.code == 0
    assert result.steps == ["daily"]
    assert "--skip-reason git_busy" in result.calls[0]
    assert skipped_line(result.log).group(1) == "git_busy"


def test_a_clean_git_dir_does_not_block_the_job(harness):
    result = harness.invoke("news")
    assert result.steps == ["news", "news-llm"]
    assert skipped_line(result.log) is None


# WMI cancelled calls (#246) ----------------------------------------------------


def test_the_harness_makes_every_wmi_call_fail(harness):
    # Without this the WMI-free check below would pass vacuously.
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "foreach ($c in 'Get-CimInstance', 'Get-WmiObject') {"
            ' try { & $c Win32_OperatingSystem | Out-Null; "$c ok" }'
            ' catch { "$c failed: $($_.Exception.Message)" } }',
        ],
        capture_output=True,
        text=True,
        errors="replace",
        env={**os.environ, "PSMODULEPATH": harness.module_path},
        timeout=120,
        check=False,
    )
    assert completed.stdout.splitlines() == [
        f"Get-CimInstance failed: {WMI_CANCELLED}",
        f"Get-WmiObject failed: {WMI_CANCELLED}",
    ], completed.stdout + completed.stderr


def test_the_wrapper_reads_free_memory_without_wmi(harness):
    result = harness.invoke("news")
    assert result.code == 0, (
        "tools/Invoke-WorkerJob.ps1 must not use WMI (Get-CimInstance, Get-WmiObject):"
        " busy machines cancel the call and the job never starts (#246)\n"
        + result.stdout
        + result.stderr
    )
    assert result.steps == ["news", "news-llm"]
    free_mb = re.search(r" free_mb=(\d+)", result.log.splitlines()[0])
    assert free_mb and int(free_mb.group(1)) > 0


# Cmdlets, aliases and type accelerators that go through WMI.
WMI_COMMAND = re.compile(
    r"\b(Get-CimInstance|Get-CimAssociatedInstance|Invoke-CimMethod|Get-WmiObject"
    r"|Invoke-WmiMethod|gcim|gwmi)\b|\[wmi(class|searcher)?\]",
    re.IGNORECASE,
)


def test_the_wrapper_source_has_no_wmi_call():
    # Runs on Linux CI too, where the script tests above are skipped.
    lines = (TOOLS / "Invoke-WorkerJob.ps1").read_text(encoding="utf-8").splitlines()
    found = [
        f"tools/Invoke-WorkerJob.ps1:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if WMI_COMMAND.search(line)
    ]
    assert not found, (
        "WMI in the scheduled job wrapper: busy machines cancel the call and the job"
        " never starts (#246)\n" + "\n".join(found)
    )


def test_daily_log_layout_is_unchanged(harness):
    result = harness.invoke("daily")
    assert result.steps == ["daily"]
    assert "--- stdout" in result.log and "--- stderr" not in result.log
    assert "news-llm" not in result.log
    assert re.search(r"^===== \S+ end exit=0 seconds=\d+$", result.log, re.MULTILINE)


def test_news_only_options_are_refused_for_daily(harness):
    result = harness.invoke("daily", "-SkipNewsLlm")
    assert result.code != 0 and result.steps == []
    assert "applies only to the news job" in result.stdout + result.stderr


def test_daily_passes_the_claude_path_to_its_candidate_notes_step(harness):
    result = harness.invoke("daily", "-ClaudeCli", r"C:\tools\claude.exe")
    assert result.code == 0 and result.steps == ["daily"]
    assert result.calls[0].endswith(r"claude_cli=C:\tools\claude.exe")
    # The daily log layout stays the same.
    assert "news-llm" not in result.log and "claude_cli" not in result.log


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
    assert (
        "Claude:   (not set; candidate_notes uses STOCK_CLAUDE_CLI or claude on the task PATH)"
        in result.stdout
    )
    assert "-SkipNewsLlm" not in result.stdout and "-ClaudeCli" not in result.stdout
    refused = harness.register("daily", "-NoNewsLlm")
    assert refused.code != 0
    assert "applies only to the news job" in refused.stdout + refused.stderr


def test_daily_registration_names_the_claude_executable_for_candidate_notes(harness):
    claude = harness.root / "claude.exe"
    claude.touch()
    result = harness.register("daily", "-ClaudeCli", str(claude))
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude} (candidate_notes)".lower() in result.stdout.lower()
    command = next(
        line for line in result.stdout.splitlines() if line.startswith("Command:")
    )
    assert f'-ClaudeCli "{claude}"'.lower() in command.lower()
    assert "-Job daily" in command and "-SkipNewsLlm" not in command
    shim = harness.root / "claude.cmd"
    shim.touch()
    for path, message in (
        (harness.root / "missing.exe", "not found"),
        (shim, "native .exe"),
    ):
        refused = harness.register("daily", "-ClaudeCli", str(path))
        assert refused.code != 0
        assert message in refused.stdout + refused.stderr
