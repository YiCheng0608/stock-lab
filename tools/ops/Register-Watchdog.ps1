<#
.SYNOPSIS
Create, update or remove the Windows Task Scheduler task for the coordinator watchdog.

.DESCRIPTION
Registers \stock-lab\watchdog, which runs tools/ops/ensure_coordinator.sh with
Git Bash every 15 minutes from this checkout. Register only from the release
checkout (C:/Users/YiCheng/stock-lab-release, a clone that stays on
origin/master); the watchdog reads the handoff text from this checkout's
docs/GITHUB_WORKFLOW.md. DataDir defaults to STOCK_DATA_DIR, then
%USERPROFILE%\stock-lab-data; PythonPath (used only for parsing JSON and the
read-only database check) defaults to STOCK_PYTHON, then this checkout's .venv.
Both are written into the task's arguments.

The task runs as the current user with an interactive logon (no stored
password), so it only runs while that user is signed in, which Orca needs
anyway. It is hidden, starts a missed run after sign-in, never runs two
instances at once and is stopped after 10 minutes. The watchdog writes
<DataDir>\logs\ensure_coordinator.log.

-DryRun registers the task with --dry-run (decide and log only); use it to
check the scheduled environment with Start-ScheduledTask before the real
registration. Add -WhatIf to print what would be registered without changing
anything.

.EXAMPLE
./tools/ops/Register-Watchdog.ps1 -WhatIf

.EXAMPLE
./tools/ops/Register-Watchdog.ps1

.EXAMPLE
./tools/ops/Register-Watchdog.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Alias('Python')]
    [string]$PythonPath,
    [string]$DataDir,
    [string]$BashPath,
    [ValidateRange(5, 60)]
    [int]$IntervalMinutes = 15,
    [switch]$DryRun,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskPath = '\stock-lab\'
$taskName = 'watchdog'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$watchdogScript = Join-Path $PSScriptRoot 'ensure_coordinator.sh'

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
if (-not $DataDir) { $DataDir = if ($env:STOCK_DATA_DIR) { $env:STOCK_DATA_DIR } else { Join-Path $env:USERPROFILE 'stock-lab-data' } }
$DataDir = [IO.Path]::GetFullPath($DataDir)
$logPath = Join-Path $DataDir 'logs\ensure_coordinator.log'

# Bash gets forward-slash paths; a hidden PowerShell hosts it so no console
# window flashes every run.
function ConvertTo-BashPath([string]$path) { return $path.Replace('\', '/') }
$bashArguments = @(
    (ConvertTo-BashPath $watchdogScript),
    '--data-dir', (ConvertTo-BashPath $DataDir),
    '--python', (ConvertTo-BashPath $PythonPath)
)
if ($DryRun) { $bashArguments += '--dry-run' }
$quoted = ($bashArguments | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '
$command = "& '{0}' {1}; exit `$LASTEXITCODE" -f $BashPath.Replace("'", "''"), $quoted
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$command`""

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$mode = if ($DryRun) { ' (dry-run)' } else { '' }
$description = "stock-lab coordinator watchdog$mode every $IntervalMinutes min. Checkout: $projectRoot. Log: $logPath"

Write-Output "Task:     $taskPath$taskName$mode"
Write-Output "Checkout: $projectRoot"
Write-Output "Bash:     $BashPath"
Write-Output "Python:   $PythonPath"
Write-Output "Data:     $DataDir"
Write-Output "Log:      $logPath"
Write-Output "Trigger:  every $IntervalMinutes min from $($start.ToString('yyyy-MM-dd HH:mm')) (local)"
Write-Output "Action:   powershell.exe $arguments"
if ($PSCmdlet.ShouldProcess("$taskPath$taskName", 'Register scheduled task')) {
    Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $taskName
    Write-Output "Registered. Next run: $($info.NextRunTime)"
}
