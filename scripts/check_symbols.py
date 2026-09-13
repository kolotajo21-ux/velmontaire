import MetaTrader5 as mt5

from config import MT5_PATH, MT5_TIMEOUT


if not mt5.initialize(
    path=MT5_PATH,
    timeout=MT5_TIMEOUT,
):
    print("Ошибка:", mt5.last_error())
    raise SystemExit


symbols = mt5.symbols_get()

if symbols is None:
    print("Ошибка:", mt5.last_error())
    mt5.shutdown()
    raise SystemExit


keywords = (
    "NAS",
    "USTEC",
    "US100",
    "NDX",
    "GER",
    "DE40",
    "DAX",
)


for symbol in symbols:
    name = symbol.name.upper()

    if any(keyword in name for keyword in keywords):
        print(symbol.name)


mt5.shutdown()