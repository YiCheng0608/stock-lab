<#
.SYNOPSIS
Run one scheduled worker job (`daily` or `news`): forwards to `python -m worker.cli job`.

.DESCRIPTION
The job itself (lock, checks before the run, time limit, dated log, news ->
news-llm, log retention, exit code) is backend/worker/job.py; see
docs/OPERATIONS.md §6. This script only maps its parameters onto that command,
so a Task Scheduler task registered before #313 (it runs this script with
-GitPull -MinFreeMemoryGB ...) keeps working until it is registered again with
tools/Register-WorkerSchedule.ps1, which calls the Python command directly.

PythonPath defaults to STOCK_PYTHON, then this checkout's .venv. DataDir is
passed through when given; the job defaults to STOCK_DATA_DIR, then
%USERPROFILE%\stock-lab-data.

.EXAMPLE
./tools/Invoke-WorkerJob.ps1 -Job daily -Date 2026-10-16 -Trigger manual

.EXAMPLE
./tools/Invoke-WorkerJob.ps1 -Job news -ClaudeCli C:\Users\me\.local\bin\claude.exe
#>
param(
    [ValidateSet('daily', 'news')]
    [string]$Job = 'daily',
    [Alias('Python')]
    [string]$PythonPath,
    [string]$DataDir,
    [string]$LogDir,
    [string]$Date,
    [ValidateSet('scheduler', 'manual', 'simulation')]
    [string]$Trigger = 'scheduler',
    [switch]$Force,
    [switch]$GitPull,
    [string]$ClaudeCli,
    [switch]$SkipNewsLlm,
    [ValidateRange(1, 3650)]
    [int]$LogRetentionDays = 90,
    [ValidateRange(0, 1024)]
    [double]$MinFreeMemoryGB = 8
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

if (-not $PythonPath) { $PythonPath = $env:STOCK_PYTHON }
if (-not $PythonPath) {
    $venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonPath = $venvPython }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found; pass -PythonPath or set STOCK_PYTHON (got: '$PythonPath')"
}

$jobArgs = @('-m', 'worker.cli', 'job', $Job, '--trigger', $Trigger,
    '--log-retention-days', [string]$LogRetentionDays,
    '--min-free-memory-gb', $MinFreeMemoryGB.ToString([Globalization.CultureInfo]::InvariantCulture))
# A trailing backslash would escape the closing quote of a quoted argument.
if ($DataDir) { $jobArgs += @('--data-dir', $DataDir.TrimEnd([char[]]@([char]92, [char]47))) }
if ($LogDir) { $jobArgs += @('--log-dir', $LogDir.TrimEnd([char[]]@([char]92, [char]47))) }
if ($Date) { $jobArgs += @('--date', $Date) }
if ($Force) { $jobArgs += '--force' }
if ($GitPull) { $jobArgs += '--git-pull' }
if ($ClaudeCli) { $jobArgs += @('--claude-cli', $ClaudeCli) }
if ($SkipNewsLlm) { $jobArgs += '--skip-news-llm' }

# `-m worker.cli` resolves from the working directory; the job writes its own
# log, so its stdout (one summary line) and stderr pass straight through.
$ErrorActionPreference = 'Continue'
Push-Location -LiteralPath (Join-Path $projectRoot 'backend')
try {
    & $PythonPath @jobArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
