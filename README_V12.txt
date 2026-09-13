VELMONTAIRE V12 — ASSET UNIVERSE + MULTI-ASSET BACKTEST

WHAT CHANGED
- Backtest is no longer hardcoded to one symbol.
- Asset Universe discovers ALL Forex / Indices / Metals exposed by the current MT5 broker.
- Broker-native symbol names are preserved (EURUSD.a, USTEC.cash, etc.).
- Canonical names are shown beside them where mapping is known.
- Search, category filters, Select visible, Clear.
- User can select any number of assets.
- One immutable strategy version is pinned into a durable backtest job for every selected asset.
- Results show per-asset ranking + aggregate independent-test summary.
- Failed/unavailable symbols fail independently instead of destroying the whole batch.

IMPORTANT
The current V12 multi-asset mode is INDEPENDENT_MULTI_ASSET:
each symbol receives the configured starting balance independently.
This is the correct first mode for discovering which markets fit a strategy.
A true shared-balance portfolio simulation requires portfolio-level risk,
concurrency and correlation rules and is intentionally not faked here.

FUTURE PAPER/LIVE
The Asset Universe API is broker-native and reusable by PAPER/LIVE deployment.
Do not hardcode NAS100/US30 aliases into execution; use broker_symbol returned
by /api/assets/universe.

INSTALL
Copy all files into C:\TradingBot\ with replacement.
Restart:
  cd C:\TradingBot
  python -m webapp.server
Then Ctrl+F5.
