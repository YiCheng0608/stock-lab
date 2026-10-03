param(
    [string]$PythonPath,
    [Parameter(Mandatory = $true)]
    [string[]]$DependencyRoots,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9]{8}$')]
    [string]$RunOwner,
    [Parameter(Mandatory = $true)]
    [string]$ValidationRoot
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testFile = Join-Path $projectRoot 'backend/tests/test_legacy_daily_volume_file_integration.py'
if (-not $PythonPath) {
    $PythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python missing: $PythonPath" }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$resolvedDependencies = @($DependencyRoots | ForEach-Object {
    $_ -split ';' | Where-Object { $_ } | ForEach-Object {
        if (-not (Test-Path -LiteralPath $_ -PathType Container)) { throw "Dependency root missing: $_" }
        (Resolve-Path -LiteralPath $_).Path
    }
})
if (-not $resolvedDependencies.Count) { throw 'At least one read-only dependency root is required' }
$tempBase = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Temp'))
$validationRoot = [IO.Path]::GetFullPath($ValidationRoot)
$leafPattern = '^taiwan-stock-r1a2-lv-' + [regex]::Escape($RunOwner) + '-[a-f0-9]{32}$'
if ([IO.Path]::GetDirectoryName($validationRoot) -ne $tempBase -or
    [IO.Path]::GetFileName($validationRoot) -cnotmatch $leafPattern -or
    $validationRoot.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ValidationRoot must be the explicitly owned immediate child of LocalAppData/Temp, outside the repository'
}
if (Test-Path -LiteralPath $validationRoot) { throw "Validation root already exists; refusing reuse: $validationRoot" }
$dbPath = Join-Path $validationRoot 'data/legacy-volume.db'
$rawDir = Join-Path $validationRoot 'raw'
$ownedDirectories = @($validationRoot, (Join-Path $validationRoot 'data'), $rawDir)
$rawLeafDirectories = @()
foreach ($source in @('twse', 'tpex')) {
    $currentDirectory = Join-Path $rawDir $source
    $ownedDirectories += $currentDirectory
    foreach ($component in @('2026', '09', '05')) {
        $currentDirectory = Join-Path $currentDirectory $component
        $ownedDirectories += $currentDirectory
    }
    $rawLeafDirectories += $currentDirectory
}
$fixedFiles = @($dbPath, ($dbPath + '-journal'))
$testEnvironment = @{
    STOCK_DATA_DIR = Join-Path $validationRoot 'data'
    STOCK_DB_PATH = $dbPath
    STOCK_RAW_DIR = $rawDir
    LEGACY_DAILY_VOLUME_VALIDATION_ROOT = $validationRoot
    LEGACY_DAILY_VOLUME_RUN_OWNER = $RunOwner
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
    # Traverse known directories one level at a time, checking every child
    # before descending. A reparse point never reaches recursive enumeration.
    $items = @($target)
    $pendingDirectories = New-Object 'System.Collections.Generic.Queue[string]'
    $pendingDirectories.Enqueue($validationRoot)
    while ($pendingDirectories.Count) {
        $directory = $pendingDirectories.Dequeue()
        foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force)) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Validation cleanup refused a reparse point: $($item.FullName)"
            }
            $items += $item
            if ($item.PSIsContainer) {
                if ($item.FullName -notin $ownedDirectories) {
                    if (-not $ReportOnly) { throw "Unexpected validation directory: $($item.FullName)" }
                } else { $pendingDirectories.Enqueue($item.FullName) }
            } elseif (-not $ReportOnly) {
                $raw = $item.DirectoryName -in $rawLeafDirectories -and $item.Name -cmatch '^[a-f0-9]{64}(\.meta)?\.json$'
                if ($item.FullName -notin $fixedFiles -and -not $raw) { throw "Unexpected validation file: $($item.FullName)" }
            }
        }
    }
    return $items
}

function Assert-OwnedBudget {
    param($Items)
    $files = @($Items | Where-Object { -not $_.PSIsContainer })
    $directories = @($Items | Where-Object { $_.PSIsContainer })
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    if ($files.Count -gt 14 -or $directories.Count -gt 11 -or $bytes -gt 3MB) {
        throw 'Validation disk budget exceeded at process exit'
    }
    $rawBodies = @($files | Where-Object { $_.DirectoryName -in $rawLeafDirectories -and $_.Name -cmatch '^[a-f0-9]{64}\.json$' })
    $rawMetadata = @($files | Where-Object { $_.DirectoryName -in $rawLeafDirectories -and $_.Name -cmatch '^[a-f0-9]{64}\.meta\.json$' })
    if ($rawBodies.Count -gt 6 -or $rawMetadata.Count -gt 6) { throw 'More than six target captures on disk' }
    foreach ($file in $files) {
        $limit = if ($file.FullName -in $fixedFiles) { 1MB } elseif ($file.Name.EndsWith('.meta.json')) { 8KB } else { 32KB }
        if ($file.Length -gt $limit) { throw "Validation file size limit exceeded: $($file.FullName)" }
    }
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
            if ($line.StartsWith('R1A2_LEGACY_VOLUME_METRICS=')) {
                $metrics += ($line.Substring('R1A2_LEGACY_VOLUME_METRICS='.Length) | ConvertFrom-Json)
            }
        }
        if ($stderrTask.Result) { Write-Output $stderrTask.Result.TrimEnd() }
    } finally { $testProcess.Dispose() }
    if ($metrics.Count -ne 1 -or $metrics[0].tests_run -ne 1 -or $metrics[0].skipped -ne 0) {
        if ($testExit -eq 0) { $testExit = 1 }
    }
    Assert-OwnedBudget -Items @(Get-OwnedInventory)
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
Write-Output ('R1A2_LEGACY_VOLUME_RESULT=' + ([ordered]@{
    test_exit = $testExit; cleanup_exit = $cleanupExit
    validation_complete = ($metrics.Count -eq 1 -and $metrics[0].tests_run -eq 1 -and $metrics[0].skipped -eq 0)
    metrics_received = $metrics.Count; peaks = $(if ($metrics.Count) { $metrics[0].peaks } else { $null })
    residuals = $residuals; cleanup_failures = $cleanupFailures; execution_failure = $executionFailure
    validation_root = $validationRoot; root_exists_after_cleanup = (Test-Path -LiteralPath $validationRoot)
} | ConvertTo-Json -Compress -Depth 6))
if ($testExit -ne 0) { exit $testExit }
exit $cleanupExit
