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

$childEnvironment = @{
    STOCK_DATA_DIR = $DataDir
    STOCK_DB_PATH = Join-Path $DataDir 'stock.db'
    STOCK_RAW_DIR = Join-Path $DataDir 'raw'
    PYTHONPATH = Join-Path $projectRoot 'backend'
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONIOENCODING = 'utf-8'
}
$saved = @{}
foreach ($name in $childEnvironment.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$stdoutPath = Join-Path $LogDir ('.' + $Job + '-' + [guid]::NewGuid().ToString('N') + '.out')
$stderrPath = Join-Path $LogDir ('.' + $Job + '-' + [guid]::NewGuid().ToString('N') + '.err')
$utf8 = New-Object System.Text.UTF8Encoding($false)
$exitCode = 1
try {
    foreach ($name in $childEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $childEnvironment[$name], 'Process') }
    $header = "===== {0} start job={1} trigger={2} date={3} force={4} db={5} free_mb={6}" -f $now.ToString('o'), $Job, $Trigger, ($(if ($Date) { $Date } else { 'default' })), [bool]$Force, $childEnvironment.STOCK_DB_PATH, $freeMB
    [IO.File]::AppendAllText($logPath, $header + [Environment]::NewLine, $utf8)
    if ($pullOutput) {
        [IO.File]::AppendAllText($logPath, "--- git pull --ff-only" + [Environment]::NewLine + $pullOutput + [Environment]::NewLine, $utf8)
    }
    if ($skipReason) {
        [IO.File]::AppendAllText($logPath, "===== skipped reason=$skipReason (min_free_mb=$([int]($MinFreeMemoryGB * 1024)), git_dir=$gitDir)" + [Environment]::NewLine, $utf8)
    }
    if ($skipReason -and $Job -ne 'daily') {
        # Only daily records a skipped run in the database; other jobs just log it.
        $exitCode = 0
    } else {
        $argumentLine = ($cliArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
        $process = Start-Process -FilePath $PythonPath -ArgumentList $argumentLine -WorkingDirectory $projectRoot `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $exitCode = $process.ExitCode
        foreach ($part in @(@('stdout', $stdoutPath), @('stderr', $stderrPath))) {
            if (Test-Path -LiteralPath $part[1]) {
                $text = [IO.File]::ReadAllText($part[1], $utf8)
                if ($text) { [IO.File]::AppendAllText($logPath, "--- $($part[0])" + [Environment]::NewLine + $text + [Environment]::NewLine, $utf8) }
            }
        }
    }
    $finished = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $taipei)
    $seconds = [int]($finished - $now).TotalSeconds
    [IO.File]::AppendAllText($logPath, ("===== {0} end exit={1} seconds={2}" -f $finished.ToString('o'), $exitCode, $seconds) + [Environment]::NewLine, $utf8)
} catch {
    [IO.File]::AppendAllText($logPath, ("===== wrapper error: {0}" -f $_.Exception.Message) + [Environment]::NewLine, $utf8)
    throw
} finally {
    foreach ($name in $saved.Keys) {
        if ($null -eq $saved[$name]) {
            [Environment]::SetEnvironmentVariable($name, [NullString]::Value, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
        }
    }
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
}

$cutoff = (Get-Date).AddDays(-$LogRetentionDays)
Get-ChildItem -LiteralPath $LogDir -Filter ($Job + '-*.log') -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Write-Output "$Job exit=$exitCode log=$logPath"
exit $exitCode
