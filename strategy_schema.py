from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from enum import Enum
from typing import Any


class StrategySide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class ComparisonOperator(str, Enum):
    EQ = "=="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    CROSS_ABOVE = "CROSS_ABOVE"
    CROSS_BELOW = "CROSS_BELOW"
    TOUCHES = "TOUCHES"
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"


class ConditionKind(str, Enum):
    COMPARISON = "COMPARISON"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    EVENT = "EVENT"
    SEQUENCE = "SEQUENCE"


class EntryOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class StopLossType(str, Enum):
    FIXED_PRICE = "FIXED_PRICE"
    FIXED_DISTANCE = "FIXED_DISTANCE"
    PERCENT = "PERCENT"
    ATR = "ATR"
    STRUCTURE = "STRUCTURE"
    CUSTOM = "CUSTOM"


class TakeProfitType(str, Enum):
    FIXED_PRICE = "FIXED_PRICE"
    FIXED_DISTANCE = "FIXED_DISTANCE"
    PERCENT = "PERCENT"
    R_MULTIPLE = "R_MULTIPLE"
    STRUCTURE = "STRUCTURE"
    CUSTOM = "CUSTOM"


class RiskSizingType(str, Enum):
    FIXED_LOT = "FIXED_LOT"
    FIXED_CASH = "FIXED_CASH"
    BALANCE_PERCENT = "BALANCE_PERCENT"
    EQUITY_PERCENT = "EQUITY_PERCENT"


class ManagementActionType(str, Enum):
    BREAK_EVEN = "BREAK_EVEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    TRAILING_STOP = "TRAILING_STOP"
    MOVE_STOP = "MOVE_STOP"
    CLOSE_POSITION = "CLOSE_POSITION"
    CUSTOM = "CUSTOM"


@dataclass(slots=True)
class ValidationIssue:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }




class ValueSourceType(str, Enum):
    """Canonical source families for universal strategy values."""
    PRICE = "PRICE"
    INDICATOR = "INDICATOR"
    CONSTANT = "CONSTANT"
    STRUCTURE = "STRUCTURE"
    LEVEL = "LEVEL"
    SESSION = "SESSION"
    TIME = "TIME"
    TRADE_STATE = "TRADE_STATE"
    ACCOUNT_STATE = "ACCOUNT_STATE"
    MODULE_OUTPUT = "MODULE_OUTPUT"
    CUSTOM = "CUSTOM"


@dataclass(slots=True)
class ValueReference:
    """
    Universal value descriptor.

    Backward compatible with the original Day 41 constructor:
        ValueReference(source="price", field="close", timeframe="M15")
        ValueReference(source="constant", constant=1.0)

    New code may additionally use canonical source families through
    source_type.  Existing serialized keys are preserved.
    """
    source: str
    field: str | None = None
    timeframe: str | None = None
    parameters: dict[str, Any] = dc_field(default_factory=dict)
    constant: Any = None
    source_type: ValueSourceType | str | None = None
    provider: str | None = None
    output: str | None = None
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source = str(self.source or "").strip()
        if not self.source:
            raise ValueError("value_reference_source_required")

        if self.timeframe is not None:
            self.timeframe = str(self.timeframe).strip().upper() or None

        if self.field is not None:
            self.field = str(self.field).strip() or None

        if self.provider is not None:
            self.provider = str(self.provider).strip() or None

        if self.output is not None:
            self.output = str(self.output).strip() or None

        if self.source_type is None:
            self.source_type = self._infer_source_type(self.source)
        elif not isinstance(self.source_type, ValueSourceType):
            raw = str(self.source_type).strip().upper()
            try:
                self.source_type = ValueSourceType(raw)
            except ValueError:
                self.source_type = ValueSourceType.CUSTOM

        if self.source_type == ValueSourceType.CONSTANT and self.constant is None:
            # None can be a legitimate Python value, but not an executable
            # strategy constant. Missing values must remain explicit.
            raise ValueError("constant_value_required")

        if self.source_type == ValueSourceType.MODULE_OUTPUT:
            if not self.provider:
                raise ValueError("module_output_provider_required")
            if not (self.output or self.field):
                raise ValueError("module_output_name_required")

    @staticmethod
    def _infer_source_type(source: str) -> ValueSourceType:
        key = str(source or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "price": ValueSourceType.PRICE,
            "ohlc": ValueSourceType.PRICE,
            "market_price": ValueSourceType.PRICE,
            "indicator": ValueSourceType.INDICATOR,
            "constant": ValueSourceType.CONSTANT,
            "const": ValueSourceType.CONSTANT,
            "structure": ValueSourceType.STRUCTURE,
            "market_structure": ValueSourceType.STRUCTURE,
            "level": ValueSourceType.LEVEL,
            "price_level": ValueSourceType.LEVEL,
            "session": ValueSourceType.SESSION,
            "time": ValueSourceType.TIME,
            "trade": ValueSourceType.TRADE_STATE,
            "trade_state": ValueSourceType.TRADE_STATE,
            "position": ValueSourceType.TRADE_STATE,
            "account": ValueSourceType.ACCOUNT_STATE,
            "account_state": ValueSourceType.ACCOUNT_STATE,
            "module": ValueSourceType.MODULE_OUTPUT,
            "module_output": ValueSourceType.MODULE_OUTPUT,
        }
        return aliases.get(key, ValueSourceType.CUSTOM)

    @property
    def canonical_source(self) -> str:
        return self.source_type.value

    def to_dict(self) -> dict[str, Any]:
        # Original keys remain unchanged for backward compatibility.
        return {
            "source": self.source,
            "field": self.field,
            "timeframe": self.timeframe,
            "parameters": dict(self.parameters),
            "constant": self.constant,
            "source_type": self.source_type.value,
            "provider": self.provider,
            "output": self.output,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StrategyCondition:
    condition_id: str
    kind: ConditionKind
    left: ValueReference | None = None
    operator: ComparisonOperator | None = None
    right: ValueReference | None = None
    logical_operator: LogicalOperator | None = None
    children: list["StrategyCondition"] = dc_field(default_factory=list)
    event_name: str | None = None
    sequence: list["StrategyCondition"] = dc_field(default_factory=list)
    max_bars_between_steps: int | None = None
    description: str | None = None
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "kind": self.kind.value,
            "left": self.left.to_dict() if self.left else None,
            "operator": self.operator.value if self.operator else None,
            "right": self.right.to_dict() if self.right else None,
            "logical_operator": (
                self.logical_operator.value if self.logical_operator else None
            ),
            "children": [child.to_dict() for child in self.children],
            "event_name": self.event_name,
            "sequence": [step.to_dict() for step in self.sequence],
            "max_bars_between_steps": self.max_bars_between_steps,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class EntryRule:
    side: StrategySide
    order_type: EntryOrderType
    conditions: StrategyCondition
    entry_price: ValueReference | None = None
    expiration_bars: int | None = None
    allow_multiple_entries: bool = False
    max_entries: int = 1
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "order_type": self.order_type.value,
            "conditions": self.conditions.to_dict(),
            "entry_price": self.entry_price.to_dict() if self.entry_price else None,
            "expiration_bars": self.expiration_bars,
            "allow_multiple_entries": self.allow_multiple_entries,
            "max_entries": self.max_entries,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StopLossRule:
    type: StopLossType
    value: float | None = None
    reference: ValueReference | None = None
    offset: float = 0.0
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "value": self.value,
            "reference": self.reference.to_dict() if self.reference else None,
            "offset": self.offset,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class TakeProfitRule:
    type: TakeProfitType
    value: float | None = None
    reference: ValueReference | None = None
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "value": self.value,
            "reference": self.reference.to_dict() if self.reference else None,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RiskRule:
    sizing_type: RiskSizingType
    value: float
    max_open_positions: int = 1
    max_positions_per_symbol: int = 1
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sizing_type": self.sizing_type.value,
            "value": self.value,
            "max_open_positions": self.max_open_positions,
            "max_positions_per_symbol": self.max_positions_per_symbol,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ManagementRule:
    action: ManagementActionType
    trigger: StrategyCondition
    parameters: dict[str, Any] = dc_field(default_factory=dict)
    priority: int = 100
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "trigger": self.trigger.to_dict(),
            "parameters": dict(self.parameters),
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StrategyRules:
    entries: list[EntryRule] = dc_field(default_factory=list)
    stop_loss: StopLossRule | None = None
    take_profit: TakeProfitRule | None = None
    risk: RiskRule | None = None
    management: list[ManagementRule] = dc_field(default_factory=list)
    invalidation: StrategyCondition | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "stop_loss": self.stop_loss.to_dict() if self.stop_loss else None,
            "take_profit": self.take_profit.to_dict() if self.take_profit else None,
            "risk": self.risk.to_dict() if self.risk else None,
            "management": [rule.to_dict() for rule in self.management],
            "invalidation": self.invalidation.to_dict() if self.invalidation else None,
        }


@dataclass(slots=True)
class StrategySchema:
    strategy_id: str
    name: str
    version: str
    symbols: list[str]
    timeframes: list[str]
    rules: StrategyRules
    description: str | None = None
    source_text: str | None = None
    parser_questions: list[str] = dc_field(default_factory=list)
    unresolved_fields: list[str] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)
    schema_version: str = "1.0"

    def validate(self) -> ValidationResult:
        issues: list[ValidationIssue] = []

        if not self.strategy_id.strip():
            issues.append(ValidationIssue("strategy_id", "REQUIRED", "strategy_id is required"))
        if not self.name.strip():
            issues.append(ValidationIssue("name", "REQUIRED", "name is required"))
        if not self.version.strip():
            issues.append(ValidationIssue("version", "REQUIRED", "version is required"))
        if not self.symbols:
            issues.append(ValidationIssue("symbols", "REQUIRED", "at least one symbol is required"))
        if not self.timeframes:
            issues.append(ValidationIssue("timeframes", "REQUIRED", "at least one timeframe is required"))
        if not self.rules.entries:
            issues.append(ValidationIssue("rules.entries", "REQUIRED", "at least one entry rule is required"))
        if self.rules.risk is None:
            issues.append(ValidationIssue("rules.risk", "REQUIRED", "risk rule is required"))

        for i, entry in enumerate(self.rules.entries):
            if entry.max_entries < 1:
                issues.append(ValidationIssue(
                    f"rules.entries[{i}].max_entries",
                    "INVALID_VALUE",
                    "max_entries must be >= 1",
                ))
            if entry.order_type in {EntryOrderType.LIMIT, EntryOrderType.STOP} and entry.entry_price is None:
                issues.append(ValidationIssue(
                    f"rules.entries[{i}].entry_price",
                    "REQUIRED",
                    "entry_price is required for LIMIT/STOP orders",
                ))
            self._validate_condition(
                entry.conditions,
                path=f"rules.entries[{i}].conditions",
                issues=issues,
            )

        if self.rules.invalidation is not None:
            self._validate_condition(
                self.rules.invalidation,
                path="rules.invalidation",
                issues=issues,
            )

        for i, rule in enumerate(self.rules.management):
            self._validate_condition(
                rule.trigger,
                path=f"rules.management[{i}].trigger",
                issues=issues,
            )

        if self.rules.risk is not None:
            if self.rules.risk.value <= 0:
                issues.append(ValidationIssue(
                    "rules.risk.value",
                    "INVALID_VALUE",
                    "risk value must be > 0",
                ))
            if self.rules.risk.max_open_positions < 1:
                issues.append(ValidationIssue(
                    "rules.risk.max_open_positions",
                    "INVALID_VALUE",
                    "max_open_positions must be >= 1",
                ))

        for field_name in self.unresolved_fields:
            issues.append(ValidationIssue(
                field_name,
                "UNRESOLVED",
                "field requires clarification before strategy can run",
            ))

        return ValidationResult(valid=not issues, issues=issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "rules": self.rules.to_dict(),
            "description": self.description,
            "source_text": self.source_text,
            "parser_questions": list(self.parser_questions),
            "unresolved_fields": list(self.unresolved_fields),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def _validate_condition(
        cls,
        condition: StrategyCondition,
        *,
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        if not condition.condition_id.strip():
            issues.append(ValidationIssue(
                f"{path}.condition_id",
                "REQUIRED",
                "condition_id is required",
            ))

        if condition.kind == ConditionKind.COMPARISON:
            if condition.left is None:
                issues.append(ValidationIssue(f"{path}.left", "REQUIRED", "left value is required"))
            if condition.operator is None:
                issues.append(ValidationIssue(f"{path}.operator", "REQUIRED", "comparison operator is required"))
            if condition.right is None:
                issues.append(ValidationIssue(f"{path}.right", "REQUIRED", "right value is required"))

        elif condition.kind == ConditionKind.LOGICAL_GROUP:
            if condition.logical_operator is None:
                issues.append(ValidationIssue(
                    f"{path}.logical_operator",
                    "REQUIRED",
                    "logical_operator is required",
                ))
            if not condition.children:
                issues.append(ValidationIssue(
                    f"{path}.children",
                    "REQUIRED",
                    "logical group requires children",
                ))
            if condition.logical_operator == LogicalOperator.NOT and len(condition.children) != 1:
                issues.append(ValidationIssue(
                    f"{path}.children",
                    "INVALID_COUNT",
                    "NOT requires exactly one child",
                ))
            for i, child in enumerate(condition.children):
                cls._validate_condition(
                    child,
                    path=f"{path}.children[{i}]",
                    issues=issues,
                )

        elif condition.kind == ConditionKind.EVENT:
            if not (condition.event_name and condition.event_name.strip()):
                issues.append(ValidationIssue(
                    f"{path}.event_name",
                    "REQUIRED",
                    "event_name is required",
                ))

        elif condition.kind == ConditionKind.SEQUENCE:
            if not condition.sequence:
                issues.append(ValidationIssue(
                    f"{path}.sequence",
                    "REQUIRED",
                    "sequence requires at least one step",
                ))
            if condition.max_bars_between_steps is not None and condition.max_bars_between_steps < 1:
                issues.append(ValidationIssue(
                    f"{path}.max_bars_between_steps",
                    "INVALID_VALUE",
                    "max_bars_between_steps must be >= 1",
                ))
            for i, step in enumerate(condition.sequence):
                cls._validate_condition(
                    step,
                    path=f"{path}.sequence[{i}]",
                  
                )