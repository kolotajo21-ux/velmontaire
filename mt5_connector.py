import MetaTrader5 as mt5

print("Подключение к MT5...")

connected = mt5.initialize(
    path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
    login=109545352,
    password="!4IaRbWy",
    server="MetaQuotes-Demo",
    timeout=120000
)

if not connected:
    print("❌ Не удалось подключиться")
    print("Ошибка:", mt5.last_error())
    mt5.shutdown()
    raise SystemExit

print("✅ Подключение успешно!")

account = mt5.account_info()

print("\n===== ИНФОРМАЦИЯ О СЧЕТЕ =====")
print(f"Логин: {account.login}")
print(f"Баланс: {account.balance}")
print(f"Средства: {account.equity}")
print(f"Сервер: {account.server}")
print("==============================")

mt5.shutdown()