from __future__ import annotations
from prop_rules.risk_models import PropAccountSnapshot, PropRiskDecision

class PropRiskComplianceEngine:
    def evaluate(self, *, rules: dict, snapshot: PropAccountSnapshot, action: str,
                 requested_risk_amount: float = 0.0, is_weekend: bool = False) -> PropRiskDecision:
        action=str(action).strip().upper()
        if action not in {"OPEN","HOLD","CLOSE","PENDING_TRIGGER"}:
            return PropRiskDecision(False,action,"risk_action_unknown","UNRESOLVED")
        if snapshot.starting_balance <= 0:
            return PropRiskDecision(False,action,"starting_balance_invalid","UNRESOLVED")

        diag={}
        # Daily loss. Fail closed if percentage exists but calculation basis is absent.
        if "daily_loss_percent" in rules:
            pct=self._pct(rules.get("daily_loss_percent"))
            basis=str(rules.get("daily_loss_basis","STARTING_BALANCE")).upper()
            if basis=="STARTING_BALANCE": ref=snapshot.starting_balance
            elif basis=="DAY_START_BALANCE": ref=snapshot.day_start_balance
            elif basis=="DAY_START_EQUITY": ref=snapshot.day_start_equity
            elif basis=="DAY_START_HIGHER_BALANCE_EQUITY": ref=max(snapshot.day_start_balance,snapshot.day_start_equity)
            else:return PropRiskDecision(False,action,"daily_loss_basis_unresolved","UNRESOLVED",diag)
            floor=ref*(1-pct/100);diag["daily_loss_floor"]=floor
            if snapshot.equity <= floor:return PropRiskDecision(False,action,"daily_loss_limit_breached",diagnostics=diag)
            if action in {"OPEN","PENDING_TRIGGER"} and snapshot.equity-requested_risk_amount <= floor:
                return PropRiskDecision(False,action,"requested_risk_can_breach_daily_loss",diagnostics=diag)

        # Overall loss: STATIC or TRAILING, with explicit balance/equity high-water basis.
        if "max_loss_percent" in rules:
            pct=self._pct(rules.get("max_loss_percent"))
            model=str(rules.get("max_loss_type","STATIC")).upper()
            if model=="STATIC":
                floor=snapshot.starting_balance*(1-pct/100)
            elif model=="TRAILING":
                trail_basis=str(rules.get("trailing_basis","")).upper()
                if trail_basis=="BALANCE": high=snapshot.high_water_balance
                elif trail_basis=="EQUITY": high=snapshot.high_water_equity
                else:return PropRiskDecision(False,action,"trailing_basis_unresolved","UNRESOLVED",diag)
                floor=high-snapshot.starting_balance*(pct/100)
                if rules.get("trailing_floor_cap_at_start") is True:floor=min(floor,snapshot.starting_balance)
            else:return PropRiskDecision(False,action,"max_loss_type_unresolved","UNRESOLVED",diag)
            diag["max_loss_floor"]=floor
            if snapshot.equity <= floor:return PropRiskDecision(False,action,"maximum_loss_limit_breached",diagnostics=diag)
            if action in {"OPEN","PENDING_TRIGGER"} and snapshot.equity-requested_risk_amount <= floor:
                return PropRiskDecision(False,action,"requested_risk_can_breach_maximum_loss",diagnostics=diag)

        max_open=rules.get("max_open_positions")
        if max_open is not None and action in {"OPEN","PENDING_TRIGGER"} and snapshot.open_positions >= int(max_open):
            return PropRiskDecision(False,action,"max_open_positions_reached",diagnostics=diag)

        max_open_risk_pct=rules.get("max_open_risk_percent")
        if max_open_risk_pct is not None and action in {"OPEN","PENDING_TRIGGER"}:
            cap=snapshot.starting_balance*self._pct(max_open_risk_pct)/100
            diag["max_open_risk_amount"]=cap
            if snapshot.open_risk_amount+requested_risk_amount > cap:
                return PropRiskDecision(False,action,"max_open_risk_exceeded",diagnostics=diag)

        if is_weekend and action=="HOLD":
            weekend=rules.get("weekend_holding")
            if weekend is False:return PropRiskDecision(False,action,"weekend_holding_blocked",diagnostics=diag)
            if weekend is None:return PropRiskDecision(False,action,"weekend_policy_unresolved","UNRESOLVED",diag)

        inactivity=rules.get("max_inactive_days")
        if inactivity is not None and snapshot.inactive_days >= int(inactivity):
            return PropRiskDecision(False,action,"inactivity_limit_reached",diagnostics=diag)

        # Consistency = best day / total profit <= configured percent.
        consistency=rules.get("consistency_max_best_day_percent")
        if consistency is not None and snapshot.total_profit > 0:
            ratio=snapshot.best_day_profit/snapshot.total_profit*100
            diag["best_day_profit_percent"]=ratio
            if ratio > self._pct(consistency):
                return PropRiskDecision(False,action,"consistency_rule_not_satisfied",diagnostics=diag)

        min_days=rules.get("minimum_trading_days")
        if action=="CLOSE" and rules.get("require_min_days_before_completion") is True and min_days is not None:
            if snapshot.trading_days < int(min_days):
                return PropRiskDecision(False,action,"minimum_trading_days_not_met",diagnostics=diag)

        return PropRiskDecision(True,action,"prop_risk_compliant",diagnostics=diag)

    @staticmethod
    def _pct(v):
        try:v=float(v)
        except (TypeError,ValueError):raise ValueError("invalid_prop_percentage")
        if v < 0 or v > 100:raise ValueError("invalid_prop_percentage")
        return v
