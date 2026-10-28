<#
.SYNOPSIS
Create, update or remove the Windows Task Scheduler task for the coordinator's event monitor.

.DESCRIPTION
Registers \stock-lab\monitor, which keeps tools/ops/monitor.sh running with Git Bash
from this checkout (Issue #316, docs/OPERATIONS.md §6.6). The monitor polls GitHub
every IntervalSeconds (at least 60, at most 2 gh calls a poll), queues events in
<DataDir>\logs\events.jsonl and wakes the coordinator terminal through Orca.
Register only from the release checkout (C:/Users/YiCheng/stock-lab-release).
DataDir defaults to STOCK_DATA_DIR, then %USERPROFILE%\stock-lab-data; PythonPath
defaults to STOCK_PYTHON, then this checkout's .venv; OrcaPath defaults to
%LOCALAPPDATA%\Programs\orca\resources\bin\orca.exe (the scheduler's PATH has no orca).
All are written into the task's arguments.

The task runs as the current user with an interactive logon (no stored password), so
it only runs while that user is signed in. It starts at sign-in and is triggered again
every RestartMinutes: a monitor that is running ignores the new start (IgnoreNew), one
that died is started again, so a stop lasts at most RestartMinutes. It has no time
limit and is hidden. The monitor writes <DataDir>\logs\monitor.log and
monitor-heartbeat.json; the watchdog comments on #1 when that heartbeat is more than
10 minutes old.

-RecordOnly registers the monitor with --record-only (queue events, no wake, no
comment). Add -WhatIf to print what would be registered without changing anything.
-Unregister removes the task and creates <DataDir>\logs\monitor.stop, which ends the
running monitor after its current poll (stopping the task may end only the PowerShell
that hosts bash).

.EXAMPLE
./tools/ops/Register-Monitor.ps1 -WhatIf

.EXAMPLE
./tools/ops/Register-Monitor.ps1

.EXAMPLE
./tools/ops/Register-Monitor.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Alias('Python')]
    [string]$PythonPath,
    [string]$DataDir,
    [string]$BashPath,
    [string]$OrcaPath,
    [ValidateRange(60, 3600)]
    [int]$IntervalSeconds = 60,
    [ValidateRange(1, 10)]
    [int]$RestartMinutes = 5,
    [switch]$RecordOnly,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskPath = '\stock-lab\'
$taskName = 'monitor'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$monitorScript = Join-Path $PSScriptRoot 'monitor.sh'

if (-not $DataDir) { $DataDir = if ($env:STOCK_DATA_DIR) { $env:STOCK_DATA_DIR } else { Join-Path $env:USERPROFILE 'stock-lab-data' } }
$DataDir = [IO.Path]::GetFullPath($DataDir)
$logPath = Join-Path $DataDir 'logs\monitor.log'

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Output "No task $taskPath$taskName to remove"
        return
    }
    if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Confirm:$false
        # Stopping the task may end only the hosting PowerShell; the stop file ends bash
        # after its current poll.
        $stopFile = Join-Path $DataDir 'logs\monitor.stop'
        if (Test-Path -LiteralPath (Split-Path $stopFile) -PathType Container) {
            New-Item -ItemType File -Path $stopFile -Force | Out-Null
        }
        Write-Output "Removed $taskPath$taskName; monitor asked to stop with $stopFile"
    }
    return
}

if (-not $BashPath) { $BashPath = Join-Path $env:ProgramFiles 'Git\bin\bash.exe' }
if (-not (Test-Path -LiteralPath $BashPath -PathType Leaf)) {
    throw "Git Bash not found; pass -BashPath (got: '$BashPath')"
}
if (-not $PythonPath) { $PythonPath = $env:STOCK_PYTHON }
if (-not $PythonPath) {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonPath = $venvPython }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found; pass -PythonPath or set STOCK_PYTHON (got: '$PythonPath')"
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not $OrcaPath) { $OrcaPath = Join-Path $env:LOCALAPPDATA 'Programs\orca\resources\bin\orca.exe' }
if (-not (Test-Path -LiteralPath $OrcaPath -PathType Leaf)) {
    throw "Orca CLI not found; pass -OrcaPath (got: '$OrcaPath')"
}
$OrcaPath = (Resolve-Path -LiteralPath $OrcaPath).Path
# Bash gets forward-slash paths; a hidden PowerShell hosts it so no console window shows.
function ConvertTo-BashPath([string]$path) { return $path.Replace('\', '/') }
$bashArguments = @(
    (ConvertTo-BashPath $monitorScript),
    '--interval', "$IntervalSeconds",
    '--data-dir', (ConvertTo-BashPath $DataDir),
    '--python', (ConvertTo-BashPath $PythonPath),
    '--orca', (ConvertTo-BashPath $OrcaPath)
)
if ($RecordOnly) { $bashArguments += '--record-only' }
$quoted = ($bashArguments | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '
$command = "& '{0}' {1}; exit `$LASTEXITCODE" -f $BashPath.Replace("'", "''"), $quoted
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$command`""

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$start = (Get-Date).AddMinutes(1)
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $user),
    (New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $RestartMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650))
)
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$mode = if ($RecordOnly) { ' (record-only)' } else { '' }
$description = "stock-lab coordinator event monitor$mode, poll every $IntervalSeconds s. Checkout: $projectRoot. Log: $logPath"

Write-Output "Task:     $taskPath$taskName$mode"
Write-Output "Checkout: $projectRoot"
Write-Output "Bash:     $BashPath"
Write-Output "Python:   $PythonPath"
Write-Output "Orca:     $OrcaPath"
Write-Output "Data:     $DataDir"
Write-Output "Log:      $logPath"
Write-Output "Trigger:  at logon of $user; every $RestartMinutes min from $($start.ToString('yyyy-MM-dd HH:mm')) (local), ignored while running"
Write-Output "Action:   powershell.exe $arguments"
if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Register scheduled task')) {
    Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $taskName
    Write-Output "Registered. Next run: $($info.NextRunTime)"
}
