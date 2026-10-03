param(
    [string]$PythonPath,
    [string[]]$DependencyRoots,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9]{8}$')]
    [string]$RunOwner,
    [Parameter(Mandatory = $true)]
    [string]$ValidationRoot
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testFile = Join-Path $projectRoot 'backend/tests/test_stock_day_selected_invalid_file_integration.py'
if (-not $PythonPath) {
    $PythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python missing: $PythonPath" }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not $DependencyRoots) {
    $DependencyRoots = @((Join-Path $projectRoot 'backend/.deps'), (Join-Path $projectRoot 'backend/.validation-deps'))
}
$resolvedDependencies = @($DependencyRoots | ForEach-Object {
    $_ -split ';' | Where-Object { $_ } | ForEach-Object {
        if (-not (Test-Path -LiteralPath $_ -PathType Container)) { throw "Dependency root missing: $_" }
        (Resolve-Path -LiteralPath $_).Path
    }
})
$tempBase = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Temp'))
$validationRoot = [IO.Path]::GetFullPath($ValidationRoot)
$leafPattern = '^taiwan-stock-r1a2-si-' + [regex]::Escape($RunOwner) + '-[a-f0-9]{32}$'
if ([IO.Path]::GetDirectoryName($validationRoot) -ne $tempBase -or
    [IO.Path]::GetFileName($validationRoot) -cnotmatch $leafPattern -or
    $validationRoot.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ValidationRoot must be the explicitly owned immediate child of LocalAppData/Temp, outside the repository'
}
if (Test-Path -LiteralPath $validationRoot) { throw "Validation root already exists; refusing reuse: $validationRoot" }
$dbPath = Join-Path $validationRoot 'data/selected-invalid.db'
$captureDir = Join-Path $validationRoot 'capture'
$rawDir = Join-Path $validationRoot 'raw'
$ownedFiles = @($dbPath, ($dbPath + '-journal'), (Join-Path $captureDir 'capture.zip'),
    (Join-Path $captureDir '.capture.lock'), (Join-Path $rawDir 'body.bin'),
    (Join-Path $rawDir 'receipt.json'), (Join-Path $rawDir '.stock-day.lock'))
$ownedDirectories = @($validationRoot, (Join-Path $validationRoot 'data'), $rawDir, $captureDir)
$testEnvironment = @{
    STOCK_DATA_DIR = Join-Path $validationRoot 'data'
    STOCK_DB_PATH = $dbPath
    STOCK_RAW_DIR = $rawDir
    STOCK_DAY_SELECTED_INVALID_VALIDATION_ROOT = $validationRoot
    STOCK_DAY_SELECTED_INVALID_RUN_OWNER = $RunOwner
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONPATH = (@((Join-Path $projectRoot 'backend')) + $resolvedDependencies) -join [IO.Path]::PathSeparator
    TEMP = $validationRoot
    TMP = $validationRoot
}
$savedEnvironment = @{}
$rootCreated = $false
$testExit = 1
$cleanupExit = 0
$metrics = @()
$cleanupFailures = @()
$executionFailure = $null

function Get-OwnedInventory {
    param([switch]$ReportOnly)
    if (-not (Test-Path -LiteralPath $validationRoot)) { return @() }
    $target = Get-Item -LiteralPath $validationRoot -Force
    if ($target.FullName -ne $validationRoot -or [IO.Path]::GetDirectoryName($target.FullName) -ne $tempBase -or
        $target.Name -cnotmatch $leafPattern) { throw 'Validation cleanup path mismatch' }
    if ($target.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Validation root is a reparse point: $validationRoot" }
    $items = @($target) + @(Get-ChildItem -LiteralPath $validationRoot -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Validation cleanup refused a reparse point: $validationRoot"
    }
    if (-not $ReportOnly) {
        foreach ($item in $items) {
            if ($item.PSIsContainer -and $item.FullName -notin $ownedDirectories) {
                throw "Unexpected validation directory: $($item.FullName)"
            }
            if (-not $item.PSIsContainer) {
                $stage = $item.DirectoryName -eq $captureDir -and $item.Name -cmatch '^\.capture-[A-Za-z0-9_-]+\.tmp$'
                if ($item.FullName -notin $ownedFiles -and -not $stage) { throw "Unexpected validation file: $($item.FullName)" }
            }
        }
    }
    return $items
}

try {
    New-Item -ItemType Directory -Path $validationRoot -ErrorAction Stop | Out-Null
    $rootCreated = $true
    foreach ($name in $testEnvironment.Keys) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $testEnvironment[$name], 'Process')
    }
    Write-Output "Validation root: $validationRoot"
    $testProcess = New-Object System.Diagnostics.Process
    try {
        $testProcess.StartInfo.FileName = $PythonPath
        $testProcess.StartInfo.Arguments = '-B -Xutf8 "' + $testFile + '"'
        $testProcess.StartInfo.WorkingDirectory = $projectRoot
        $testProcess.StartInfo.UseShellExecute = $false
        $testProcess.StartInfo.CreateNoWindow = $true
        $testProcess.StartInfo.RedirectStandardOutput = $true
        $testProcess.StartInfo.RedirectStandardError = $true
        $testProcess.StartInfo.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $testProcess.StartInfo.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
        if (-not $testProcess.Start()) { throw 'Could not start the owned test process' }
        $stdoutTask = $testProcess.StandardOutput.ReadToEndAsync()
        $stderrTask = $testProcess.StandardError.ReadToEndAsync()
        if (-not $testProcess.WaitForExit(60000)) {
            $testProcess.Kill()
            if (-not $testProcess.WaitForExit(5000)) { throw 'Owned test process did not stop' }
            $testExit = 124
        } else { $testExit = $testProcess.ExitCode }
        foreach ($line in @($stdoutTask.Result -split '\r?\n' | Where-Object { $_ })) {
            Write-Output $line
            if ($line.StartsWith('R1A2_SELECTED_INVALID_METRICS=')) {
                $metrics += ($line.Substring('R1A2_SELECTED_INVALID_METRICS='.Length) | ConvertFrom-Json)
            }
        }
        if ($stderrTask.Result) { Write-Output $stderrTask.Result.TrimEnd() }
    } finally { $testProcess.Dispose() }
    if ($metrics.Count -ne 1 -or $metrics[0].tests_run -ne 1 -or $metrics[0].skipped -ne 0) {
        if ($testExit -eq 0) { $testExit = 1 }
    }
    $items = @(Get-OwnedInventory)
    $files = @($items | Where-Object { -not $_.PSIsContainer })
    $directories = @($items | Where-Object { $_.PSIsContainer })
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    if ($files.Count -gt 5 -or $directories.Count -gt 4 -or $bytes -gt 2MB) {
        throw 'Validation disk budget exceeded at process exit'
    }
    foreach ($file in $files) {
        $limit = switch ($file.Name) {
            'selected-invalid.db' { 1MB }
            'capture.zip' { 64KB }
            'body.bin' { 32KB }
            'receipt.json' { 32KB }
            default { if ($file.Name -cmatch '^\.capture-[A-Za-z0-9_-]+\.tmp$') { 64KB } else { 2MB } }
        }
        if ($file.Length -gt $limit) { throw "Validation file size limit exceeded: $($file.FullName)" }
    }
} catch {
    if ($testExit -eq 0) { $testExit = 1 }
    $executionFailure = $_.Exception.Message
    Write-Output "Validation execution failure: $executionFailure"
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    if ($rootCreated -and (Test-Path -LiteralPath $validationRoot)) {
        try {
            $null = @(Get-OwnedInventory)
            Remove-Item -LiteralPath $validationRoot -Recurse -Force -ErrorAction Stop
        } catch {
            $cleanupExit = 1
            $cleanupFailures += $_.Exception.Message
        }
    }
}
$residuals = @()
if (Test-Path -LiteralPath $validationRoot) {
    try {
        $residuals = @(Get-OwnedInventory -ReportOnly | ForEach-Object {
            [ordered]@{ path = $_.FullName; bytes = $(if ($_.PSIsContainer) { 0 } else { $_.Length })
                reason = ($cleanupFailures -join '; ') }
        })
    } catch { $residuals = @([ordered]@{ path = $validationRoot; bytes = $null; reason = $_.Exception.Message }) }
}
Write-Output ('R1A2_SELECTED_INVALID_RESULT=' + ([ordered]@{
    test_exit = $testExit; cleanup_exit = $cleanupExit
    validation_complete = ($metrics.Count -eq 1 -and $metrics[0].tests_run -eq 1 -and $metrics[0].skipped -eq 0)
    metrics_received = $metrics.Count; peaks = $(if ($metrics.Count) { $metrics[0].peaks } else { $null })
    residuals = $residuals; cleanup_failures = $cleanupFailures; execution_failure = $executionFailure
    validation_root = $validationRoot; root_exists_after_cleanup = (Test-Path -LiteralPath $validationRoot)
} | ConvertTo-Json -Compress -Depth 6))
if ($testExit -ne 0) { exit $testExit }
exit $cleanupExit
