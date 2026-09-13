from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


def _serialize(value: Any) -> Any:
    """
    Преобразует dataclass, Enum, Path и вложенные структуры
    в JSON-совместимый формат.
    """

    if is_dataclass(value):
        return {
            key: _serialize(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): _serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _serialize(item)
            for item in value
        ]

    enum_value = getattr(value, "value", None)

    if enum_value is not None:
        return _serialize(enum_value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, float):
        if value == float("inf"):
            return "Infinity"

        if value == float("-inf"):
            return "-Infinity"

    return value


def _trade_to_dict(trade: Any) -> dict[str, Any]:
    if isinstance(trade, dict):
        return {
            key: _serialize(value)
            for key, value in trade.items()
        }

    if hasattr(trade, "to_dict"):
        return _serialize(trade.to_dict())

    if is_dataclass(trade):
        return _serialize(asdict(trade))

    result: dict[str, Any] = {}

    for field_name in (
        "direction",
        "order_type",
        "entry",
        "stop_loss",
        "take_profit",
        "initial_stop_loss",
        "initial_risk",
        "rr",
        "status",
        "outcome",
        "signal_time",
        "open_time",
        "close_time",
        "open_bar_index",
        "close_bar_index",
        "close_price",
        "result_r",
        "bars_waited",
        "bars_in_trade",
        "break_even_armed",
        "break_even_moved",
        "reason",
    ):
        if hasattr(trade, field_name):
            result[field_name] = _serialize(
                getattr(trade, field_name)
            )

    return result


class BacktestReport:
    """
    Генератор отчётов бэктеста.

    Создаёт:
    - summary.json
    - trades.csv
    - equity.csv
    - report.txt
    """

    def __init__(
        self,
        output_dir: str | Path = "reports",
    ) -> None:
        self.output_dir = Path(output_dir)

    def _create_run_directory(
        self,
        run_name: Optional[str] = None,
    ) -> Path:
        if not run_name:
            run_name = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

        run_directory = self.output_dir / run_name
        run_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        return run_directory

    @staticmethod
    def _statistics_to_dict(
        statistics: Any,
    ) -> dict[str, Any]:
        if isinstance(statistics, dict):
            return _serialize(statistics)

        if hasattr(statistics, "to_dict"):
            return _serialize(
                statistics.to_dict()
            )

        if is_dataclass(statistics):
            return _serialize(
                asdict(statistics)
            )

        raise TypeError(
            "statistics должен быть dict "
            "или dataclass с методом to_dict()"
        )

    @staticmethod
    def _equity_to_dict(
        equity: Any,
    ) -> dict[str, Any]:
        if isinstance(equity, dict):
            return _serialize(equity)

        if hasattr(equity, "to_dict"):
            return _serialize(
                equity.to_dict()
            )

        if is_dataclass(equity):
            return _serialize(
                asdict(equity)
            )

        raise TypeError(
            "equity должен быть dict "
            "или dataclass с методом to_dict()"
        )

    def save_summary_json(
        self,
        run_directory: Path,
        statistics: Any,
        equity: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        summary_path = run_directory / "summary.json"

        payload = {
            "generated_at": datetime.now().isoformat(),
            "metadata": _serialize(metadata or {}),
            "statistics": self._statistics_to_dict(
                statistics
            ),
            "equity": self._equity_to_dict(
                equity
            ),
        }

        summary_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return summary_path

    def save_trades_csv(
        self,
        run_directory: Path,
        trades: Iterable[Any],
    ) -> Path:
        trades_path = run_directory / "trades.csv"

        trade_rows = [
            _trade_to_dict(trade)
            for trade in trades
        ]

        fieldnames = [
            "trade_number",
            "direction",
            "order_type",
            "entry",
            "stop_loss",
            "take_profit",
            "initial_stop_loss",
            "initial_risk",
            "rr",
            "status",
            "outcome",
            "signal_time",
            "open_time",
            "close_time",
            "open_bar_index",
            "close_bar_index",
            "close_price",
            "result_r",
            "bars_waited",
            "bars_in_trade",
            "break_even_armed",
            "break_even_moved",
            "reason",
        ]

        with trades_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )

            writer.writeheader()

            for trade_number, row in enumerate(
                trade_rows,
                start=1,
            ):
                output_row = {
                    field_name: row.get(
                        field_name,
                        "",
                    )
                    for field_name in fieldnames
                }

                output_row["trade_number"] = (
                    trade_number
                )

                writer.writerow(output_row)

        return trades_path

    def save_equity_csv(
        self,
        run_directory: Path,
        equity: Any,
    ) -> Path:
        equity_path = run_directory / "equity.csv"
        equity_dict = self._equity_to_dict(equity)
        points = equity_dict.get("points", [])

        fieldnames = [
            "trade_number",
            "result_r",
            "cumulative_r",
            "balance_before",
            "risk_money",
            "profit_money",
            "balance_after",
            "peak_balance",
            "drawdown_money",
            "drawdown_percent",
            "close_time",
        ]

        with equity_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )

            writer.writeheader()

            for point in points:
                writer.writerow(
                    {
                        field_name: point.get(
                            field_name,
                            "",
                        )
                        for field_name in fieldnames
                    }
                )

        return equity_path

    def save_text_report(
        self,
        run_directory: Path,
        statistics: Any,
        equity: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        report_path = run_directory / "report.txt"

        stats = self._statistics_to_dict(
            statistics
        )
        equity_data = self._equity_to_dict(
            equity
        )
        metadata_data = metadata or {}

        profit_factor = stats.get(
            "profit_factor",
            0.0,
        )

        payoff_ratio = stats.get(
            "payoff_ratio",
            0.0,
        )

        if profit_factor == "Infinity":
            profit_factor = "∞"

        if payoff_ratio == "Infinity":
            payoff_ratio = "∞"

        lines = [
            "========================================",
            "            BACKTEST REPORT",
            "========================================",
            "",
            f"Generated: {datetime.now().isoformat()}",
        ]

        if metadata_data:
            lines.extend(
                [
                    "",
                    "METADATA",
                    "----------------------------------------",
                ]
            )

            for key, value in metadata_data.items():
                lines.append(
                    f"{key}: {_serialize(value)}"
                )

        lines.extend(
            [
                "",
                "TRADES",
                "----------------------------------------",
                (
                    f"Total trades: "
                    f"{stats.get('total_trades', 0)}"
                ),
                (
                    f"Closed trades: "
                    f"{stats.get('closed_trades', 0)}"
                ),
                (
                    f"Open trades: "
                    f"{stats.get('open_trades', 0)}"
                ),
                (
                    f"Expired orders: "
                    f"{stats.get('expired_orders', 0)}"
                ),
                (
                    f"Not triggered: "
                    f"{stats.get('not_triggered_orders', 0)}"
                ),
                "",
                "RESULTS",
                "----------------------------------------",
                f"Wins: {stats.get('wins', 0)}",
                f"Losses: {stats.get('losses', 0)}",
                (
                    f"Break Even: "
                    f"{stats.get('break_even', 0)}"
                ),
                (
                    f"Win Rate: "
                    f"{stats.get('win_rate', 0):.2f}%"
                ),
                (
                    f"Loss Rate: "
                    f"{stats.get('loss_rate', 0):.2f}%"
                ),
                (
                    f"Break Even Rate: "
                    f"{stats.get('break_even_rate', 0):.2f}%"
                ),
                "",
                "R-METRICS",
                "----------------------------------------",
                (
                    f"Total R: "
                    f"{stats.get('total_r', 0):.2f}R"
                ),
                (
                    f"Average R: "
                    f"{stats.get('average_r', 0):.2f}R"
                ),
                (
                    f"Median R: "
                    f"{stats.get('median_r', 0):.2f}R"
                ),
                (
                    f"Average Win: "
                    f"{stats.get('average_win_r', 0):.2f}R"
                ),
                (
                    f"Average Loss: "
                    f"{stats.get('average_loss_r', 0):.2f}R"
                ),
                (
                    f"Best Trade: "
                    f"{stats.get('best_trade_r', 0):.2f}R"
                ),
                (
                    f"Worst Trade: "
                    f"{stats.get('worst_trade_r', 0):.2f}R"
                ),
                "",
                "QUALITY",
                "----------------------------------------",
                (
                    f"Profit Factor: "
                    f"{profit_factor}"
                ),
                (
                    f"Payoff Ratio: "
                    f"{payoff_ratio}"
                ),
                (
                    f"Expectancy: "
                    f"{stats.get('expectancy_r', 0):.2f}R"
                ),
                (
                    f"Sharpe Ratio: "
                    f"{stats.get('sharpe_ratio', 0):.2f}"
                ),
                (
                    f"Recovery Factor: "
                    f"{stats.get('recovery_factor', 0):.2f}"
                ),
                "",
                "DRAWDOWN",
                "----------------------------------------",
                (
                    f"Max Drawdown R: "
                    f"{equity_data.get('max_drawdown_r', 0):.2f}R"
                ),
                (
                    f"Max Drawdown Money: "
                    f"${equity_data.get('max_drawdown_money', 0):.2f}"
                ),
                (
                    f"Max Drawdown Percent: "
                    f"{equity_data.get('max_drawdown_percent', 0):.2f}%"
                ),
                "",
                "BALANCE",
                "----------------------------------------",
                (
                    f"Starting Balance: "
                    f"${equity_data.get('starting_balance', 0):.2f}"
                ),
                (
                    f"Final Balance: "
                    f"${equity_data.get('final_balance', 0):.2f}"
                ),
                (
                    f"Net Profit: "
                    f"${equity_data.get('net_profit', 0):.2f}"
                ),
                (
                    f"Return: "
                    f"{equity_data.get('return_percent', 0):.2f}%"
                ),
                "",
                "STREAKS",
                "----------------------------------------",
                (
                    f"Max consecutive wins: "
                    f"{stats.get('max_consecutive_wins', 0)}"
                ),
                (
                    f"Max consecutive losses: "
                    f"{stats.get('max_consecutive_losses', 0)}"
                ),
                "",
                "========================================",
            ]
        )

        report_path.write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

        return report_path

    def generate(
        self,
        trades: Iterable[Any],
        statistics: Any,
        equity: Any,
        metadata: Optional[dict[str, Any]] = None,
        run_name: Optional[str] = None,
    ) -> dict[str, Path]:
        """
        Создаёт полный комплект файлов отчёта.
        """

        trade_list = list(trades)

        run_directory = self._create_run_directory(
            run_name=run_name,
        )

        summary_path = self.save_summary_json(
            run_directory=run_directory,
            statistics=statistics,
            equity=equity,
            metadata=metadata,
        )

        trades_path = self.save_trades_csv(
            run_directory=run_directory,
            trades=trade_list,
        )

        equity_path = self.save_equity_csv(
            run_directory=run_directory,
            equity=equity,
        )

        report_path = self.save_text_report(
            run_directory=run_directory,
            statistics=statistics,
            equity=equity,
            metadata=metadata,
        )

        return {
            "run_directory": run_directory,
            "summary_json": summary_path,
            "trades_csv": trades_path,
            "equity_csv": equity_path,
            "text_report": report_path,
        }
