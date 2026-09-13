param(
    [string[]]$TestPaths = @('backend/tests/test_database_readiness.py'),
    [string]$PythonPath,
    [switch]$KeepArtifacts
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testsRoot = Join-Path $projectRoot 'backend/tests'
$resolvedTests = @($TestPaths | ForEach-Object {
    $testPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $_))
    if ($testPath -ne $testsRoot -and -not $testPath.StartsWith($testsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Test must be within backend/tests: $testPath"
    }
    if (-not (Test-Path -LiteralPath $testPath)) { throw "Test path missing: $testPath" }
    $testPath
})
if (-not $resolvedTests.Count) { throw 'At least one test path is required' }
if (-not $PythonPath) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    $PythonPath = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { (Get-Command python -ErrorAction Stop).Source }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python executable missing: $PythonPath" }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

# Snapshot readers reject project-local databases, including synthetic ones.
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
if ($tempBase -eq $projectRoot -or $tempBase.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'TEMP must be outside the project for snapshot comparison tests'
}
$validationRoot = Join-Path $tempBase ('taiwan-stock-validation-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $validationRoot -ErrorAction Stop | Out-Null
$testEnvironment = @{
    STOCK_DATA_DIR = Join-Path $validationRoot 'data'
    STOCK_DB_PATH = Join-Path $validationRoot 'data/stock.db'
    STOCK_RAW_DIR = Join-Path $validationRoot 'raw'
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONPATH = (@('backend','backend/.deps','backend/.validation-deps') | ForEach-Object { Join-Path $projectRoot $_ }) -join [IO.Path]::PathSeparator
    TEMP = $validationRoot
    TMP = $validationRoot
}
$savedEnvironment = @{}
foreach ($name in $testEnvironment.Keys) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
Push-Location -LiteralPath $projectRoot
try {
    foreach ($name in $testEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $testEnvironment[$name], 'Process') }
    Write-Output "Isolated validation data: $validationRoot"
    & $PythonPath -Xutf8 -m pytest @resolvedTests -q --disable-warnings -rs -p no:cacheprovider --basetemp (Join-Path $validationRoot 'pytest')
    if ($LASTEXITCODE -ne 0) { throw "pytest failed: $LASTEXITCODE" }
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        if ($null -eq $savedEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable($name, [NullString]::Value, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
        }
    }
    Pop-Location
    if ($KeepArtifacts) {
        Write-Output "Preserved validation data: $validationRoot"
    } elseif (Test-Path -LiteralPath $validationRoot) {
        $target = Get-Item -LiteralPath $validationRoot -Force
        if ($target.FullName -ne $validationRoot -or [IO.Path]::GetDirectoryName($target.FullName) -ne $tempBase) { throw 'Validation cleanup path mismatch' }
        $items = @($target) + @(Get-ChildItem -LiteralPath $validationRoot -Recurse -Force)
        if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Validation cleanup refused a reparse point: $validationRoot" }
        Remove-Item -LiteralPath $validationRoot -Recurse -Force -ErrorAction Stop
    }
}
