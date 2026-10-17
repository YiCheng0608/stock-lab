<#
.SYNOPSIS
Run one scheduled worker job (`daily` or `news`) and append its output to a dated log.

.DESCRIPTION
Entry point for the Windows Task Scheduler tasks created by
Register-WorkerSchedule.ps1; it can also be run by hand. The STOCK_*
variables are set for the child process only. stdout (the JSON result) and
stderr are appended to <LogDir>/<Job>-<yyyyMMdd>.log, named by the Taipei
date of the invocation. The exit code is the CLI exit code; for daily: 0 for
success, skipped or non_trading_day, 1 for failed, 2 for partial. Logs older
than LogRetentionDays are removed from LogDir (only files named <Job>-*.log).

The news job runs two steps in one invocation: `worker.cli news`, then
`worker.cli news-llm` (AI summaries of the stored news). Each step has its own
log sections (`--- news stdout`, `--- news-llm stderr`, ...) and its own
`--- <step> end exit=<code>` line; the end line of the run carries
`news_llm_exit=<code>`. The job's exit code is news's alone: news-llm failing
(claude not found, not signed in, quota used up) shows in its log section and
in its `run_type=news_llm` ingestion run, but does not change the news result.
news-llm runs even when news failed, because it only reads news already stored.
-Date applies to news only (for news-llm it would filter, not label).
-SkipNewsLlm turns the second step off. -ClaudeCli is the native claude
executable for news-llm, passed to the child as STOCK_CLAUDE_CLI (a scheduled
task's PATH differs from an interactive shell's, so the registered task names
the path); without it the worker uses STOCK_CLAUDE_CLI or `claude` on PATH.

Before starting, the job is skipped (exit 0, logged; daily also records a
skipped schedule_runs row) when free physical memory is below
MinFreeMemoryGB (reason low_memory) or the checkout has a git operation in
progress, i.e. index.lock or MERGE_HEAD exists (reason git_busy). With
-GitPull (set on the scheduled tasks, which run from the release checkout)
it first runs `git pull --ff-only` in this checkout and skips with reason
git_pull_failed when that fails. The next trigger runs it again.

DataDir defaults to STOCK_DATA_DIR, then %USERPROFILE%\stock-lab-data;
PythonPath defaults to STOCK_PYTHON, then this checkout's .venv.

.EXAMPLE
./tools/Invoke-WorkerJob.ps1 -Job daily -PythonPath C:\path\to\.venv\Scripts\python.exe

.EXAMPLE
./tools/Invoke-WorkerJob.ps1 -Job daily -Date 2026-10-16 -Trigger manual

.EXAMPLE
./tools/Invoke-WorkerJob.ps1 -Job news

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

if ($Job -ne 'news') {
    if ($SkipNewsLlm) { throw '-SkipNewsLlm applies only to the news job' }
    if ($ClaudeCli) { throw '-ClaudeCli applies only to the news job' }
}
if (-not $PythonPath) { $PythonPath = $env:STOCK_PYTHON }
if (-not $PythonPath) {
    $venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonPath = $venvPython }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found; pass -PythonPath or set STOCK_PYTHON (got: '$PythonPath')"
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

if (-not $DataDir) { $DataDir = $env:STOCK_DATA_DIR }
if (-not $DataDir) { $DataDir = Join-Path $env:USERPROFILE 'stock-lab-data' }
$DataDir = [IO.Path]::GetFullPath($DataDir.TrimEnd([char[]]@([char]92, [char]47)))
if (-not $LogDir) { $LogDir = Join-Path $DataDir 'logs' }
$LogDir = [IO.Path]::GetFullPath($LogDir)
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$taipei = [TimeZoneInfo]::FindSystemTimeZoneById('Taipei Standard Time')
$now = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $taipei)
$logPath = Join-Path $LogDir ($Job + '-' + $now.ToString('yyyyMMdd') + '.log')

function Get-GitDir([string]$root) {
    $dotGit = Join-Path $root '.git'
    if (Test-Path -LiteralPath $dotGit -PathType Container) { return $dotGit }
    if (Test-Path -LiteralPath $dotGit -PathType Leaf) {
        $line = (Get-Content -LiteralPath $dotGit -TotalCount 1)
        if ($line -match '^gitdir:\s*(.+)$') { return [IO.Path]::GetFullPath($Matches[1].Trim()) }
    }
    return $null
}

$skipReason = $null
$freeMB = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
if ($freeMB -lt $MinFreeMemoryGB * 1024) { $skipReason = 'low_memory' }
$gitDir = Get-GitDir $projectRoot
if (-not $skipReason -and $gitDir) {
    foreach ($marker in 'index.lock', 'MERGE_HEAD') {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) { $skipReason = 'git_busy' }
    }
}
$pullOutput = ''
if (-not $skipReason -and $GitPull) {
    # git writes progress to stderr; run it through cmd so PowerShell 5.1
    # does not turn those lines into errors under ErrorActionPreference=Stop.
    $pullOutput = (& cmd.exe /c "git -C `"$projectRoot`" pull --ff-only 2>&1" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { $skipReason = 'git_pull_failed' }
}

$cliArgs = @('-X', 'utf8', '-m', 'worker.cli', $Job)
if ($Job -eq 'daily') {
    $cliArgs += @('--trigger', $Trigger)
    if ($Force) { $cliArgs += '--force' }
    if ($skipReason) { $cliArgs += @('--skip-reason', $skipReason) }
} elseif ($Force) {
    throw '-Force applies only to the daily job'
}
if ($Date) { $cliArgs += @('--date', $Date) }
$runNewsLlm = ($Job -eq 'news' -and -not $SkipNewsLlm)
# No --date: for news-llm it would select that day's items, not label the run.
$newsLlmArgs = @('-X', 'utf8', '-m', 'worker.cli', 'news-llm')
$claudeCliShown = if ($ClaudeCli) { $ClaudeCli } elseif ($env:STOCK_CLAUDE_CLI) { $env:STOCK_CLAUDE_CLI } else { 'claude (PATH)' }

$childEnvironment = @{
    STOCK_DATA_DIR = $DataDir
    STOCK_DB_PATH = Join-Path $DataDir 'stock.db'
    STOCK_RAW_DIR = Join-Path $DataDir 'raw'
    PYTHONPATH = Join-Path $projectRoot 'backend'
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONIOENCODING = 'utf-8'
}
if ($ClaudeCli) { $childEnvironment.STOCK_CLAUDE_CLI = $ClaudeCli }
$saved = @{}
foreach ($name in $childEnvironment.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Add-Log([string]$Text) {
    [IO.File]::AppendAllText($logPath, $Text + [Environment]::NewLine, $utf8)
}

# Run the worker CLI once; append its stdout and stderr to the log and return
# the exit code. The news job names its sections after the step (news, news-llm).
function Invoke-WorkerStep([string]$Step, [string[]]$StepArgs) {
    $prefix = if ($Job -eq 'news') { "$Step " } else { '' }
    $stdoutPath = Join-Path $LogDir ('.' + $Step + '-' + [guid]::NewGuid().ToString('N') + '.out')
    $stderrPath = Join-Path $LogDir ('.' + $Step + '-' + [guid]::NewGuid().ToString('N') + '.err')
    try {
        $argumentLine = ($StepArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
        $process = Start-Process -FilePath $PythonPath -ArgumentList $argumentLine -WorkingDirectory $projectRoot `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        foreach ($part in @(@('stdout', $stdoutPath), @('stderr', $stderrPath))) {
            if (Test-Path -LiteralPath $part[1]) {
                $text = [IO.File]::ReadAllText($part[1], $utf8)
                if ($text) { Add-Log ("--- $prefix$($part[0])" + [Environment]::NewLine + $text) }
            }
        }
        return [int]$process.ExitCode
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
        }
    }
}

$exitCode = 1
$newsLlmExit = if ($Job -ne 'news') { $null } elseif ($SkipNewsLlm) { 'disabled' } else { 'not_run' }
try {
    foreach ($name in $childEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $childEnvironment[$name], 'Process') }
    $header = "===== {0} start job={1} trigger={2} date={3} force={4} db={5} free_mb={6}" -f $now.ToString('o'), $Job, $Trigger, ($(if ($Date) { $Date } else { 'default' })), [bool]$Force, $childEnvironment.STOCK_DB_PATH, $freeMB
    if ($Job -eq 'news') { $header += " news_llm=$(if ($runNewsLlm) { 'on' } else { 'off' })" }
    Add-Log $header
    if ($pullOutput) {
        Add-Log ("--- git pull --ff-only" + [Environment]::NewLine + $pullOutput)
    }
    if ($skipReason) {
        Add-Log "===== skipped reason=$skipReason (min_free_mb=$([int]($MinFreeMemoryGB * 1024)), git_dir=$gitDir)"
    }
    if ($skipReason -and $Job -ne 'daily') {
        # Only daily records a skipped run in the database; other jobs just log it.
        $exitCode = 0
    } else {
        $stepStart = [DateTimeOffset]::Now
        $exitCode = Invoke-WorkerStep $Job $cliArgs
        if ($Job -eq 'news') {
            Add-Log ("--- news end exit={0} seconds={1}" -f $exitCode, [int]([DateTimeOffset]::Now - $stepStart).TotalSeconds)
        }
        if ($runNewsLlm) {
            # Runs whatever news's result was, and never changes it: any failure
            # here is logged and reported in news_llm_exit only.
            $stepStart = [DateTimeOffset]::Now
            Add-Log "--- news-llm start claude_cli=$claudeCliShown"
            try {
                $newsLlmExit = Invoke-WorkerStep 'news-llm' $newsLlmArgs
            } catch {
                $newsLlmExit = 'wrapper_error'
                Add-Log ("--- news-llm wrapper error: {0}" -f $_.Exception.Message)
            }
            Add-Log ("--- news-llm end exit={0} seconds={1}" -f $newsLlmExit, [int]([DateTimeOffset]::Now - $stepStart).TotalSeconds)
        }
    }
    $finished = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $taipei)
    $seconds = [int]($finished - $now).TotalSeconds
    $endLine = "===== {0} end exit={1} seconds={2}" -f $finished.ToString('o'), $exitCode, $seconds
    if ($Job -eq 'news') { $endLine += " news_llm_exit=$newsLlmExit" }
    Add-Log $endLine
} catch {
    Add-Log ("===== wrapper error: {0}" -f $_.Exception.Message)
    throw
} finally {
    foreach ($name in $saved.Keys) {
        if ($null -eq $saved[$name]) {
            [Environment]::SetEnvironmentVariable($name, [NullString]::Value, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
        }
    }
}

$cutoff = (Get-Date).AddDays(-$LogRetentionDays)
Get-ChildItem -LiteralPath $LogDir -Filter ($Job + '-*.log') -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

$summary = "$Job exit=$exitCode"
if ($Job -eq 'news') { $summary += " news_llm_exit=$newsLlmExit" }
Write-Output "$summary log=$logPath"
exit $exitCode
