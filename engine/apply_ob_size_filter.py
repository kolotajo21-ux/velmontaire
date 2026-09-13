from __future__ import annotations

from pathlib import Path
import shutil
import sys


TARGET_NAME = "strategy_engine.py"
RATIO = "0.60"


def find_target() -> Path:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1]).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Файл не найден: {path}")

    local = Path.cwd() / TARGET_NAME
    if local.is_file():
        return local.resolve()

    matches = list(Path.cwd().rglob(TARGET_NAME))
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise FileNotFoundError(
            f"Не найден {TARGET_NAME}. Положи этот скрипт в папку с файлом "
            "или перетащи strategy_engine.py на скрипт."
        )

    raise RuntimeError(
        "Найдено несколько strategy_engine.py. Запусти так:\n"
        'python apply_ob_size_filter.py "C:\\путь\\к\\strategy_engine.py"'
    )


def main() -> None:
    target = find_target()
    text = target.read_text(encoding="utf-8")

    if "MAX_OB_TO_IMPULSE_RATIO" in text:
        print("Фильтр уже установлен. Ничего не меняю.")
        print(target)
        return

    constant_anchor = "MAX_BARS_TO_BOS = 6"
    if constant_anchor not in text:
        raise RuntimeError(
            f"Не нашёл строку '{constant_anchor}'. Файл не изменён."
        )

    text = text.replace(
        constant_anchor,
        constant_anchor + f"\n        MAX_OB_TO_IMPULSE_RATIO = {RATIO}",
        1,
    )

    displacement_block = (
        '            if not displacement:\n'
        '                reject("displacement_too_weak")\n'
        '                continue\n'
    )

    insertion = displacement_block + (
        '\n'
        '            # Фильтр слишком широкого Order Block.\n'
        '            # Сравниваем полный диапазон OB с суммарным телом\n'
        '            # импульсных свечей от OB до BOS.\n'
        '            impulse_size = sum(impulse_bodies)\n'
        '\n'
        '            if impulse_size <= 0:\n'
        '                reject("invalid_impulse_size")\n'
        '                continue\n'
        '\n'
        '            ob_to_impulse_ratio = (\n'
        '                block_range / impulse_size\n'
        '            )\n'
        '\n'
        '            if (\n'
        '                ob_to_impulse_ratio\n'
        '                > MAX_OB_TO_IMPULSE_RATIO\n'
        '            ):\n'
        '                reject("order_block_too_wide")\n'
        '                continue\n'
    )

    if displacement_block not in text:
        displacement_block = (
            '            if not displacement:\n'
            '                continue\n'
        )
        insertion = displacement_block + (
            '\n'
            '            # Фильтр слишком широкого Order Block.\n'
            '            impulse_size = sum(impulse_bodies)\n'
            '\n'
            '            if impulse_size <= 0:\n'
            '                continue\n'
            '\n'
            '            ob_to_impulse_ratio = (\n'
            '                block_range / impulse_size\n'
            '            )\n'
            '\n'
            '            if (\n'
            '                ob_to_impulse_ratio\n'
            '                > MAX_OB_TO_IMPULSE_RATIO\n'
            '            ):\n'
            '                continue\n'
        )

    if displacement_block not in text:
        raise RuntimeError(
            "Не нашёл блок проверки displacement. Файл не изменён."
        )

    text = text.replace(displacement_block, insertion, 1)

    backup = target.with_suffix(target.suffix + ".before_ob_size_filter.bak")
    shutil.copy2(target, backup)
    target.write_text(text, encoding="utf-8")

    print("ГОТОВО: фильтр размера Order Block установлен.")
    print(f"Коэффициент: {RATIO}")
    print(f"Изменён файл: {target}")
    print(f"Резервная копия: {backup}")
    print("Теперь запускай квартальный бэктест.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ОШИБКА: {exc}")
        input("Нажми Enter для выхода...")
        raise
