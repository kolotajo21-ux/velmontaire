$ErrorActionPreference = "Stop"

$root = "C:\TradingBot"
$source = $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "C:\TradingBot_backup_M1_SCALPING_V8_1_$stamp"

$files = @(
    "modules\entry\m1_ifvg_fvg_rejection.py",
    "strategy_parser\parser.py",
    "strategy_compiler\compiler.py",
    "strategy_runtime\trade_plan.py",
    "generic_backtest\runner.py",
    "tests\velmontaire_m1_scalping_strategy_contract_test.py",
    "VELMONTAIRE_M1_SCALPING_STRATEGY.txt"
)

if (-not (Test-Path -LiteralPath $root)) { throw "TradingBot root not found: $root" }
foreach ($relative in $files) {
    $sourceFile = Join-Path $source $relative
    if (-not (Test-Path -LiteralPath $sourceFile)) { throw "Update file missing: $sourceFile" }
}

foreach ($relative in $files) {
    $targetFile = Join-Path $root $relative
    if (Test-Path -LiteralPath $targetFile) {
        $backupFile = Join-Path $backup $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $backupFile) | Out-Null
        Copy-Item -LiteralPath $targetFile -Destination $backupFile -Force
    }
}

foreach ($relative in $files) {
    $sourceFile = Join-Path $source $relative
    $targetFile = Join-Path $root $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $targetFile) | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $targetFile -Force
}

Push-Location $root
try {
    $env:PYTHONPATH = $root
    python -m py_compile `
        modules\entry\m1_ifvg_fvg_rejection.py `
        strategy_parser\parser.py `
        strategy_compiler\compiler.py `
        strategy_runtime\trade_plan.py `
        generic_backtest\runner.py `
        tests\velmontaire_m1_scalping_strategy_contract_test.py
    if ($LASTEXITCODE -ne 0) { throw "Python compile check failed" }

    python tests\velmontaire_m1_scalping_strategy_contract_test.py
    if ($LASTEXITCODE -ne 0) { throw "M1 scalping contract failed" }

    python tests\velmontaire_limit_atr_first_tap_regression_test.py
    if ($LASTEXITCODE -ne 0) { throw "Existing V7 ATR/first-tap regression failed" }

    python tests\velmontaire_limit_long_candidate_contract_test.py
    if ($LASTEXITCODE -ne 0) { throw "Existing LIMIT LONG contract failed" }

    python tests\velmontaire_all_in_risk_regression_test.py
    if ($LASTEXITCODE -ne 0) { throw "Existing risk regression failed" }

    python tests\velmontaire_trade_plan_rejection_regression_test.py
    if ($LASTEXITCODE -ne 0) { throw "Existing trade-plan regression failed" }

    python -c "from generic_backtest.runner import ProductionGenericHistoricalRunner as R; print('HOTFIX:', R.HOTFIX_VERSION)"
    if ($LASTEXITCODE -ne 0) { throw "Installed runtime inspection failed" }
}
finally { Pop-Location }

Write-Host "VELMONTAIRE M1 SCALPING V8.1 INSTALLED"
Write-Host "BACKUP: $backup"
Write-Host "Existing strategies and immutable versions were not modified."
Write-Host "Next: restart the server and create a NEW strategy from VELMONTAIRE_M1_SCALPING_STRATEGY.txt."
