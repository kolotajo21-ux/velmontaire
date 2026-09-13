from typing import Any
from backend.api.backtest_api import BacktestAPI
from application.backtest_job_service import BacktestJobService
from application.strategy_management_service import StrategyManagementService
class FailClosedBacktestCore:
    def run_backtest(self, command): raise RuntimeError("production_backtest_core_not_configured")
class WebBacktestApplication:
    def __init__(self,repository,bot_core=None):
        self.api=BacktestAPI(jobs=BacktestJobService(repository=repository,strategies=StrategyManagementService(repository),bot_core=bot_core or FailClosedBacktestCore()))
    def _x(self,r):
        c=int(r.get("status_code",500))
        return (c,{"ok":False,"error":str(r["error"])}) if "error" in r else (c,{"ok":True,**dict(r.get("data") or {})})
    def create(self,user_id,body): return self._x(self.api.create(principal={"user_id":user_id},body=body))
    def run(self,user_id,backtest_id): return self._x(self.api.run(principal={"user_id":user_id},backtest_id=backtest_id))
    def status(self,user_id,backtest_id): return self._x(self.api.status(principal={"user_id":user_id},backtest_id=backtest_id))
