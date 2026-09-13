from __future__ import annotations

import py_compile
import shutil
from pathlib import Path

PROJECT_DIR = Path(r"C:\TradingBot")
CANDIDATES = [
    PROJECT_DIR / "backtester_day6_diagnostics.py",
    PROJECT_DIR / "backtester_multi_period.py",
    PROJECT_DIR / "backtester.py",
]

OLD_LINE = "PENDING_EXPIRY_BARS = 288"
NEW_LINE = "PENDING_EXPIRY_BARS = 432"


def main() -> None:
    found = [path for path in CANDIDATES if path.exists()]

    if not found:
        raise FileNotFoundError(
            "Не найден файл бэктестера в C:\\TradingBot. "
            "Проверь названия: backtester_day6_diagnostics.py, "
            "backtester_multi_period.py или backtester.py."
        )

    changed = []

    for path in found:
        text = path.read_text(encoding="utf-8")

        if NEW_LINE in text:
            print(f"Уже изменён: {path.name}")
            continue

        if OLD_LINE not in text:
            print(f"Пропущен: {path.name} — строка со значением 288 не найдена")
            continue

        backup = path.with_suffix(path.suffix + ".bak_pending_24h")
        shutil.copy2(path, backup)

        updated = text.replace(OLD_LINE, NEW_LINE, 1)
        path.write_text(updated, encoding="utf-8")

        py_compile.compile(str(path), doraise=True)
        changed.append(path)

        print(f"Готово: {path.name}")
        print(f"  288 M5 баров (24 часа) -> 432 M5 бара (36 часов)")
        print(f"  Резервная копия: {backup.name}")

    if not changed:
        print("\nНи один файл не был изменён.")
        print("Открой активный файл бэктестера и вручную замени:")
        print("PENDING_EXPIRY_BARS = 288")
        print("на:")
        print("PENDING_EXPIRY_BARS = 432")
        return

    print("\nИзменение применено. Можно запускать новый полный бэктест.")


if __name__ == "__main__":
    main()
