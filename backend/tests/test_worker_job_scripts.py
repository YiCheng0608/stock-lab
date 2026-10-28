"""Schedule scripts (tools/Invoke-WorkerJob.ps1, tools/Register-WorkerSchedule.ps1).

Since #313 the job is backend/worker/job.py (test_worker_job.py). Invoke-WorkerJob.ps1
only forwards its parameters to `python -m worker.cli job`, so that tasks registered
before #313 keep working; the registration script now registers that Python command.

The forwarding tests run the script inside test_worker_job's project tree (a copy of
job.py behind a fake worker.cli) with the real interpreter: the old task command line
goes through the script and the real job down to the fake worker steps. No worker,
DB, network or Claude call is involved. The registration script is only ever run
with -WhatIf: nothing is registered. Windows PowerShell 5.1 is required, so the
tests that run a script are skipped on other systems.

The wrapper used to read free memory through WMI (Get-CimInstance). On a busy
machine WMI cancels those calls (0x80041032 in the WMI-Activity event log) and the
job stopped before its first log line (#246). Every script run here has
Get-CimInstance and Get-WmiObject replaced by a module that throws; a source check
that also runs on Linux CI refuses WMI cmdlets in the script (the Python job has its
own, test_the_job_source_has_no_wmi_call).
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

from test_worker_job import Tree, end_line, skipped_line

POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SCRIPTS = ("Invoke-WorkerJob.ps1", "Register-WorkerSchedule.ps1")
CLAUDE = r"C:\tools\claude.exe"

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
    tree = Tree(tmp_path)
    # The scripts find their checkout through their own location: the tree's.
    tools = tree.project / "tools"
    tools.mkdir()
    for name in SCRIPTS:
        shutil.copyfile(TOOLS / name, tools / name)
    tree.data.mkdir(exist_ok=True)  # conftest already made tmp_path/data
    (tree.data / "stock.db").touch()
    no_wmi = tmp_path / "no-wmi"
    (no_wmi / "NoWmi").mkdir(parents=True)
    (no_wmi / "NoWmi" / "NoWmi.psm1").write_text(NO_WMI_MODULE, encoding="utf-8")
    # os.environ keys are upper case on Windows.
    module_path = os.pathsep.join([str(no_wmi), os.environ.get("PSMODULEPATH", "")])

    def powershell(script, *args, env=None):
        return subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(tools / script),
                *args,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            env={**tree.environment(), "PSMODULEPATH": module_path, **(env or {})},
            timeout=120,
            check=False,
        )

    def invoke(job, *args, env=None, min_free_gb="0"):
        completed = powershell(
            "Invoke-WorkerJob.ps1",
            "-Job",
            job,
            "-PythonPath",
            sys.executable,
            "-DataDir",
            str(tree.data),
            "-MinFreeMemoryGB",
            min_free_gb,
            *args,
            env=env,
        )
        return SimpleNamespace(
            code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            log=tree.log(job),
            calls=tree.calls(),
            steps=tree.steps(),
        )

    def register(job, *args, env=None):
        completed = powershell(
            "Register-WorkerSchedule.ps1",
            "-Job",
            job,
            "-PythonPath",
            sys.executable,
            "-DataDir",
            str(tree.data),
            "-WhatIf",
            *args,
            env=env,
        )
        return SimpleNamespace(
            code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )

    return SimpleNamespace(
        invoke=invoke,
        register=register,
        tree=tree,
        root=tmp_path,
        module_path=module_path,
    )


def command_line(stdout):
    return next(line for line in stdout.splitlines() if line.startswith("Command:"))


# Tasks registered before #313 keep working ---------------------------------------


def test_the_old_daily_task_command_runs_the_python_job(harness):
    # The parameters of a daily task registered before #313, minus -GitPull (the
    # tree is no repository to pull) and with this test's paths.
    result = harness.invoke(
        "daily",
        "-LogDir",
        str(harness.tree.logs),
        "-Trigger",
        "scheduler",
        "-ClaudeCli",
        CLAUDE,
    )
    assert result.code == 0, result.stdout + result.stderr
    assert result.steps == ["daily"]
    call = result.calls[0]
    assert call["argv"] == ["daily", "--trigger", "scheduler"]
    assert call["env"]["STOCK_CLAUDE_CLI"] == CLAUDE
    assert call["env"]["STOCK_DATA_DIR"] == str(harness.tree.data)
    assert [groups[1:] for groups in end_line(result.log)] == [("0", "")]
    assert "daily exit=0 log=" in result.stdout


def test_the_old_news_task_command_runs_news_and_news_llm(harness):
    result = harness.invoke(
        "news",
        "-Date",
        "2026-10-16",
        "-ClaudeCli",
        CLAUDE,
        env={"FAKE_NEWS_LLM_EXIT": "1"},
    )
    assert result.code == 0, result.stdout + result.stderr
    assert result.steps == ["news", "news-llm"]
    assert result.calls[0]["argv"] == ["news", "--date", "2026-10-16"]
    assert result.calls[1]["argv"] == ["news-llm"]
    assert [groups[1:] for groups in end_line(result.log)] == [("0", "1")]
    assert "news exit=0 news_llm_exit=1 log=" in result.stdout


def test_the_script_forwards_the_options_and_the_exit_code(harness):
    off = harness.invoke("news", "-SkipNewsLlm")
    assert off.code == 0 and off.steps == ["news"]
    assert end_line(off.log)[-1][1:] == ("0", "disabled")
    failed = harness.invoke("daily", "-Force", env={"FAKE_DAILY_EXIT": "2"})
    assert failed.code == 2
    assert failed.calls[-1]["argv"] == ["daily", "--trigger", "scheduler", "--force"]


def test_news_only_options_are_refused_for_daily(harness):
    result = harness.invoke("daily", "-SkipNewsLlm")
    assert result.code != 0 and result.steps == []
    assert "applies only to the news job" in result.stdout + result.stderr


def test_a_skipped_run_goes_through_the_script(harness):
    result = harness.invoke("news", min_free_gb="1024")
    assert result.code == 0 and result.steps == []
    assert skipped_line(result.log).group(1) == "low_memory"


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
        "tools/Invoke-WorkerJob.ps1 and the job must not use WMI (Get-CimInstance,"
        " Get-WmiObject): busy machines cancel the call and the job never starts (#246)\n"
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


# Registration (-WhatIf only) ---------------------------------------------------


def test_the_registered_command_is_the_python_job(harness):
    result = harness.register("daily")
    assert result.code == 0, result.stderr
    command = command_line(result.stdout)
    # AC-1: one command, the interpreter of the release venv and worker.cli job.
    python_dir = re.escape(str(Path(sys.executable).parent))
    assert re.fullmatch(
        rf'Command:  "{python_dir}\\pythonw?\.exe" -m worker\.cli job daily'
        r' --trigger scheduler --data-dir "[^"]+" --log-dir "[^"]+"'
        r" --min-free-memory-gb 2 --git-pull",
        command,
        re.IGNORECASE,
    ), command
    assert "powershell" not in command.lower() and "Invoke-WorkerJob" not in command
    assert f"WorkDir:  {harness.tree.backend}".lower() in result.stdout.lower()
    assert "job stops the worker at 02:30:00 (task limit 02:40:00)" in result.stdout


def test_news_registration_names_the_claude_executable(harness):
    claude = harness.root / "claude.exe"
    claude.touch()
    result = harness.register("news", "-ClaudeCli", str(claude))
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude}".lower() in result.stdout.lower()
    command = command_line(result.stdout)
    assert f'--claude-cli "{claude}"'.lower() in command.lower()
    assert "--skip-news-llm" not in command
    assert " job news " in command and command.endswith(f'"{claude}"')
    assert "--min-free-memory-gb 1 --git-pull" in command
    assert "job stops the worker at 01:30:00 (task limit 01:40:00)" in result.stdout


def test_news_registration_without_news_llm(harness):
    result = harness.register("news", "-NoNewsLlm")
    assert result.code == 0, result.stderr
    command = command_line(result.stdout)
    assert "--skip-news-llm" in command and "--claude-cli" not in command
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


def test_news_registration_takes_the_path_from_stock_claude_cli(harness):
    claude = harness.root / "claude.exe"
    claude.touch()
    result = harness.register("news", env={"STOCK_CLAUDE_CLI": str(claude)})
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude}".lower() in result.stdout.lower()


def test_daily_registration_has_no_news_llm_options(harness):
    result = harness.register("daily")
    assert result.code == 0, result.stderr
    assert (
        "Claude:   (not set; candidate_notes uses STOCK_CLAUDE_CLI or claude on the task PATH)"
        in result.stdout
    )
    assert (
        "--skip-news-llm" not in result.stdout and "--claude-cli" not in result.stdout
    )
    refused = harness.register("daily", "-NoNewsLlm")
    assert refused.code != 0
    assert "applies only to the news job" in refused.stdout + refused.stderr


def test_daily_registration_names_the_claude_executable_for_candidate_notes(harness):
    claude = harness.root / "claude.exe"
    claude.touch()
    result = harness.register("daily", "-ClaudeCli", str(claude))
    assert result.code == 0, result.stderr
    assert f"Claude:   {claude} (candidate_notes)".lower() in result.stdout.lower()
    command = command_line(result.stdout)
    assert f'--claude-cli "{claude}"'.lower() in command.lower()
    assert " job daily " in command and "--skip-news-llm" not in command
    shim = harness.root / "claude.cmd"
    shim.touch()
    for path, message in (
        (harness.root / "missing.exe", "not found"),
        (shim, "native .exe"),
    ):
        refused = harness.register("daily", "-ClaudeCli", str(path))
        assert refused.code != 0
        assert message in refused.stdout + refused.stderr
