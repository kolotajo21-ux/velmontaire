import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent / "data"
DATABASE_PATH = DATA_DIR / "trades.db"


def connect_database() -> sqlite3.Connection:
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_PATH
    )
    connection.row_factory = sqlite3.Row

    return connection


def _get_existing_columns(
    connection: sqlite3.Connection,
) -> set[str]:
    rows = connection.execute(
        "PRAGMA table_info(trades)"
    ).fetchall()

    return {
        str(row["name"])
        for row in rows
    }


def _add_missing_columns(
    connection: sqlite3.Connection,
) -> None:
    existing_columns = _get_existing_columns(
        connection
    )

    new_columns = {
        "signal_time": "TEXT",
        "quality_score": "REAL",
        "impulse_ratio": "REAL",
        "ob_age": "INTEGER",
        "bos": "INTEGER",
        "fvg": "INTEGER",
        "fresh": "INTEGER",
        "mitigated": "INTEGER",
        "mitigation_count": "INTEGER",
        "atr": "REAL",
        "atr_ratio": "REAL",
        "d1_trend": "TEXT",
        "h4_trend": "TEXT",
        "distance_to_daily_block": "REAL",
        "ob_high": "REAL",
        "ob_low": "REAL",
        "ob_midpoint": "REAL",
        "ob_range": "REAL",
        "broken_level": "REAL",
    }

    for column_name, column_type in new_columns.items():
        if column_name in existing_columns:
            continue

        connection.execute(
            f"""
            ALTER TABLE trades
            ADD COLUMN {column_name} {column_type}
            """
        )


def initialize_database() -> None:
    with connect_database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                created_at TEXT NOT NULL,
                signal_time TEXT,

                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                order_type TEXT NOT NULL,

                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,

                lot REAL NOT NULL,
                risk_percent REAL NOT NULL,
                risk_money REAL NOT NULL,
                rr REAL NOT NULL,

                status TEXT NOT NULL,
                ticket INTEGER,

                open_time TEXT,
                close_time TEXT,
                close_price REAL,

                profit REAL,
                result_r REAL,

                quality_score REAL,
                impulse_ratio REAL,
                ob_age INTEGER,

                bos INTEGER,
                fvg INTEGER,
                fresh INTEGER,
                mitigated INTEGER,
                mitigation_count INTEGER,

                atr REAL,
                atr_ratio REAL,

                d1_trend TEXT,
                h4_trend TEXT,
                distance_to_daily_block REAL,

                ob_high REAL,
                ob_low REAL,
                ob_midpoint REAL,
                ob_range REAL,
                broken_level REAL,

                comment TEXT
            )
            """
        )

        _add_missing_columns(
            connection
        )


def _bool_to_database(
    value: bool | int | None,
) -> int | None:
    if value is None:
        return None

    return int(bool(value))


def _safe_float(
    value: Any,
) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(
    value: Any,
) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def add_trade(
    symbol: str,
    direction: str,
    order_type: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    lot: float,
    risk_percent: float,
    risk_money: float,
    rr: float,
    status: str = "SIGNAL",
    ticket: int | None = None,
    comment: str = "",

    signal_time: str | None = None,

    quality_score: float | None = None,
    impulse_ratio: float | None = None,
    ob_age: int | None = None,

    bos: bool | int | None = None,
    fvg: bool | int | None = None,
    fresh: bool | int | None = None,
    mitigated: bool | int | None = None,
    mitigation_count: int | None = None,

    atr: float | None = None,
    atr_ratio: float | None = None,

    d1_trend: str | None = None,
    h4_trend: str | None = None,
    distance_to_daily_block: float | None = None,

    ob_high: float | None = None,
    ob_low: float | None = None,
    ob_midpoint: float | None = None,
    ob_range: float | None = None,
    broken_level: float | None = None,
) -> int:
    initialize_database()

    created_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    with connect_database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO trades (
                created_at,
                signal_time,

                symbol,
                direction,
                order_type,

                entry,
                stop_loss,
                take_profit,

                lot,
                risk_percent,
                risk_money,
                rr,

                status,
                ticket,

                quality_score,
                impulse_ratio,
                ob_age,

                bos,
                fvg,
                fresh,
                mitigated,
                mitigation_count,

                atr,
                atr_ratio,

                d1_trend,
                h4_trend,
                distance_to_daily_block,

                ob_high,
                ob_low,
                ob_midpoint,
                ob_range,
                broken_level,

                comment
            )
            VALUES (
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?
            )
            """,
            (
                created_at,
                signal_time,

                symbol,
                direction,
                order_type,

                float(entry),
                float(stop_loss),
                float(take_profit),

                float(lot),
                float(risk_percent),
                float(risk_money),
                float(rr),

                status,
                ticket,

                _safe_float(
                    quality_score
                ),
                _safe_float(
                    impulse_ratio
                ),
                _safe_int(
                    ob_age
                ),

                _bool_to_database(
                    bos
                ),
                _bool_to_database(
                    fvg
                ),
                _bool_to_database(
                    fresh
                ),
                _bool_to_database(
                    mitigated
                ),
                _safe_int(
                    mitigation_count
                ),

                _safe_float(
                    atr
                ),
                _safe_float(
                    atr_ratio
                ),

                d1_trend,
                h4_trend,
                _safe_float(
                    distance_to_daily_block
                ),

                _safe_float(
                    ob_high
                ),
                _safe_float(
                    ob_low
                ),
                _safe_float(
                    ob_midpoint
                ),
                _safe_float(
                    ob_range
                ),
                _safe_float(
                    broken_level
                ),

                comment,
            ),
        )

        return int(
            cursor.lastrowid
        )


def update_trade_status(
    trade_id: int,
    status: str,
    **fields: Any,
) -> None:
    allowed_fields = {
        "ticket",
        "signal_time",
        "open_time",
        "close_time",
        "close_price",
        "profit",
        "result_r",
        "comment",
        "quality_score",
        "impulse_ratio",
        "ob_age",
        "bos",
        "fvg",
        "fresh",
        "mitigated",
        "mitigation_count",
        "atr",
        "atr_ratio",
        "d1_trend",
        "h4_trend",
        "distance_to_daily_block",
        "ob_high",
        "ob_low",
        "ob_midpoint",
        "ob_range",
        "broken_level",
    }

    boolean_fields = {
        "bos",
        "fvg",
        "fresh",
        "mitigated",
    }

    updates = [
        "status = ?"
    ]

    values: list[Any] = [
        status
    ]

    for field, value in fields.items():
        if field not in allowed_fields:
            raise ValueError(
                f"Недопустимое поле: {field}"
            )

        if field in boolean_fields:
            value = _bool_to_database(
                value
            )

        updates.append(
            f"{field} = ?"
        )
        values.append(
            value
        )

    values.append(
        int(trade_id)
    )

    query = (
        f"UPDATE trades "
        f"SET {', '.join(updates)} "
        f"WHERE id = ?"
    )

    with connect_database() as connection:
        connection.execute(
            query,
            values,
        )


def get_all_trades() -> list[dict[str, Any]]:
    initialize_database()

    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM trades
            ORDER BY id DESC
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_trade_by_id(
    trade_id: int,
) -> dict[str, Any] | None:
    initialize_database()

    with connect_database() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM trades
            WHERE id = ?
            """,
            (
                int(trade_id),
            ),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def get_statistics() -> dict[str, Any]:
    trades = get_all_trades()

    closed_trades = [
        trade
        for trade in trades
        if trade["status"] == "CLOSED"
    ]

    wins = [
        trade
        for trade in closed_trades
        if float(
            trade["result_r"] or 0
        ) > 0
    ]

    losses = [
        trade
        for trade in closed_trades
        if float(
            trade["result_r"] or 0
        ) < 0
    ]

    breakeven = [
        trade
        for trade in closed_trades
        if float(
            trade["result_r"] or 0
        ) == 0
    ]

    total_profit = sum(
        float(
            trade["profit"] or 0
        )
        for trade in closed_trades
    )

    total_r = sum(
        float(
            trade["result_r"] or 0
        )
        for trade in closed_trades
    )

    decided_trades = (
        len(wins)
        + len(losses)
    )

    win_rate = 0.0

    if decided_trades > 0:
        win_rate = (
            len(wins)
            / decided_trades
        ) * 100

    gross_profit = sum(
        float(
            trade["profit"] or 0
        )
        for trade in wins
    )

    gross_loss = abs(
        sum(
            float(
                trade["profit"] or 0
            )
            for trade in losses
        )
    )

    profit_factor = 0.0

    if gross_loss > 0:
        profit_factor = (
            gross_profit
            / gross_loss
        )
    elif gross_profit > 0:
        profit_factor = float(
            "inf"
        )

    return {
        "total_trades": len(trades),
        "closed_trades": len(
            closed_trades
        ),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(
            breakeven
        ),
        "win_rate": round(
            win_rate,
            2,
        ),
        "total_profit": round(
            total_profit,
            2,
        ),
        "total_r": round(
            total_r,
            2,
        ),
        "profit_factor": (
            round(
                profit_factor,
                2,
            )
            if profit_factor
            != float("inf")
            else float("inf")
        ),
    }


def _average_field(
    trades: list[dict[str, Any]],
    field: str,
) -> float | None:
    values: list[float] = []

    for trade in trades:
        value = trade.get(
            field
        )

        if value is None:
            continue

        try:
            values.append(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    if not values:
        return None

    return round(
        sum(values)
        / len(values),
        4,
    )


def _percentage_true(
    trades: list[dict[str, Any]],
    field: str,
) -> float | None:
    values = [
        trade.get(field)
        for trade in trades
        if trade.get(field)
        is not None
    ]

    if not values:
        return None

    true_count = sum(
        1
        for value in values
        if bool(value)
    )

    return round(
        true_count
        / len(values)
        * 100,
        2,
    )


def get_feature_analysis() -> dict[str, Any]:
    trades = get_all_trades()

    closed_trades = [
        trade
        for trade in trades
        if trade["status"] == "CLOSED"
    ]

    wins = [
        trade
        for trade in closed_trades
        if float(
            trade["result_r"] or 0
        ) > 0
    ]

    losses = [
        trade
        for trade in closed_trades
        if float(
            trade["result_r"] or 0
        ) < 0
    ]

    numeric_fields = [
        "quality_score",
        "impulse_ratio",
        "ob_age",
        "atr",
        "atr_ratio",
        "distance_to_daily_block",
        "ob_range",
        "mitigation_count",
    ]

    boolean_fields = [
        "bos",
        "fvg",
        "fresh",
        "mitigated",
    ]

    analysis: dict[str, Any] = {
        "wins_count": len(wins),
        "losses_count": len(losses),
        "wins": {},
        "losses": {},
    }

    for field in numeric_fields:
        analysis["wins"][field] = (
            _average_field(
                wins,
                field,
            )
        )

        analysis["losses"][field] = (
            _average_field(
                losses,
                field,
            )
        )

    for field in boolean_fields:
        analysis["wins"][
            f"{field}_percent"
        ] = _percentage_true(
            wins,
            field,
        )

        analysis["losses"][
            f"{field}_percent"
        ] = _percentage_true(
            losses,
            field,
        )

    return analysis


def print_feature_analysis() -> None:
    analysis = get_feature_analysis()

    print()
    print("=" * 72)
    print(
        "АНАЛИЗ ПОБЕДИТЕЛЕЙ И ПРОИГРАВШИХ"
    )
    print("=" * 72)

    print(
        f"Побед: "
        f"{analysis['wins_count']}"
    )

    print(
        f"Убытков: "
        f"{analysis['losses_count']}"
    )

    fields = [
        "quality_score",
        "impulse_ratio",
        "ob_age",
        "atr",
        "atr_ratio",
        "distance_to_daily_block",
        "ob_range",
        "mitigation_count",
        "bos_percent",
        "fvg_percent",
        "fresh_percent",
        "mitigated_percent",
    ]

    print()

    print(
        f"{'ПРИЗНАК':<30}"
        f"{'ПОБЕДЫ':>18}"
        f"{'УБЫТКИ':>18}"
    )

    print("-" * 66)

    for field in fields:
        win_value = analysis[
            "wins"
        ].get(field)

        loss_value = analysis[
            "losses"
        ].get(field)

        win_text = (
            "нет данных"
            if win_value is None
            else str(win_value)
        )

        loss_text = (
            "нет данных"
            if loss_value is None
            else str(loss_value)
        )

        print(
            f"{field:<30}"
            f"{win_text:>18}"
            f"{loss_text:>18}"
        )

    print("=" * 72)


initialize_database()