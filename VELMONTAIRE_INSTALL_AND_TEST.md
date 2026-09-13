# VELMONTAIRE: установка и проверка

Все команды ниже выполняются в PowerShell. Сервер перед заменой файлов должен
быть остановлен.

## 1. Распаковать обновление и сделать резервную копию

Положите `VELMONTAIRE_CORE_UPDATED.zip` в `C:\TradingBot`, затем выполните:

```powershell
cd C:\TradingBot
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "C:\TradingBot_backup_$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null

$changed = @(
  "strategy_parser\parser.py",
  "strategy_compiler\compiler.py",
  "core\context.py",
  "strategy_runtime\executor.py",
  "strategy_runtime\condition_evaluator.py",
  "strategy_runtime\trade_plan.py",
  "generic_backtest\runner.py",
  "generic_backtest\synthetic_dxy.py"
)

foreach ($relative in $changed) {
  $source = Join-Path "C:\TradingBot" $relative
  if (Test-Path $source) {
    $target = Join-Path $backup $relative
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item $source $target -Force
  }
}

Expand-Archive .\VELMONTAIRE_CORE_UPDATED.zip .\_velmontaire_update -Force
foreach ($relative in $changed) {
  Copy-Item (Join-Path ".\_velmontaire_update" $relative) (Join-Path "." $relative) -Force
}
Copy-Item .\_velmontaire_update\tests\velmontaire_full_strategy_contract_test.py .\tests\ -Force
Copy-Item .\_velmontaire_update\tests\synthetic_dxy_history_test.py .\tests\ -Force
Copy-Item .\_velmontaire_update\VELMONTAIRE_STRATEGY_READY.txt .\ -Force
```

## 2. Проверить активные файлы и контракт стратегии

```powershell
cd C:\TradingBot
$env:PYTHONPATH = "C:\TradingBot"

python -c "import inspect,generic_backtest.runner as r; s=inspect.getsource(r.ProductionGenericHistoricalRunner); print('FILE=',r.__file__); print({x:(x in s) for x in ['CLOSED_BARS_ONLY','daily_loss_blocks','rates_by_symbol','limit_first_tap_simulation','SYNTHETIC_DXY']})"

python .\tests\synthetic_dxy_history_test.py
python .\tests\velmontaire_full_strategy_contract_test.py
python .\tests\day43_multi_step_ai_parsing_pipeline_test.py
python .\tests\day51_strategy_compiler_foundation_test.py
python .\tests\day52_generic_strategy_runtime_executor_test.py
python .\tests\day53_generic_trade_plan_resolution_test.py
```

Правильный путь в первой команде: `C:\TradingBot\generic_backtest\runner.py`.
Все пять feature-флагов должны быть `True`. Контрактный тест должен вывести:

```text
VELMONTAIRE full strategy parser/compiler contract: OK
```

## 3. Проверить источник DXY

```powershell
python -c "import MetaTrader5 as mt5; ok=mt5.initialize(); print('MT5=',ok); info=mt5.symbol_info('DXY'); print('DXY=',None if info is None else info.name); print('CANDIDATES=',[s.name for s in (mt5.symbols_get() or []) if ('DXY' in s.name.upper() or 'USDX' in s.name.upper())][:30]); mt5.shutdown()"
```

Если `DXY=None`, не заменяйте его на похожий тикер: `DXYN` является акцией,
а `USDX` у проверенного брокера является ETF. Движок автоматически построит
на H4 синтетический направленный DXY из:

```text
EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF
```

Если настоящий `DXY` существует, движок использует его. Если нет истории хотя
бы одного из шести компонентов, бэктест завершится ошибкой, а не пропустит
подтверждение молча.

## 4. Создать новую версию стратегии

Запустите сервер:

```powershell
python -m webapp.server
```

Создайте новую стратегию/версию из полного текста
`VELMONTAIRE_STRATEGY_READY.txt`. Старую версию с фиксированным 3R не
используйте. В бэктесте выберите:

- Symbol: `EURUSD`
- Timeframe: `M15`
- Starting balance: `5000`
- Сначала даты: `2026-08-03` — `2026-08-09`
- Затем, после проверки сделок: `2026-08-03` — `2026-08-28`

В серверном логе до симуляции должны появиться строки:

```text
phase=CONTEXT_HISTORY_LOAD started symbol=DXY timeframe=H4
phase=SYNTHETIC_DXY_BUILD completed timeframe=H4
phase=CONTEXT_HISTORY_LOAD completed symbol=DXY timeframe=H4
phase=SIMULATION started symbol=EURUSD timeframe=M15
```

В готовом JSON проверьте:

- `execution_timeframe = M15`
- `context_symbol_scope` содержит `DXY` или брокерский эквивалент
- `context_symbol_sources.DXY.H4.source = SYNTHETIC_DXY` (если нет native DXY)
- `execution_policy.mtf_visibility = CLOSED_BARS_ONLY`
- `risk_policy.risk_percent = 1`
- `risk_policy.daily_loss_percent = 1`
- `risk_policy.weekly_loss_percent = 3`
- у прибыльных сделок `gross_r` находится в диапазоне `1.5 ... 2.0`
- одновременно открыта только одна позиция

## 5. Смотреть статус из F12

Подставьте ID из ответа `POST /api/backtests`:

```javascript
clearInterval(window.btWatch); window.btWatch=setInterval(()=>fetch('/api/backtests/backtest_ВАШ_ID').then(r=>r.json()).then(x=>console.log(new Date().toLocaleTimeString(),'STATUS:',x.status,x.status==='COMPLETED'?x.result.metrics:x.result)),3000)
```

Остановить наблюдение:

```javascript
clearInterval(window.btWatch)
```
