param(
    [string]$PythonPath,
    [string[]]$DependencyRoots,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9]{8}$')]
    [string]$RunOwner
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testFile = Join-Path $projectRoot 'backend/tests/test_turnover_availability_file_migration.py'
if (-not $PythonPath) {
    $PythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python missing: $PythonPath" }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not $DependencyRoots) {
    $DependencyRoots = @((Join-Path $projectRoot 'backend/.deps'), (Join-Path $projectRoot 'backend/.validation-deps'))
}
# A semicolon-delimited value also works with Windows powershell.exe -File.
$resolvedDependencies = @($DependencyRoots | ForEach-Object {
    $_ -split ';' | Where-Object { $_ } | ForEach-Object {
        if (-not (Test-Path -LiteralPath $_ -PathType Container)) { throw "Dependency root missing: $_" }
        (Resolve-Path -LiteralPath $_).Path
    }
})
$tempBase = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Temp'))
$prefix = 'taiwan-stock-r1a2-' + $RunOwner + '-'
$validationRoot = [IO.Path]::GetFullPath((Join-Path $tempBase ($prefix + [guid]::NewGuid().ToString('N'))))
if ([IO.Path]::GetDirectoryName($validationRoot) -ne $tempBase -or
    $validationRoot.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Validation root must be an immediate child of LocalAppData/Temp outside the worktree'
}
$dbPath = Join-Path $validationRoot 'data/legacy.db'
$ownedFiles = @($dbPath, ($dbPath + '-journal'))
$ownedDirectories = @($validationRoot, (Join-Path $validationRoot 'data'), (Join-Path $validationRoot 'raw'))
$testEnvironment = @{
    STOCK_DATA_DIR = Join-Path $validationRoot 'data'
    STOCK_DB_PATH = $dbPath
    STOCK_RAW_DIR = Join-Path $validationRoot 'raw'
    TURNOVER_MIGRATION_VALIDATION_ROOT = $validationRoot
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONPATH = (@((Join-Path $projectRoot 'backend')) + $resolvedDependencies) -join [IO.Path]::PathSeparator
    TEMP = $validationRoot
    TMP = $validationRoot
}
$caseMethods = @(
    'test_legacy_values_survive_reopen_and_rerun',
    'test_synthetic_nullable_legacy_null_is_unverified',
    'test_initial_existing_status_is_authoritative',
    'test_failed_backfill_reopens_unchanged_and_retries_same_file'
)
$testExit = 0
$cleanupExit = 0
$executed = 0
$rootCreated = $false
$metrics = @()
$cleanupFailures = @()
$savedEnvironment = @{}

function Get-OwnedInventory {
    param([switch]$ReportOnly)
    if (-not (Test-Path -LiteralPath $validationRoot)) { return @() }
    $target = Get-Item -LiteralPath $validationRoot -Force
    if ($target.FullName -ne $validationRoot -or [IO.Path]::GetDirectoryName($target.FullName) -ne $tempBase -or
        -not $target.Name.StartsWith($prefix, [StringComparison]::Ordinal)) {
        throw 'Validation cleanup path mismatch'
    }
    $items = @($target) + @(Get-ChildItem -LiteralPath $validationRoot -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Validation cleanup refused a reparse point: $validationRoot"
    }
    if (-not $ReportOnly) {
        foreach ($item in $items) {
            if ($item.PSIsContainer -and $item.FullName -notin $ownedDirectories) {
                throw "Unexpected validation directory: $($item.FullName)"
            }
            if (-not $item.PSIsContainer -and $item.FullName -notin $ownedFiles) {
                throw "Unexpected validation file: $($item.FullName)"
            }
        }
    }
    return $items
}

function Remove-OwnedDatabase {
    $items = @(Get-OwnedInventory)
    foreach ($item in $items | Where-Object { -not $_.PSIsContainer }) {
        if ($item.FullName -notin $ownedFiles) { throw "Unexpected validation file: $($item.FullName)" }
    }
    foreach ($ownedPath in $ownedFiles) {
        if ([IO.Path]::GetDirectoryName($ownedPath) -ne (Join-Path $validationRoot 'data')) {
            throw "Owned DB cleanup path mismatch: $ownedPath"
        }
        if (Test-Path -LiteralPath $ownedPath) { Remove-Item -LiteralPath $ownedPath -Force -ErrorAction Stop }
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
    foreach ($className in @('AlembicFileMigrationTests', 'FallbackFileMigrationTests')) {
        foreach ($method in $caseMethods) {
            $caseName = $className + '.' + $method
            # Read both streams in memory; stderr progress/logging is not an exit code.
            $testProcess = New-Object System.Diagnostics.Process
            try {
                $testProcess.StartInfo.FileName = $PythonPath
                $testProcess.StartInfo.Arguments = '-B -Xutf8 "' + $testFile + '" "' + $caseName + '"'
                $testProcess.StartInfo.WorkingDirectory = $projectRoot
                $testProcess.StartInfo.UseShellExecute = $false
                $testProcess.StartInfo.CreateNoWindow = $true
                $testProcess.StartInfo.RedirectStandardOutput = $true
                $testProcess.StartInfo.RedirectStandardError = $true
                $testProcess.StartInfo.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
                $testProcess.StartInfo.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
                if (-not $testProcess.Start()) { throw "Could not start test case: $caseName" }
                $stdoutTask = $testProcess.StandardOutput.ReadToEndAsync()
                $stderrTask = $testProcess.StandardError.ReadToEndAsync()
                if (-not $testProcess.WaitForExit(60000)) {
                    $testProcess.Kill()
                    if (-not $testProcess.WaitForExit(5000)) { throw "Owned test process did not stop: $caseName" }
                    $caseExit = 124
                } else {
                    $caseExit = $testProcess.ExitCode
                }
                $caseOutput = @($stdoutTask.Result -split '\r?\n' | Where-Object { $_ })
                if ($stderrTask.Result) { Write-Output $stderrTask.Result.TrimEnd() }
            } finally {
                $testProcess.Dispose()
            }
            $executed++
            foreach ($line in $caseOutput) {
                Write-Output $line
                if ($line.StartsWith('R1A2_METRICS=')) {
                    $metrics += ($line.Substring('R1A2_METRICS='.Length) | ConvertFrom-Json)
                }
            }
            Write-Output "Test case: $caseName; exit=$caseExit"
            if ($caseExit -ne 0 -and $testExit -eq 0) { $testExit = $caseExit }
            try {
                $items = @(Get-OwnedInventory)
                $files = @($items | Where-Object { -not $_.PSIsContainer })
                $directories = @($items | Where-Object { $_.PSIsContainer })
                $bytes = ($files | Measure-Object -Property Length -Sum).Sum
                if ($files.Count -gt 2 -or $directories.Count -gt 3 -or $bytes -gt 2MB) {
                    throw 'Validation disk budget exceeded at process exit'
                }
                Remove-OwnedDatabase
            } catch {
                $cleanupExit = 1
                $cleanupFailures += $_.Exception.Message
                break
            }
        }
        if ($cleanupExit -ne 0) { break }
    }
    if ($cleanupExit -eq 0 -and ($executed -ne 8 -or $metrics.Count -ne 8 -or
        @($metrics | Where-Object { $_.tests_run -ne 1 -or $_.skipped -ne 0 }).Count)) {
        if ($testExit -eq 0) { $testExit = 1 }
    }
} catch {
    if ($testExit -eq 0) { $testExit = 1 }
    Write-Output "Validation execution failure: $($_.Exception.Message)"
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
    } catch {
        $residuals = @([ordered]@{ path = $validationRoot; bytes = $null; reason = $_.Exception.Message })
    }
}
$peaks = [ordered]@{}
foreach ($key in @('files', 'directories', 'bytes', 'db_bytes')) {
    $value = ($metrics | ForEach-Object { $_.peaks.$key } | Measure-Object -Maximum).Maximum
    $peaks[$key] = $(if ($null -eq $value) { 0 } else { $value })
}
Write-Output ('R1A2_RESULT=' + ([ordered]@{
    test_exit = $testExit; cleanup_exit = $cleanupExit; cases_executed = $executed
    validation_complete = ($executed -eq 8 -and $metrics.Count -eq 8 -and
        @($metrics | Where-Object { $_.tests_run -ne 1 -or $_.skipped -ne 0 }).Count -eq 0)
    metrics_received = $metrics.Count; peaks = $peaks; residuals = $residuals
    cleanup_failures = $cleanupFailures; validation_root = $validationRoot
} | ConvertTo-Json -Compress -Depth 6))
if ($testExit -ne 0) { exit $testExit }
exit $cleanupExit
