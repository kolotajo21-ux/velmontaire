VELMONTAIRE M1 SCALPING V8.1

What is included
----------------
- Separate M1 IFVG -> new M1 FVG -> future retest -> rejection/engulfing model.
- Loads M1 together with the required H1/M30/M15 context histories.
- NAS100 and GER40 symbols; M1 execution with H1/M30/M15 POI context.
- Hard new-entry window: 16:30-18:00 Europe/Kyiv.
- MARKET entries only; structural M1 rejection/retest fractal Stop Loss.
- Fixed Take Profit at exactly 1R.
- Risk 0.5% per trade, maximum 2 open positions, one completed entry per
  Europe/Kyiv day per symbol.

Install
-------
1. Stop the running Python server.
2. Extract this archive into a temporary folder.
3. Run INSTALL_VELMONTAIRE_M1_SCALPING_V8.ps1 from PowerShell.
4. Start the server again.
5. In the dashboard create a NEW strategy and paste the contents of
   VELMONTAIRE_M1_SCALPING_STRATEGY.txt. Do not replace an existing strategy.
6. Confirm the parser shows NAS100/GER40, M1, MARKET, 0.5% risk, RR 1.0 and
   the hard 16:30-18:00 Europe/Kyiv window, then persist and backtest.

Validation
----------
The installer runs the new causal contract test plus V7 regression tests.
The synthetic test confirms a valid bullish sweep, IFVG, new FVG, future
retest, direct rejection and structural stop. It does not fabricate NAS100 or
GER40 market performance; use broker history for the real backtest.

Safety
------
The installer creates a timestamped C:\TradingBot_backup_M1_SCALPING_V8_1_*
backup before copying files. Existing strategy records and immutable versions
are not edited. The old V7 strategy remains available separately.
