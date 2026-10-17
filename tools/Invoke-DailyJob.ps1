<#
.SYNOPSIS
Run `python -m worker.cli daily` once and append its output to a dated log.

.DESCRIPTION
Entry point for the Windows Task Scheduler task created by
Register-DailySchedule.ps1; it can also be run by hand. The three STOCK_*
variables are set for the child process only. stdout (the JSON result) and
stderr are appended to <LogDir>/daily-<yyyyMMdd>.log, named by the Taipei
date of the invocation. The exit code is the CLI exit code: 0 for success,
skipped or non_trading_day, 1 for failed, 2 for partial. Logs older than
LogRetentionDays are removed from LogDir (only files named daily-*.log).

.EXAMPLE
./tools/Invoke-DailyJob.ps1 -PythonPath C:\path\to\.venv\Scripts\python.exe

.EXAMPLE
./tools/Invoke-DailyJob.ps1 -Date 2026-10-16 -Trigger manual
#>
param(
    [string]$PythonPath,
    [string]$DataDir,
    [string]$LogDir,
    [string]$Date,
    [ValidateSet('scheduler', 'manual', 'simulation')]
    [string]$Trigger = 'scheduler',
    [switch]$Force,
    [ValidateRange(1, 3650)]
    [int]$LogRetentionDays = 90
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
if (-not $DataDir) { $DataDir = Join-Path $projectRoot 'data' }
$DataDir = [IO.Path]::GetFullPath($DataDir)
if (-not $LogDir) { $LogDir = Join-Path $DataDir 'logs' }
$LogDir = [IO.Path]::GetFullPath($LogDir)
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$taipei = [TimeZoneInfo]::FindSystemTimeZoneById('Taipei Standard Time')
$now = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $taipei)
$logPath = Join-Path $LogDir ('daily-' + $now.ToString('yyyyMMdd') + '.log')

$cliArgs = @('-X', 'utf8', '-m', 'worker.cli', 'daily', '--trigger', $Trigger)
if ($Date) { $cliArgs += @('--date', $Date) }
if ($Force) { $cliArgs += '--force' }

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
$stdoutPath = Join-Path $LogDir ('.daily-' + [guid]::NewGuid().ToString('N') + '.out')
$stderrPath = Join-Path $LogDir ('.daily-' + [guid]::NewGuid().ToString('N') + '.err')
$utf8 = New-Object System.Text.UTF8Encoding($false)
$exitCode = 1
try {
    foreach ($name in $childEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $childEnvironment[$name], 'Process') }
    $header = "===== {0} start trigger={1} date={2} force={3} db={4}" -f $now.ToString('o'), $Trigger, ($(if ($Date) { $Date } else { 'latest-weekday' })), [bool]$Force, $childEnvironment.STOCK_DB_PATH
    [IO.File]::AppendAllText($logPath, $header + [Environment]::NewLine, $utf8)
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
    $finished = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $taipei)
    [IO.File]::AppendAllText($logPath, ("===== {0} end exit={1}" -f $finished.ToString('o'), $exitCode) + [Environment]::NewLine, $utf8)
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
Get-ChildItem -LiteralPath $LogDir -Filter 'daily-*.log' -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Write-Output "daily exit=$exitCode log=$logPath"
exit $exitCode
