<#
.SYNOPSIS
Create, update or remove the Windows Task Scheduler task for the daily job.

.DESCRIPTION
Registers \stock-lab\<TaskName>, which runs tools/Invoke-DailyJob.ps1 from
this checkout every Monday to Friday at the given Taipei times (default
15:30 with retries at 18:30 and 21:30). Exchange holidays are not encoded
in the trigger: on a weekday without a session the job records
non_trading_day. A retry after a successful run only records an
already_complete row and does not touch market data.

The task runs as the current user with an interactive logon (no stored
password), so it only runs while that user is signed in; StartWhenAvailable
runs a missed trigger after sign-in. A new instance is not started while the
previous one is still running.

Add -WhatIf to print what would be registered without changing anything.

.EXAMPLE
./tools/Register-DailySchedule.ps1 -PythonPath C:\path\to\.venv\Scripts\python.exe -WhatIf

.EXAMPLE
./tools/Register-DailySchedule.ps1 -PythonPath C:\path\to\.venv\Scripts\python.exe -DataDir D:\stock-lab\data

.EXAMPLE
./tools/Register-DailySchedule.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$TaskName = 'stock-lab-daily',
    [string]$PythonPath,
    [string]$DataDir,
    [string]$LogDir,
    [string[]]$TaipeiTimes = @('15:30', '18:30', '21:30'),
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskPath = '\stock-lab\'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$invokeScript = Join-Path $PSScriptRoot 'Invoke-DailyJob.ps1'

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Output "No task $taskPath$TaskName to remove"
        return
    }
    if ($PSCmdlet.ShouldProcess("$taskPath$TaskName", 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -Confirm:$false
        Write-Output "Removed $taskPath$TaskName"
    }
    return
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
if (-not $DataDir) { $DataDir = if ($env:STOCK_DATA_DIR) { $env:STOCK_DATA_DIR } else { Join-Path $projectRoot 'data' } }
$DataDir = [IO.Path]::GetFullPath($DataDir)
if (-not $LogDir) { $LogDir = Join-Path $DataDir 'logs' }
$LogDir = [IO.Path]::GetFullPath($LogDir)
if (-not (Test-Path -LiteralPath (Join-Path $DataDir 'stock.db') -PathType Leaf)) {
    throw "No initialized database at $(Join-Path $DataDir 'stock.db'); run worker.cli init-db against the intended database first"
}

# Task Scheduler triggers use the machine's local time; convert the Taipei
# wall-clock times so the task fires at the same Taipei time on any machine.
$taipei = [TimeZoneInfo]::FindSystemTimeZoneById('Taipei Standard Time')
$weekdays = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$triggers = @()
$localTimes = @()
foreach ($value in $TaipeiTimes) {
    $parsed = [DateTime]::ParseExact($value, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
    # A Monday, to detect a trigger that would move to another local weekday.
    $taipeiMoment = [DateTime]::SpecifyKind((Get-Date -Year 2026 -Month 1 -Day 5 -Hour $parsed.Hour -Minute $parsed.Minute -Second 0 -Millisecond 0), 'Unspecified')
    $local = [TimeZoneInfo]::ConvertTime($taipeiMoment, $taipei, [TimeZoneInfo]::Local)
    if ($local.Date -ne $taipeiMoment.Date) {
        throw "Taipei $value falls on another local weekday ($local); register on a machine whose local date matches Taipei at that time"
    }
    $localTimes += $local.ToString('HH:mm')
    $triggers += New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $local
}

$arguments = @(
    '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
    '-File', ('"' + $invokeScript + '"'),
    '-PythonPath', ('"' + $PythonPath + '"'),
    '-DataDir', ('"' + $DataDir + '"'),
    '-LogDir', ('"' + $LogDir + '"'),
    '-Trigger', 'scheduler'
) -join ' '
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$description = "stock-lab daily collect/analyze/evaluate (Taipei $($TaipeiTimes -join ', '), Mon-Fri). " +
    "Checkout: $projectRoot. Logs: $LogDir. Run log: python -m worker.cli schedule-runs"

Write-Output "Task:     $taskPath$TaskName"
Write-Output "Checkout: $projectRoot"
Write-Output "Python:   $PythonPath"
Write-Output "Data:     $DataDir"
Write-Output "Logs:     $LogDir"
Write-Output ("Triggers: Mon-Fri Taipei {0} (local {1})" -f ($TaipeiTimes -join ', '), ($localTimes -join ', '))
if ($PSCmdlet.ShouldProcess("$taskPath$TaskName", 'Register scheduled task')) {
    Register-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $TaskName
    Write-Output "Registered. Next run: $($info.NextRunTime)"
}
