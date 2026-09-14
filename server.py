from __future__ import annotations

import json
import os
import mimetypes
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from application.auth_service import AuthService
from application.mt5_historical_data_source import MT5HistoricalDataSource
from application.production_generic_backtest_gateway import (
    ProductionGenericBacktestGateway,
)

from backend.infrastructure.auth_store import AuthStore
from backend.infrastructure.database import Database
from backend.infrastructure.repositories import PersistenceRepository

from webapp.auth_api import WebAuthApplication, WebAuthResponse
from webapp.backtest_api import WebBacktestApplication
from webapp.strategy_api import WebStrategyApplication
from webapp.mt5_paper_api import WebMT5PaperApplication
from webapp.live_api import WebLiveMonitoringApplication, FailClosedLivePrerequisites
from webapp.failure_api import WebRuntimeFailureApplication
from webapp.billing_api import WebBillingApplication
from webapp.paddle_billing import PaddleSandbox
from webapp.prop_rules_api import WebPropRulesApplication
from webapp.news_compliance_api import WebNewsComplianceApplication
from webapp.prop_risk_api import WebPropRiskApplication
from webapp.prop_compliance_api import WebPropComplianceApplication
from webapp.markets_api import WebMarketsApplication
from webapp.futures_prop_api import WebFuturesPropApplication
from webapp.capability_requests_api import WebCapabilityRequestsApplication
from webapp.notifications_api import WebNotificationsApplication
from notifications.service import NotificationService
from capability_requests.service import CapabilityRequestService
from prop_rules.catalog import build_default_prop_registry
from backend.application.plan_entitlement_service import PlanEntitlementService
from backend.application.subscription_lifecycle_service import SubscriptionLifecycleService
from backend.application.runtime_resilience_service import RuntimeResilienceService
from backend.application.production_observability_service import ProductionObservabilityService
from backend.application.broker_connection_service import BrokerConnectionService, BrokerCredentialVault
from backend.application.execution_mode_guard import ExecutionModeGuard
from webapp.comparison_api import WebStrategyComparisonApplication
from webapp.public_live_pulse import PublicLivePulse


# ============================================================
# PATHS / CONFIG
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

FRONTEND_ROOT = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"

DATABASE_PATH = DATA_DIR / "velmontaire_saas.sqlite3"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))

COOKIE_NAME = "velmontaire_session"


# ============================================================
# STORAGE
# ============================================================

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# AUTH APPLICATION
# ============================================================

AUTH = WebAuthApplication(
    database_path=DATABASE_PATH
)


# ============================================================
# DATABASE / REPOSITORY
# ============================================================

_DB = Database(
    DATABASE_PATH
)

_DB.initialize()


_AUTH_STORE = AuthStore(
    _DB
)

_AUTH_STORE.initialize()


_REPOSITORY = PersistenceRepository(
    _DB
)


_AUTH_SERVICE = AuthService(
    repository=_REPOSITORY,
    auth_store=_AUTH_STORE,
)


# ============================================================
# STRATEGY APPLICATION
# ============================================================

STRATEGIES = WebStrategyApplication(
    repository=_REPOSITORY
)

COMPARISONS = WebStrategyComparisonApplication(_REPOSITORY)


# ============================================================
# STAGE 5 — PRODUCTION GENERIC BACKTEST CORE
# ============================================================

_HISTORY_SOURCE = MT5HistoricalDataSource(
    bars=5000
)


_PRODUCTION_BACKTEST_GATEWAY = (
    ProductionGenericBacktestGateway(
        repository=_REPOSITORY,
        history_source=_HISTORY_SOURCE,
        starting_balance=5000.0,
    )
)


BACKTESTS = WebBacktestApplication(
    _REPOSITORY,
    _PRODUCTION_BACKTEST_GATEWAY,
)

_STAGE8_API = getattr(BACKTESTS, "api", None)
_STAGE8_JOBS = getattr(_STAGE8_API, "jobs", None)
_STAGE8_CORE = getattr(_STAGE8_JOBS, "bot_core", None)

MT5_PAPER = (
    WebMT5PaperApplication(
        connections=BrokerConnectionService(
            vault=BrokerCredentialVault(
                (os.environ.get("VELMONTAIRE_CREDENTIAL_KEY") or
                 "VELMONTAIRE-DEVELOPMENT-ONLY-STAGE8-KEY").encode("utf-8")
            ),
            bot_core=_STAGE8_CORE,
        ),
        mode_guard=ExecutionModeGuard(),
        bot_core=_STAGE8_CORE,
    )
    if _STAGE8_CORE is not None
    else None
)



# Stage 9 shares Stage 8 broker/guard state. Server remains fail-closed unless the composed core exposes runtime control/status.
_STAGE9_CORE = _STAGE8_CORE
_STAGE9_RUNTIME_CAPABLE = bool(_STAGE9_CORE is not None and callable(getattr(_STAGE9_CORE, "control_bot", None)) and callable(getattr(_STAGE9_CORE, "runtime_status", None)))
LIVE_APP = (WebLiveMonitoringApplication(connections=MT5_PAPER.connections,mode_guard=MT5_PAPER.mode_guard,bot_core=_STAGE9_CORE,prerequisites=FailClosedLivePrerequisites(),observability=ProductionObservabilityService()) if MT5_PAPER is not None and _STAGE9_RUNTIME_CAPABLE else None)

# Stage 10 fail-closed resilience composition.
_STAGE10_RESILIENCE_CAPABLE = bool(
    _STAGE9_CORE is not None
    and all(
        callable(getattr(_STAGE9_CORE, name, None))
        for name in (
            "block_new_entries",
            "unblock_new_entries",
            "reconcile_runtime_state",
            "recover_after_restart",
        )
    )
)

RESILIENCE_APP = (
    WebRuntimeFailureApplication(
        resilience=RuntimeResilienceService(bot_core=_STAGE9_CORE),
        bot_core=_STAGE9_CORE,
        observability=ProductionObservabilityService(),
    )
    if _STAGE10_RESILIENCE_CAPABLE
    else None
)

PUBLIC_LIVE_PULSE = PublicLivePulse()

class _Stage11UsageProvider:
    def usage_for(self, *, user_id):
        return {"strategies":0,"backtests_this_month":0,"broker_connections":0,"active_bots":0}

_STAGE11_SUBSCRIPTIONS=SubscriptionLifecycleService()
_STAGE11_USAGE=_Stage11UsageProvider()
PADDLE_SANDBOX=PaddleSandbox(DATA_DIR)
BILLING=WebBillingApplication(subscription_service=_STAGE11_SUBSCRIPTIONS,usage_provider=_STAGE11_USAGE,plans=PlanEntitlementService(),paddle=PADDLE_SANDBOX)

PROP_RULES = WebPropRulesApplication(build_default_prop_registry())
NEWS_COMPLIANCE = WebNewsComplianceApplication(prop_rules_app=PROP_RULES)
PROP_RISK = WebPropRiskApplication(prop_rules_app=PROP_RULES)
PROP_COMPLIANCE = WebPropComplianceApplication(prop_rules_app=PROP_RULES)
MARKETS = WebMarketsApplication()
FUTURES_PROP = WebFuturesPropApplication()
CAPABILITY_REQUESTS = WebCapabilityRequestsApplication(CapabilityRequestService())
NOTIFICATION_SERVICE = NotificationService()
NOTIFICATIONS = WebNotificationsApplication(NOTIFICATION_SERVICE)


# ============================================================
# DASHBOARD DAILY STATISTICS
# ============================================================

def _stat_number(payload, keys):
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for value in payload.values():
        if isinstance(value, dict):
            found = _stat_number(value, keys)
            if found is not None:
                return found
    return None


def _dashboard_statistics(user_id: str, days: int) -> dict:
    days = max(1, min(int(days), 365))
    now = datetime.now(timezone.utc)
    start_day = now.date() - timedelta(days=days - 1)
    start_iso = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc).isoformat()

    with _DB.connect() as conn:
        rows = conn.execute(
            """
            SELECT event_type, payload_json, created_at
            FROM execution_logs
            WHERE user_id=? AND created_at>=?
            ORDER BY created_at
            """,
            (user_id, start_iso),
        ).fetchall()

    by_day = {}
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        by_day[day.isoformat()] = {
            "date": day.isoformat(), "trades": 0, "wins": 0, "losses": 0,
            "net_pnl": 0.0, "net_r": 0.0, "max_drawdown": 0.0,
        }

    all_pnls = []
    latest_equity = latest_balance = latest_open_risk = None
    running = peak = overall_max_dd = 0.0
    pnl_keys = ("pnl_money", "net_pnl", "pnl", "profit_money", "profit")
    r_keys = ("result_r", "net_r", "r_multiple", "r")
    equity_keys = ("equity", "account_equity")
    balance_keys = ("balance", "account_balance")
    risk_keys = ("open_risk_percent", "total_open_risk_percent", "risk_percent")

    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        eq = _stat_number(payload, equity_keys)
        bal = _stat_number(payload, balance_keys)
        risk = _stat_number(payload, risk_keys)
        if eq is not None: latest_equity = eq
        if bal is not None: latest_balance = bal
        if risk is not None: latest_open_risk = risk

        pnl = _stat_number(payload, pnl_keys)
        if pnl is None:
            continue
        event_type = str(row["event_type"] or "").upper()
        if any(t in event_type for t in ("INTENT", "SUBMIT", "PENDING", "OPENED")) and not any(
            t in event_type for t in ("CLOSE", "CLOSED", "EXIT", "RESULT", "SETTLED")
        ):
            continue
        day_key = str(row["created_at"] or "")[:10]
        if day_key not in by_day:
            continue
        result_r = _stat_number(payload, r_keys) or 0.0
        item = by_day[day_key]
        item["trades"] += 1
        item["wins"] += int(pnl > 0)
        item["losses"] += int(pnl < 0)
        item["net_pnl"] += pnl
        item["net_r"] += result_r
        running += pnl
        peak = max(peak, running)
        dd = peak - running
        overall_max_dd = max(overall_max_dd, dd)
        item["max_drawdown"] = max(item["max_drawdown"], dd)
        all_pnls.append(pnl)

    daily = []
    for item in by_day.values():
        for key in ("net_pnl", "net_r", "max_drawdown"):
            item[key] = round(item[key], 2)
        daily.append(item)

    trades = len(all_pnls)
    wins = sum(1 for p in all_pnls if p > 0)
    losses = sum(1 for p in all_pnls if p < 0)
    gross_profit = sum(p for p in all_pnls if p > 0)
    gross_loss = abs(sum(p for p in all_pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (None if gross_profit > 0 else 0.0)
    today = by_day[now.date().isoformat()]
    recent_activity = []
    for row in reversed(rows[-12:]):
        event_type = str(row["event_type"] or "")
        if not event_type:
            continue
        try:
            event_payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            event_payload = {}
        detail = (
            event_payload.get("symbol")
            or event_payload.get("strategy_id")
            or event_payload.get("bot_id")
            or event_payload.get("reason")
            or ""
        )
        recent_activity.append({
            "event_type": event_type,
            "created_at": row["created_at"],
            "detail": str(detail)[:120],
        })
        if len(recent_activity) >= 5:
            break

    return {
        "ok": True, "source": "execution_logs", "days": days,
        "summary": {
            "equity": latest_equity if latest_equity is not None else latest_balance,
            "balance": latest_balance, "open_risk_percent": latest_open_risk,
            "trades": trades, "wins": wins, "losses": losses,
            "win_rate": round(wins / trades * 100.0, 2) if trades else None,
            "profit_factor": round(pf, 3) if pf is not None else None,
            "net_pnl": round(sum(all_pnls), 2),
            "net_r": round(sum(x["net_r"] for x in daily), 2),
            "max_drawdown": round(overall_max_dd, 2),
        },
        "today": today, "daily": daily,
        "recent_activity": recent_activity,
    }


# ============================================================
# HTTP HANDLER
# ============================================================

# Stage 10 endpoint surface:
# /api/runtime/resilience/{bot_id}/disconnect
# /api/runtime/resilience/{bot_id}/recover
# /api/runtime/resilience/{bot_id}/restart-recovery
# /api/runtime/resilience/{bot_id}/status

class VelmontaireHandler(
    BaseHTTPRequestHandler
):

    server_version = "VELMONTAIRE/1.0"


    # ========================================================
    # GET
    # ========================================================

    def do_GET(
        self,
    ) -> None:

        path = urlparse(
            self.path
        ).path

        if path == "/api/public/live-pulse":
            status, payload = PUBLIC_LIVE_PULSE.get()
            return self._json(status, payload)


        # ----------------------------------------------------
        # HEALTH
        # ----------------------------------------------------

        if path == "/api/health":

            return self._json(
                200,
                {
                    "ok": True,
                    "service": (
                        "velmontaire-web"
                    ),
                },
            )


        # ----------------------------------------------------
        # AUTH / ME
        # ----------------------------------------------------

        if path == "/api/auth/me":

            return self._send_auth_response(
                AUTH.me(
                    self._session_token()
                )
            )


        # ----------------------------------------------------
        # BACKTEST STATUS
        #
        # GET /api/backtests/{backtest_id}
        # ----------------------------------------------------

        if path.startswith(
            "/api/backtests/"
        ):

            principal = self._principal()

            if principal is None:
                return

            if not self._require_entitlement(principal, "BACKTEST"):
                return

            parts = (
                path
                .strip("/")
                .split("/")
            )


            if (
                len(parts) == 3
                and parts[0] == "api"
                and parts[1] == "backtests"
            ):

                backtest_id = parts[2]

                if not self._require_entitlement(principal, "BACKTEST"):
                    return

                status, payload = (
                    BACKTESTS.status(
                        principal.user_id,
                        backtest_id,
                    )
                )


                return self._json(
                    status,
                    payload,
                )


        # ----------------------------------------------------
        # STRATEGY LIBRARY
        #
        # GET /api/strategies
        # GET /api/strategies/{id}/versions
        # ----------------------------------------------------

        if path == "/api/strategies":
            principal = self._principal()
            if principal is None:
                return
            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return
            return self._strategy_call(
                lambda: STRATEGIES.list_strategies(user_id=principal.user_id)
            )

        if path.startswith("/api/strategies/") and path.endswith("/versions"):
            principal = self._principal()
            if principal is None:
                return
            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                return self._json(404, {"ok": False, "error": "not_found"})
            strategy_id = parts[2]
            return self._strategy_call(
                lambda: STRATEGIES.version_history(
                    user_id=principal.user_id,
                    strategy_id=strategy_id,
                )
            )

        # GET /api/strategies/{id}
        if path.startswith("/api/strategies/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                principal = self._principal()
                if principal is None:
                    return
                if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                    return
                return self._strategy_call(
                    lambda: STRATEGIES.strategy_detail(
                        user_id=principal.user_id,
                        strategy_id=parts[2],
                    )
                )

        # ----------------------------------------------------
        # STRATEGY REVIEW
        #
        # GET /api/strategies/{id}/review
        # ----------------------------------------------------

        if (
            path.startswith(
                "/api/strategies/"
            )
            and path.endswith(
                "/review"
            )
        ):

            principal = self._principal()

            if principal is None:
                return

            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return

            strategy_id = (
                path.split("/")[3]
            )

            return self._strategy_call(
                lambda: (
                    STRATEGIES.review(
                        user_id=(
                            principal.user_id
                        ),
                        strategy_id=(
                            strategy_id
                        ),
                    )
                )
            )


        if path.startswith("/api/runtime/live/") and path.endswith("/status"):
            principal = self._principal()
            if principal is None: return
            if not self._require_entitlement(principal, "LIVE_EXECUTION"): return
            if LIVE_APP is None: return self._json(503, {"ok": False, "error": "live_runtime_not_configured"})
            parts=path.strip("/").split("/")
            if len(parts)!=5: return self._json(404, {"ok": False, "error": "not_found"})
            try: status,payload=LIVE_APP.status(user_id=principal.user_id,bot_id=parts[3])
            except RuntimeError as exc: return self._json(409, {"ok": False, "error": str(exc)})
            return self._json(status,payload)

        if path.startswith("/api/runtime/resilience/") and path.endswith("/status"):
            principal = self._principal()
            if principal is None:
                return

            if RESILIENCE_APP is None:
                return self._json(
                    503,
                    {"ok": False, "error": "runtime_resilience_not_configured"},
                )

            parts = path.strip("/").split("/")
            if len(parts) != 5:
                return self._json(404, {"ok": False, "error": "not_found"})

            try:
                status, payload = RESILIENCE_APP.status(
                    user_id=principal.user_id,
                    bot_id=parts[3],
                )
            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

            return self._json(status, payload)

        if path == "/api/dashboard/statistics":
            principal = self._principal()
            if principal is None:
                return
            query = parse_qs(urlparse(self.path).query)
            try:
                days = int((query.get("days") or ["30"])[0])
            except (TypeError, ValueError):
                return self._json(400, {"ok": False, "error": "invalid_days"})
            try:
                payload = _dashboard_statistics(principal.user_id, days)
            except Exception as exc:
                return self._json(500, {"ok": False, "error": f"statistics_failed:{exc}"})
            return self._json(200, payload)

        if path == "/api/billing/plans":
            principal=self._principal()
            if principal is None:return
            status,payload=BILLING.plans_public()
            return self._json(status,payload)

        if path == "/api/billing/checkout-config":
            principal=self._principal()
            if principal is None:return
            status,payload=BILLING.checkout_config()
            return self._json(status,payload)

        if path == "/api/billing/me":
            principal=self._principal()
            if principal is None:return
            try:status,payload=BILLING.me(user_id=principal.user_id)
            except RuntimeError as exc:return self._json(409,{"ok":False,"error":str(exc)})
            return self._json(status,payload)

        # ----------------------------------------------------
        # PROP RULES
        # ----------------------------------------------------

        if path == "/api/notifications":
            principal=self._principal()
            if principal is None:return
            status,payload=NOTIFICATIONS.list(principal.user_id)
            return self._json(status,payload)

        if path == "/api/capability-requests":
            principal=self._principal()
            if principal is None:return
            status,payload=CAPABILITY_REQUESTS.list(principal.user_id)
            return self._json(status,payload)

        if path == "/api/futures-prop/details":
            principal=self._principal()
            if principal is None:return
            if not self._require_entitlement(principal,"FUTURES_PROP"):return
            q=parse_qs(urlparse(self.path).query)
            status,payload=FUTURES_PROP.details((q.get("firm") or [""])[0],(q.get("program") or [""])[0],(q.get("stage") or [""])[0],(q.get("account_size") or ["0"])[0])
            return self._json(status,payload)

        if path == "/api/futures-prop/catalog":
            principal=self._principal()
            if principal is None:return
            if not self._require_entitlement(principal,"FUTURES_PROP"):return
            status,payload=FUTURES_PROP.catalog()
            return self._json(status,payload)

        if path == "/api/markets/catalog":
            principal=self._principal()
            if principal is None:return
            if not self._require_entitlement(principal,"PERSONAL_MARKETS"):return
            status,payload=MARKETS.catalog()
            return self._json(status,payload)

        if path == "/api/prop-rules/details":
            principal=self._principal()
            if principal is None:return
            if not self._require_entitlement(principal,"CFD_PROP"):return
            q=parse_qs(urlparse(self.path).query)
            status,payload=PROP_RULES.details(principal.user_id,(q.get("firm") or [""])[0],(q.get("program") or [""])[0],(q.get("phase") or [""])[0],(q.get("account_size") or ["0"])[0])
            return self._json(status,payload)

        if path == "/api/prop-rules/catalog":
            principal = self._principal()
            if principal is None:
                return
            if not self._require_entitlement(principal, "CFD_PROP"):
                return

            status, payload = PROP_RULES.catalog(
                principal.user_id
            )
            return self._json(
                status,
                payload,
            )

        if path == "/api/prop-rules/current":
            principal = self._principal()
            if principal is None:
                return
            if not self._require_entitlement(principal, "CFD_PROP"):
                return

            status, payload = PROP_RULES.current(
                principal.user_id
            )
            return self._json(
                status,
                payload,
            )

        # ----------------------------------------------------
        # STATIC
        # ----------------------------------------------------

        return self._serve_static(
            path
        )


    # ========================================================
    # POST
    # ========================================================

    def do_POST(
        self,
    ) -> None:

        path = urlparse(
            self.path
        ).path
        if path == "/api/billing/paddle/webhook":
            try:size=int(self.headers.get("Content-Length","0"))
            except ValueError:size=0
            if size <= 0 or size > 256*1024:return self._json(400,{"ok":False,"error":"invalid_body_size"})
            raw=self.rfile.read(size)
            status,payload=PADDLE_SANDBOX.ingest(raw,self.headers.get("Paddle-Signature",""))
            return self._json(status,payload)



        # ----------------------------------------------------
        # REGISTER
        # ----------------------------------------------------

        if path == "/api/auth/register":

            return self._send_auth_response(
                AUTH.register(
                    self._json_body()
                )
            )


        # ----------------------------------------------------
        # LOGIN
        # ----------------------------------------------------

        if path == "/api/auth/login":

            return self._send_auth_response(
                AUTH.login(
                    self._json_body()
                )
            )


        # ----------------------------------------------------
        # LOGOUT
        # ----------------------------------------------------

        if path == "/api/auth/logout":

            return self._send_auth_response(
                AUTH.logout(
                    self._session_token()
                )
            )


        # ----------------------------------------------------
        # AUTH REQUIRED BELOW
        # ----------------------------------------------------

        principal = self._principal()

        if principal is None:
            return


        if path.startswith("/api/runtime/resilience/"):
            if RESILIENCE_APP is None:
                return self._json(
                    503,
                    {"ok": False, "error": "runtime_resilience_not_configured"},
                )

            parts = path.strip("/").split("/")
            if len(parts) != 5:
                return self._json(404, {"ok": False, "error": "not_found"})

            bot_id = parts[3]
            action = parts[4]

            try:
                if action == "disconnect":
                    status, payload = RESILIENCE_APP.disconnect(
                        user_id=principal.user_id,
                        bot_id=bot_id,
                    )

                elif action == "recover":
                    status, payload = RESILIENCE_APP.recover(
                        user_id=principal.user_id,
                        bot_id=bot_id,
                        connection_status=str(
                            self._json_body().get("connection_status", "")
                        ),
                    )

                elif action == "restart-recovery":
                    status, payload = RESILIENCE_APP.restart_recovery(
                        user_id=principal.user_id,
                        bot_id=bot_id,
                    )

                else:
                    return self._json(
                        404,
                        {"ok": False, "error": "not_found"},
                    )

            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            except RuntimeError as exc:
                return self._json(409, {"ok": False, "error": str(exc)})

            return self._json(status, payload)

        if path.startswith("/api/notifications/") and path.endswith("/read"):
            parts=path.strip("/").split("/")
            if len(parts)!=4:return self._json(404,{"ok":False,"error":"not_found"})
            status,payload=NOTIFICATIONS.mark_read(principal.user_id,parts[2])
            return self._json(status,payload)

        if path == "/api/capability-requests":
            status,payload=CAPABILITY_REQUESTS.submit(principal.user_id,self._json_body())
            return self._json(status,payload)

        if path == "/api/futures-prop/check":
            if not self._require_entitlement(principal,"FUTURES_PROP"):return
            status,payload=FUTURES_PROP.check(self._json_body())
            return self._json(status,payload)

        if path == "/api/markets/normalize":
            if not self._require_entitlement(principal,"PERSONAL_MARKETS"):return
            status,payload=MARKETS.normalize(self._json_body())
            return self._json(status,payload)

        if path == "/api/markets/futures-risk":
            if not self._require_entitlement(principal,"PERSONAL_MARKETS"):return
            status,payload=MARKETS.futures_risk(self._json_body())
            return self._json(status,payload)

        if path == "/api/prop-rules/compliance/check":
            if not self._require_entitlement(principal,"CFD_PROP"):return
            status,payload=PROP_COMPLIANCE.check(user_id=principal.user_id,body=self._json_body())
            return self._json(status,payload)

        if path == "/api/prop-rules/risk/check":
            if not self._require_entitlement(principal,"CFD_PROP"):return
            status,payload=PROP_RISK.evaluate(user_id=principal.user_id,body=self._json_body())
            return self._json(status,payload)

        if path == "/api/prop-rules/news/check":
            if not self._require_entitlement(principal,"CFD_PROP"):return
            status,payload=NEWS_COMPLIANCE.evaluate(user_id=principal.user_id,body=self._json_body())
            return self._json(status,payload)

        if path == "/api/prop-rules/select":
            if not self._require_entitlement(principal, "CFD_PROP"):
                return
            status, payload = PROP_RULES.select(
                principal.user_id,
                self._json_body(),
            )
            return self._json(
                status,
                payload,
            )

        if path == "/api/runtime/live/confirm":
            if not self._require_entitlement(principal,"LIVE_EXECUTION"):return
            if LIVE_APP is None: return self._json(503, {"ok": False, "error": "live_runtime_not_configured"})
            try: status,payload=LIVE_APP.confirm_live(user_id=principal.user_id,body=self._json_body())
            except PermissionError: return self._json(404, {"ok": False, "error": "not_found"})
            except ValueError as exc: return self._json(400, {"ok": False, "error": str(exc)})
            except RuntimeError as exc: return self._json(409, {"ok": False, "error": str(exc)})
            return self._json(status,payload)

        if path == "/api/runtime/live/start":
            if not self._require_entitlement(principal,"LIVE_EXECUTION"):
                return
            if LIVE_APP is None: return self._json(503, {"ok": False, "error": "live_runtime_not_configured"})
            try: status,payload=LIVE_APP.start_live(user_id=principal.user_id,body=self._json_body())
            except PermissionError: return self._json(404, {"ok": False, "error": "not_found"})
            except (ValueError,RuntimeError) as exc: return self._json(409, {"ok": False, "error": str(exc)})
            return self._json(status,payload)

        if path.startswith("/api/runtime/live/") and path.endswith("/command"):
            if not self._require_entitlement(principal,"LIVE_EXECUTION"):return
            if LIVE_APP is None: return self._json(503, {"ok": False, "error": "live_runtime_not_configured"})
            parts=path.strip("/").split("/")
            if len(parts)!=5: return self._json(404, {"ok": False, "error": "not_found"})
            try: status,payload=LIVE_APP.command(user_id=principal.user_id,bot_id=parts[3],action=str(self._json_body().get("action","")))
            except ValueError as exc: return self._json(400, {"ok": False, "error": str(exc)})
            except RuntimeError as exc: return self._json(409, {"ok": False, "error": str(exc)})
            return self._json(status,payload)

        if path.startswith("/api/runtime/live/") and path.endswith("/revoke"):
            if not self._require_entitlement(principal,"LIVE_EXECUTION"):return
            if LIVE_APP is None: return self._json(503, {"ok": False, "error": "live_runtime_not_configured"})
            parts=path.strip("/").split("/")
            if len(parts)!=5: return self._json(404, {"ok": False, "error": "not_found"})
            status,payload=LIVE_APP.revoke_live(user_id=principal.user_id,bot_id=parts[3])
            return self._json(status,payload)

        if path == "/api/mt5/connections":
            if not self._require_entitlement(principal,"PAPER_TRADING"):return
            if MT5_PAPER is None:
                return self._json(503, {"ok": False, "error": "mt5_paper_core_not_configured"})
            try:
                status, payload = MT5_PAPER.create_connection(
                    user_id=principal.user_id,
                    body=self._json_body(),
                )
            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            return self._json(status, payload)

        if path.startswith("/api/mt5/connections/") and path.endswith("/test"):
            if not self._require_entitlement(principal,"PAPER_TRADING"):return
            if MT5_PAPER is None:
                return self._json(503, {"ok": False, "error": "mt5_paper_core_not_configured"})
            parts = path.strip("/").split("/")
            if len(parts) != 5:
                return self._json(404, {"ok": False, "error": "not_found"})
            try:
                status, payload = MT5_PAPER.test_connection(
                    user_id=principal.user_id,
                    connection_id=parts[3],
                )
            except PermissionError:
                return self._json(404, {"ok": False, "error": "not_found"})
            return self._json(status, payload)

        if path == "/api/runtime/paper/start":
            if not self._require_entitlement(principal,"PAPER_TRADING"):return
            if MT5_PAPER is None:
                return self._json(503, {"ok": False, "error": "mt5_paper_core_not_configured"})
            try:
                status, payload = MT5_PAPER.start_paper(
                    user_id=principal.user_id,
                    body=self._json_body(),
                )
            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            except RuntimeError as exc:
                return self._json(409, {"ok": False, "error": str(exc)})
            return self._json(status, payload)
        # ----------------------------------------------------
        # VERSION COMPARISON
        #
        # POST /api/comparisons
        # ----------------------------------------------------

        if path == "/api/comparisons":

            if not self._require_entitlement(principal, "ADVANCED_ANALYTICS"):
                return

            status, payload = COMPARISONS.compare(
                user_id=principal.user_id,
                body=self._json_body(),
            )

            return self._json(
                status,
                payload,
            )



        # ----------------------------------------------------
        # CREATE BACKTEST
        #
        # POST /api/backtests
        # ----------------------------------------------------

        if path == "/api/backtests":

            if not self._require_entitlement(principal, "BACKTEST"):
                return

            body = self._json_body()


            status, payload = (
                BACKTESTS.create(
                    principal.user_id,
                    body,
                )
            )


            return self._json(
                status,
                payload,
            )


        # ----------------------------------------------------
        # RUN BACKTEST
        #
        # POST /api/backtests/{id}/run
        # ----------------------------------------------------

        if (
            path.startswith(
                "/api/backtests/"
            )
            and path.endswith(
                "/run"
            )
        ):

            parts = (
                path
                .strip("/")
                .split("/")
            )


            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "backtests"
                and parts[3] == "run"
            ):

                backtest_id = parts[2]


                status, payload = (
                    BACKTESTS.run(
                        principal.user_id,
                        backtest_id,
                    )
                )


                return self._json(
                    status,
                    payload,
                )


        # ----------------------------------------------------
        # CREATE STRATEGY
        #
        # POST /api/strategies
        # ----------------------------------------------------

        if path == "/api/strategies":

            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return

            body = self._json_body()


            return self._strategy_call(
                lambda: (
                    STRATEGIES.create(
                        user_id=(
                            principal.user_id
                        ),
                        body=body,
                    )
                ),
                success_status=201,
            )


        # ----------------------------------------------------
        # STRATEGY CLARIFICATION
        #
        # POST /api/strategies/{id}/clarification
        # ----------------------------------------------------

        if (
            path.startswith(
                "/api/strategies/"
            )
            and path.endswith(
                "/clarification"
            )
        ):

            strategy_id = (
                path.split("/")[3]
            )

            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return

            body = self._json_body()


            return self._strategy_call(
                lambda: (
                    STRATEGIES.answer(
                        user_id=(
                            principal.user_id
                        ),
                        strategy_id=(
                            strategy_id
                        ),
                        body=body,
                    )
                )
            )


        # ----------------------------------------------------
        # STRATEGY APPROVAL
        #
        # POST /api/strategies/{id}/approve
        # ----------------------------------------------------

        if (
            path.startswith(
                "/api/strategies/"
            )
            and path.endswith(
                "/approve"
            )
        ):

            strategy_id = (
                path.split("/")[3]
            )

            if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                return

            body = self._json_body()


            return self._strategy_call(
                lambda: (
                    STRATEGIES.approve(
                        user_id=(
                            principal.user_id
                        ),
                        strategy_id=(
                            strategy_id
                        ),
                        body=body,
                    )
                )
            )


        # ----------------------------------------------------
        # STRATEGY LIBRARY ACTIONS
        #
        # POST /api/strategies/{id}/rename
        # POST /api/strategies/{id}/favorite
        # POST /api/strategies/{id}/duplicate
        # POST /api/strategies/{id}/archive
        # POST /api/strategies/{id}/restore
        # POST /api/strategies/{id}/delete
        # ----------------------------------------------------

        if path.startswith("/api/strategies/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "strategies":
                strategy_id = parts[2]
                action = parts[3]

                if not self._require_entitlement(principal, "AI_STRATEGY_BUILDER"):
                    return

                body = self._json_body()

                if action == "rename":
                    return self._strategy_call(
                        lambda: STRATEGIES.rename_strategy(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                            body=body,
                        )
                    )

                if action == "favorite":
                    return self._strategy_call(
                        lambda: STRATEGIES.set_favorite(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                            body=body,
                        )
                    )

                if action == "duplicate":
                    return self._strategy_call(
                        lambda: STRATEGIES.duplicate_strategy(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                            body=body,
                        ),
                        success_status=201,
                    )

                if action == "archive":
                    return self._strategy_call(
                        lambda: STRATEGIES.archive_library_strategy(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                        )
                    )

                if action == "restore":
                    return self._strategy_call(
                        lambda: STRATEGIES.restore_library_strategy(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                        )
                    )

                if action == "delete":
                    return self._strategy_call(
                        lambda: STRATEGIES.delete_strategy(
                            user_id=principal.user_id,
                            strategy_id=strategy_id,
                        )
                    )

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        return self._json(
            404,
            {
                "ok": False,
                "error": "not_found",
            },
        )


    # ========================================================
    # AUTH PRINCIPAL
    # ========================================================

    def _principal(
        self,
    ):

        token = self._session_token()


        if not token:

            self._json(
                401,
                {
                    "ok": False,
                    "error": (
                        "authentication_required"
                    ),
                },
            )

            return None


        principal = (
            _AUTH_SERVICE.authenticate(
                token
            )
        )


        if principal is None:

            self._json(
                401,
                {
                    "ok": False,
                    "error": (
                        "invalid_or_expired_session"
                    ),
                },
                headers=[
                    (
                        "Set-Cookie",
                        (
                            f"{COOKIE_NAME}=; "
                            "Path=/; "
                            "HttpOnly; "
                            "SameSite=Strict; "
                            "Max-Age=0"
                        ),
                    )
                ],
            )

            return None


        return principal


    # ========================================================
    # BILLING ENTITLEMENT GUARD
    # ========================================================

    def _require_entitlement(
        self,
        principal,
        capability: str,
    ) -> bool:

        result = BILLING.authorize(
            user_id=principal.user_id,
            capability=capability,
        )

        if result.get("allowed") is True:
            return True

        self._json(
            403,
            {
                "ok": False,
                "error": "entitlement_required",
                "capability": capability,
                "reason": result.get("reason", "forbidden"),
                "plan_code": result.get("plan_code"),
            },
        )
        return False


    # ========================================================
    # STRATEGY CALL WRAPPER
    # ========================================================

    def _strategy_call(
        self,
        fn,
        success_status=200,
    ) -> None:

        try:

            payload = fn()


        except PermissionError:

            return self._json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )


        except ValueError as exc:

            return self._json(
                400,
                {
                    "ok": False,
                    "error": str(exc),
                },
            )


        except RuntimeError as exc:

            return self._json(
                409,
                {
                    "ok": False,
                    "error": str(exc),
                },
            )


        return self._json(
            success_status,
            payload,
        )


    # ========================================================
    # STATIC FILES
    # ========================================================

    def _serve_static(
        self,
        path: str,
    ) -> None:

        routes = {

            "/": (
                FRONTEND_ROOT
                / "public"
                / "index.html"
            ),

            "/login": (
                FRONTEND_ROOT
                / "auth"
                / "login.html"
            ),

            "/register": (
                FRONTEND_ROOT
                / "auth"
                / "register.html"
            ),

            "/dashboard": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/overview": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/strategy": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/my-strategies": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/backtest": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/compare": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/prop-rules": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/mt5": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/paper": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/live": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/safety": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/billing": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),
            "/dashboard/telemetry": (
                FRONTEND_ROOT
                / "dashboard"
                / "index.html"
            ),

            "/docs": (FRONTEND_ROOT / "public" / "docs.html"),
            "/support": (FRONTEND_ROOT / "public" / "support.html"),
            "/product": (FRONTEND_ROOT / "public" / "product.html"),
            "/workflow": (FRONTEND_ROOT / "public" / "workflow.html"),
            "/controls": (FRONTEND_ROOT / "public" / "controls.html"),
            "/safety": (FRONTEND_ROOT / "public" / "safety.html"),
            "/pricing": (FRONTEND_ROOT / "public" / "pricing.html"),
            "/resources": (FRONTEND_ROOT / "public" / "resources.html"),
        }


        if path in routes:

            # Dashboard bootstrap: expose the authenticated user id to frontend JS.
            # This keeps billing checkout custom_data bound to the current account.
            if path.startswith("/dashboard"):
                principal = self._principal()
                if principal is None:
                    return
                dashboard_path = routes[path]
                if not dashboard_path.is_file():
                    return self._json(404, {"ok": False, "error": "not_found"})
                html = dashboard_path.read_text(encoding="utf-8")
                bootstrap = (
                    "<script>window.VELMONTAIRE_USER_ID="
                    + json.dumps(str(principal.user_id))
                    + ";</script>"
                )
                if "</head>" in html:
                    html = html.replace("</head>", bootstrap + "</head>", 1)
                else:
                    html = bootstrap + html
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                return

            return self._file(
                routes[path]
            )


        if path.startswith(
            "/frontend/"
        ):

            relative = (
                path.removeprefix(
                    "/frontend/"
                )
            )


            candidate = (
                FRONTEND_ROOT
                / relative
            ).resolve()


            try:

                candidate.relative_to(
                    FRONTEND_ROOT.resolve()
                )


            except ValueError:

                return self._json(
                    404,
                    {
                        "ok": False,
                        "error": "not_found",
                    },
                )


            return self._file(
                candidate
            )


        return self._json(
            404,
            {
                "ok": False,
                "error": "not_found",
            },
        )


    # ========================================================
    # FILE RESPONSE
    # ========================================================

    def _file(
        self,
        path: Path,
    ) -> None:

        if not path.is_file():

            return self._json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )


        data = path.read_bytes()


        content_type, _ = (
            mimetypes.guess_type(
                path.name
            )
        )


        self.send_response(
            200
        )


        self.send_header(
            "Content-Type",
            (
                content_type
                or "application/octet-stream"
            )
            + (
                "; charset=utf-8"
                if (
                    content_type
                    or ""
                ).startswith(
                    "text/"
                )
                else ""
            ),
        )


        self.send_header(
            "Content-Length",
            str(
                len(data)
            ),
        )


        self.send_header(
            "Cache-Control",
            "no-store",
        )


        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )


        self.end_headers()


        self.wfile.write(
            data
        )


    # ========================================================
    # JSON BODY
    # ========================================================

    def _json_body(
        self,
    ) -> dict:

        try:

            size = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )


        except ValueError:

            size = 0


        if (
            size <= 0
            or size > 64 * 1024
        ):

            return {}


        try:

            value = json.loads(
                self.rfile.read(
                    size
                ).decode(
                    "utf-8"
                )
            )


        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):

            return {}


        if isinstance(
            value,
            dict,
        ):

            return value


        return {}


    # ========================================================
    # SESSION COOKIE
    # ========================================================

    def _session_token(
        self,
    ) -> str | None:

        raw = self.headers.get(
            "Cookie",
            "",
        )


        if not raw:

            return None


        cookie = SimpleCookie()


        try:

            cookie.load(
                raw
            )


        except Exception:

            return None


        morsel = cookie.get(
            COOKIE_NAME
        )


        if morsel:

            return morsel.value


        return None


    # ========================================================
    # AUTH RESPONSE
    # ========================================================

    def _send_auth_response(
        self,
        result: WebAuthResponse,
    ) -> None:

        headers = []


        if result.session_token:

            headers.append(
                (
                    "Set-Cookie",
                    (
                        f"{COOKIE_NAME}="
                        f"{result.session_token}; "
                        "Path=/; "
                        "HttpOnly; "
                        "SameSite=Strict; "
                        "Max-Age=86400"
                    ),
                )
            )


        if result.clear_session:

            headers.append(
                (
                    "Set-Cookie",
                    (
                        f"{COOKIE_NAME}=; "
                        "Path=/; "
                        "HttpOnly; "
                        "SameSite=Strict; "
                        "Max-Age=0"
                    ),
                )
            )


        self._json(
            result.status_code,
            result.payload,
            headers=headers,
        )


    # ========================================================
    # JSON RESPONSE
    # ========================================================

    def _json(
        self,
        status: int,
        payload: dict,
        *,
        headers=None,
    ) -> None:

        data = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )


        self.send_response(
            int(status)
        )


        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )


        self.send_header(
            "Content-Length",
            str(
                len(data)
            ),
        )


        self.send_header(
            "Cache-Control",
            "no-store",
        )


        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )


        self.send_header(
            "Referrer-Policy",
            "same-origin",
        )


        for key, value in (
            headers
            or []
        ):

            self.send_header(
                key,
                value,
            )


        self.end_headers()


        self.wfile.write(
            data
        )


    # ========================================================
    # SERVER LOG
    # ========================================================

    def log_message(
        self,
        format: str,
        *args,
    ) -> None:

        print(
            "[VELMONTAIRE]",
            format % args,
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    print(
        "=" * 72
    )

    print(
        "VELMONTAIRE WEB"
    )

    print(
        f"http://{HOST}:{PORT}"
    )

    print(
        "CTRL+C to stop"
    )

    print(
        "=" * 72
    )


    server = ThreadingHTTPServer(
        (
            HOST,
            PORT,
        ),
        VelmontaireHandler,
    )


    try:

        server.serve_forever()


    except KeyboardInterrupt:

        pass


    finally:

        server.server_close()


if __name__ == "__main__":

    main()

