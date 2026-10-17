<#
.SYNOPSIS
Create, update or remove the Windows Task Scheduler task for one worker job.

.DESCRIPTION
Registers \stock-lab\<Job>, which runs tools/Invoke-WorkerJob.ps1 -GitPull
from this checkout. Register only from the release checkout (a clone that
stays on origin/master), never from a working or task checkout: every run
first fast-forwards it. DataDir defaults to STOCK_DATA_DIR, then
%USERPROFILE%\stock-lab-data.

  daily  Monday to Friday at the given Taipei times (default 18:30, retried at
         21:30 because institutional and margin data publish late). Exchange
         holidays are not encoded in the trigger: on a weekday without a
         session the job records non_trading_day. The retry after a
         successful run only records an already_complete row and does not
         touch data; after a partial run it completes the day.
  news   Every IntervalHours hours (default 2), every day, starting at the
         next whole interval in Taipei time.

The task runs as the current user with an interactive logon (no stored
password), so it only runs while that user is signed in; StartWhenAvailable
runs a missed trigger after sign-in. A new instance is not started while the
previous one is still running.

Add -WhatIf to print what would be registered without changing anything.

.EXAMPLE
./tools/Register-WorkerSchedule.ps1 -Job daily -PythonPath C:\path\to\.venv\Scripts\python.exe -WhatIf

.EXAMPLE
./tools/Register-WorkerSchedule.ps1 -Job news -PythonPath C:\path\to\.venv\Scripts\python.exe

.EXAMPLE
./tools/Register-WorkerSchedule.ps1 -Job daily -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('daily', 'news')]
    [string]$Job,
    [Alias('Python')]
    [string]$PythonPath,
    [string]$DataDir,
    [string]$LogDir,
    [string[]]$TaipeiTimes = @('18:30', '21:30'),
    [ValidateRange(1, 12)]
    [int]$IntervalHours = 2,
    # Passed to Invoke-WorkerJob.ps1 -MinFreeMemoryGB; a full-market analyze
    # peaks around 5-5.5 GB, while news is light.
    [ValidateRange(0, 1024)]
    [double]$DailyMinFreeMemoryGB = 6,
    [ValidateRange(0, 1024)]
    [double]$NewsMinFreeMemoryGB = 1,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskPath = '\stock-lab\'
$taskName = $Job
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$invokeScript = Join-Path $PSScriptRoot 'Invoke-WorkerJob.ps1'

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Output "No task $taskPath$taskName to remove"
        return
    }
    if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Confirm:$false
        Write-Output "Removed $taskPath$taskName"
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
if (-not $DataDir) { $DataDir = if ($env:STOCK_DATA_DIR) { $env:STOCK_DATA_DIR } else { Join-Path $env:USERPROFILE 'stock-lab-data' } }
$DataDir = [IO.Path]::GetFullPath($DataDir.TrimEnd([char[]]@([char]92, [char]47)))
if (-not $LogDir) { $LogDir = Join-Path $DataDir 'logs' }
$LogDir = [IO.Path]::GetFullPath($LogDir)
if (-not (Test-Path -LiteralPath (Join-Path $DataDir 'stock.db') -PathType Leaf)) {
    throw "No initialized database at $(Join-Path $DataDir 'stock.db'); run worker.cli init-db against the intended database first"
}

# Task Scheduler triggers use the machine's local time; convert Taipei
# wall-clock times so the task fires at the same Taipei time on any machine.
$taipei = [TimeZoneInfo]::FindSystemTimeZoneById('Taipei Standard Time')
$triggers = @()
if ($Job -eq 'daily') {
    $weekdays = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
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
    $when = "Mon-Fri Taipei {0} (local {1})" -f ($TaipeiTimes -join ', '), ($localTimes -join ', ')
    # Same as the abandoned-run limit in worker.schedule_runs and clearly
    # shorter than the 3 hours between the default triggers.
    $timeLimit = New-TimeSpan -Hours 2 -Minutes 30
    $minFreeMemoryGB = $DailyMinFreeMemoryGB
} else {
    $nowTaipei = [TimeZoneInfo]::ConvertTime([DateTime]::Now, $taipei)
    $startTaipei = $nowTaipei.Date.AddHours(([Math]::Floor($nowTaipei.Hour / $IntervalHours) + 1) * $IntervalHours)
    $startLocal = [TimeZoneInfo]::ConvertTime([DateTime]::SpecifyKind($startTaipei, 'Unspecified'), $taipei, [TimeZoneInfo]::Local)
    $triggers += New-ScheduledTaskTrigger -Once -At $startLocal -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $when = "every $IntervalHours h from Taipei $($startTaipei.ToString('yyyy-MM-dd HH:mm')) (local $($startLocal.ToString('yyyy-MM-dd HH:mm')))"
    $timeLimit = New-TimeSpan -Minutes 90
    $minFreeMemoryGB = $NewsMinFreeMemoryGB
}

$arguments = @(
    '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
    '-File', ('"' + $invokeScript + '"'),
    '-Job', $Job,
    '-PythonPath', ('"' + $PythonPath + '"'),
    '-DataDir', ('"' + $DataDir + '"'),
    '-LogDir', ('"' + $LogDir + '"'),
    '-Trigger', 'scheduler',
    '-MinFreeMemoryGB', ([string]$minFreeMemoryGB),
    '-GitPull'
) -join ' '
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit $timeLimit -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$description = "stock-lab $Job ($when). Checkout: $projectRoot. Logs: $LogDir\$Job-YYYYMMDD.log"

Write-Output "Task:     $taskPath$taskName"
Write-Output "Checkout: $projectRoot"
Write-Output "Python:   $PythonPath"
Write-Output "Data:     $DataDir"
Write-Output "Logs:     $LogDir\$Job-YYYYMMDD.log"
Write-Output "Trigger:  $when"
Write-Output "Limits:   run at most $timeLimit; skip below $minFreeMemoryGB GB free memory"
if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Register scheduled task')) {
    Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $taskName
    Write-Output "Registered. Next run: $($info.NextRunTime)"
}
