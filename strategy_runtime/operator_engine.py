from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

from strategy_schema import ComparisonOperator


class OperatorEvaluationError(ValueError):
    """Fail-closed operator evaluation error."""


@dataclass(frozen=True, slots=True)
class OperatorEvaluation:
    operator: ComparisonOperator
    passed: bool
    left: Any
    right: Any
    previous_left: Any = None
    previous_right: Any = None
    tolerance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator.value,
            "passed": bool(self.passed),
            "left": self.left,
            "right": self.right,
            "previous_left": self.previous_left,
            "previous_right": self.previous_right,
            "tolerance": float(self.tolerance),
        }


class UniversalOperatorEngine:
    """
    One deterministic gateway for strategy comparison operators.

    Stateful operators such as CROSS_* and BREAK_* require previous values.
    Missing previous state never gets guessed; evaluation fails closed.
    """

    _ALIASES: dict[str, ComparisonOperator] = {
        "==": ComparisonOperator.EQ,
        "=": ComparisonOperator.EQ,
        "EQ": ComparisonOperator.EQ,
        "EQUAL": ComparisonOperator.EQ,
        "EQUALS": ComparisonOperator.EQ,

        "!=": ComparisonOperator.NE,
        "<>": ComparisonOperator.NE,
        "NE": ComparisonOperator.NE,
        "NOT_EQUAL": ComparisonOperator.NE,

        ">": ComparisonOperator.GT,
        "GT": ComparisonOperator.GT,
        "ABOVE": ComparisonOperator.GT,

        ">=": ComparisonOperator.GTE,
        "GTE": ComparisonOperator.GTE,
        "AT_OR_ABOVE": ComparisonOperator.GTE,

        "<": ComparisonOperator.LT,
        "LT": ComparisonOperator.LT,
        "BELOW": ComparisonOperator.LT,

        "<=": ComparisonOperator.LTE,
        "LTE": ComparisonOperator.LTE,
        "AT_OR_BELOW": ComparisonOperator.LTE,

        "CROSS_ABOVE": ComparisonOperator.CROSS_ABOVE,
        "CROSSES_ABOVE": ComparisonOperator.CROSS_ABOVE,
        "CROSS_OVER": ComparisonOperator.CROSS_ABOVE,

        "CROSS_BELOW": ComparisonOperator.CROSS_BELOW,
        "CROSSES_BELOW": ComparisonOperator.CROSS_BELOW,
        "CROSS_UNDER": ComparisonOperator.CROSS_BELOW,

        "TOUCH": ComparisonOperator.TOUCH,
        "TOUCHES": ComparisonOperator.TOUCH,
        "TOUCHED": ComparisonOperator.TOUCH,

        "BREAK_ABOVE": ComparisonOperator.BREAK_ABOVE,
        "BREAKS_ABOVE": ComparisonOperator.BREAK_ABOVE,
        "BREAKOUT_ABOVE": ComparisonOperator.BREAK_ABOVE,

        "BREAK_BELOW": ComparisonOperator.BREAK_BELOW,
        "BREAKS_BELOW": ComparisonOperator.BREAK_BELOW,
        "BREAKOUT_BELOW": ComparisonOperator.BREAK_BELOW,

        "BETWEEN": ComparisonOperator.BETWEEN,
        "INSIDE": ComparisonOperator.INSIDE,
        "OUTSIDE": ComparisonOperator.OUTSIDE,
    }

    def normalize(self, operator: ComparisonOperator | str) -> ComparisonOperator:
        if isinstance(operator, ComparisonOperator):
            if operator == ComparisonOperator.TOUCHES:
                return ComparisonOperator.TOUCH
            return operator

        raw = str(operator or "").strip().upper().replace("-", "_").replace(" ", "_")
        resolved = self._ALIASES.get(raw)
        if resolved is None:
            try:
                resolved = ComparisonOperator(str(operator))
            except (ValueError, TypeError):
                raise OperatorEvaluationError(f"unsupported_operator:{operator}")
        if resolved == ComparisonOperator.TOUCHES:
            return ComparisonOperator.TOUCH
        return resolved

    def evaluate(
        self,
        operator: ComparisonOperator | str,
        left: Any,
        right: Any,
        *,
        previous_left: Any = None,
        previous_right: Any = None,
        tolerance: float = 0.0,
    ) -> OperatorEvaluation:
        op = self.normalize(operator)

        try:
            tol = float(tolerance)
        except (TypeError, ValueError) as exc:
            raise OperatorEvaluationError("invalid_operator_tolerance") from exc
        if tol < 0:
            raise OperatorEvaluationError("invalid_operator_tolerance")

        if op == ComparisonOperator.EQ:
            passed = self._equal(left, right, tol)
        elif op == ComparisonOperator.NE:
            passed = not self._equal(left, right, tol)
        elif op == ComparisonOperator.GT:
            passed = self._ordered(left, right, lambda a, b: a > b)
        elif op == ComparisonOperator.GTE:
            passed = self._ordered(left, right, lambda a, b: a >= b)
        elif op == ComparisonOperator.LT:
            passed = self._ordered(left, right, lambda a, b: a < b)
        elif op == ComparisonOperator.LTE:
            passed = self._ordered(left, right, lambda a, b: a <= b)
        elif op == ComparisonOperator.CROSS_ABOVE:
            self._require_previous(previous_left, previous_right, op)
            passed = (
                self._ordered(previous_left, previous_right, lambda a, b: a <= b)
                and self._ordered(left, right, lambda a, b: a > b)
            )
        elif op == ComparisonOperator.CROSS_BELOW:
            self._require_previous(previous_left, previous_right, op)
            passed = (
                self._ordered(previous_left, previous_right, lambda a, b: a >= b)
                and self._ordered(left, right, lambda a, b: a < b)
            )
        elif op == ComparisonOperator.BREAK_ABOVE:
            self._require_previous(previous_left, previous_right, op)
            # Break requires prior value not above the level and current value above it.
            passed = (
                self._ordered(previous_left, previous_right, lambda a, b: a <= b)
                and self._ordered(left, right, lambda a, b: a > b)
            )
        elif op == ComparisonOperator.BREAK_BELOW:
            self._require_previous(previous_left, previous_right, op)
            passed = (
                self._ordered(previous_left, previous_right, lambda a, b: a >= b)
                and self._ordered(left, right, lambda a, b: a < b)
            )
        elif op == ComparisonOperator.TOUCH:
            passed = self._touch(left, right, tol)
        elif op == ComparisonOperator.BETWEEN:
            low, high = self._range(right)
            passed = self._ordered(left, low, lambda a, b: a >= b) and self._ordered(
                left, high, lambda a, b: a <= b
            )
        elif op == ComparisonOperator.INSIDE:
            passed = self._inside(left, right)
        elif op == ComparisonOperator.OUTSIDE:
            passed = not self._inside(left, right)
        else:
            raise OperatorEvaluationError(f"unsupported_operator:{op.value}")

        return OperatorEvaluation(
            operator=op,
            passed=bool(passed),
            left=left,
            right=right,
            previous_left=previous_left,
            previous_right=previous_right,
            tolerance=tol,
        )

    @staticmethod
    def _require_previous(previous_left: Any, previous_right: Any, op: ComparisonOperator) -> None:
        if previous_left is None or previous_right is None:
            raise OperatorEvaluationError(f"previous_values_required:{op.value}")

    @staticmethod
    def _ordered(left: Any, right: Any, fn) -> bool:
        try:
            return bool(fn(left, right))
        except (TypeError, ValueError) as exc:
            raise OperatorEvaluationError(
                f"incomparable_values:{type(left).__name__}:{type(right).__name__}"
            ) from exc

    @staticmethod
    def _equal(left: Any, right: Any, tolerance: float) -> bool:
        if (
            tolerance > 0
            and isinstance(left, Real)
            and isinstance(right, Real)
        ):
            return abs(float(left) - float(right)) <= tolerance
        return left == right

    @classmethod
    def _touch(cls, left: Any, right: Any, tolerance: float) -> bool:
        # Scalar touch: equality, optionally with tolerance.
        if not cls._is_range(left) and not cls._is_range(right):
            return cls._equal(left, right, tolerance)

        # Scalar touching a zone.
        if not cls._is_range(left) and cls._is_range(right):
            low, high = cls._range(right)
            return (
                cls._ordered(left, low - tolerance, lambda a, b: a >= b)
                and cls._ordered(left, high + tolerance, lambda a, b: a <= b)
            )

        # Range touching scalar.
        if cls._is_range(left) and not cls._is_range(right):
            low, high = cls._range(left)
            return (
                cls._ordered(right, low - tolerance, lambda a, b: a >= b)
                and cls._ordered(right, high + tolerance, lambda a, b: a <= b)
            )

        # Two ranges overlap/touch.
        l_low, l_high = cls._range(left)
        r_low, r_high = cls._range(right)
        return l_high + tolerance >= r_low and r_high + tolerance >= l_low

    @classmethod
    def _inside(cls, left: Any, right: Any) -> bool:
        r_low, r_high = cls._range(right)
        if cls._is_range(left):
            l_low, l_high = cls._range(left)
            return l_low >= r_low and l_high <= r_high
        return left >= r_low and left <= r_high

    @staticmethod
    def _is_range(value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) == 2
        ) or (
            isinstance(value, dict)
            and (
                {"low", "high"} <= set(value)
                or {"min", "max"} <= set(value)
            )
        )

    @classmethod
    def _range(cls, value: Any) -> tuple[Any, Any]:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            low, high = value
        elif isinstance(value, dict) and {"low", "high"} <= set(value):
            low, high = value["low"], value["high"]
        elif isinstance(value, dict) and {"min", "max"} <= set(value):
            low, high = value["min"], value["max"]
        else:
            raise OperatorEvaluationError("range_value_required")

        try:
            if low > high:
                low, high = high, low
        except (TypeError, ValueError) as exc:
            raise OperatorEvaluationError("invalid_range_values") from exc

        return low, high
