from application.mt5_historical_data_source import MT5HistoricalDataSource
from concepts.fvg.detector import FVGDetector, FVGDetectorConfig
from core.detector import DetectorContext


source = MT5HistoricalDataSource(bars=5000)

for tf in ("H4", "H1"):
    loaded = source.load(
        symbol="EURUSD",
        timeframe=tf,
        date_from="2026-06-01",
        date_to="2026-08-26",
    )

    rates = loaded.rates

    detector = FVGDetector(
        FVGDetectorConfig(timeframe=tf)
    )

    result = detector.analyze(
        DetectorContext(
            symbol="EURUSD",
            rates_by_timeframe={tf: rates},
            current_time=int(rates.iloc[-1]["time"]),
        ),
        {},
    )

    data = dict(result.data or {})

    print()
    print("=" * 60)
    print("TIMEFRAME:", tf)
    print("=" * 60)
    print("CANDLES:", len(rates))
    print("SUCCESS:", result.success)
    print("ERROR:", result.error)
    print("EVENTS:", len(result.events or []))
    print("DIAGNOSTICS:", result.diagnostics)
    print("BEST_FVG:", data.get("best_fvg"))
    print("BEST_IFVG:", data.get("best_ifvg"))

    for key in (
        "bullish_fvgs",
        "bearish_fvgs",
        "bullish_ifvgs",
        "bearish_ifvgs",
    ):
        zones = data.get(key, [])

        print(
            key.upper() + ":",
            len(zones)
            if isinstance(zones, list)
            else "N/A",
        )