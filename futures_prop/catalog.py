from futures_prop.models import FuturesPropRuleSet
from futures_prop.registry import FuturesPropRegistry
TOPSTEP_COMBINE="https://help.topstep.com/en/articles/8284197-trading-combine-parameters"
TOPSTEP_MLL="https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit"
MFF_RAPID="https://help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look"
TPT_RULES="https://try.takeprofittrader.com/TPT-FAQs-nf30r2-0526"
TPT_HOME="https://takeprofittrader.com/"

def build_default_futures_prop_registry():
    R=FuturesPropRuleSet
    base_ts={"market":"FUTURES","drawdown_type":"EOD_TRAILING_BALANCE","drawdown_breach_basis":"INTRADAY_EQUITY","drawdown_lock":"STARTING_BALANCE","micro_to_mini_ratio":10,"consistency_percent":50.0,"news_policy":"ALLOW","minimum_trading_days":None}
    return FuturesPropRegistry([
      R("topstep_combine_50k_202608","Topstep","Trading Combine","EVALUATION",50000,{**base_ts,"profit_target":3000.0,"max_loss_distance":2000.0,"max_minis":5,"max_micros":50},(TOPSTEP_COMBINE,TOPSTEP_MLL),"2026-08-19"),
      R("topstep_combine_100k_202608","Topstep","Trading Combine","EVALUATION",100000,{**base_ts,"profit_target":6000.0,"max_loss_distance":3000.0,"max_minis":10,"max_micros":100},(TOPSTEP_COMBINE,TOPSTEP_MLL),"2026-08-19"),
      R("topstep_combine_150k_202608","Topstep","Trading Combine","EVALUATION",150000,{**base_ts,"profit_target":9000.0,"max_loss_distance":4500.0,"max_minis":15,"max_micros":150},(TOPSTEP_COMBINE,TOPSTEP_MLL),"2026-08-19"),
      R("mff_rapid_50k_eval_202608","My Funded Futures","Rapid","EVALUATION",50000,{"market":"FUTURES","profit_target":3000.0,"drawdown_type":"EOD_TRAILING_BALANCE","drawdown_breach_basis":"EOD_EQUITY","max_loss_distance":2000.0,"daily_loss_limit":None,"max_minis":5,"max_micros":50,"micro_to_mini_ratio":10,"consistency_percent":50.0,"minimum_trading_days":2,"news_policy":"ALLOW_T1"},(MFF_RAPID,),"2026-08-19"),
      R("mff_rapid_50k_sim_202608","My Funded Futures","Rapid","SIM_FUNDED",50000,{"market":"FUTURES","starting_balance_model":"ZERO","drawdown_type":"INTRADAY_TRAILING_EQUITY_HWM","drawdown_breach_basis":"INTRADAY_EQUITY","max_loss_distance":2000.0,"drawdown_lock_value":100.0,"daily_loss_limit":None,"max_minis":5,"max_micros":50,"micro_to_mini_ratio":10,"consistency_percent":None,"minimum_trading_days":None,"news_policy":"BLOCK_T1"},(MFF_RAPID,),"2026-08-19"),
      R("tpt_test_50k_202608","Take Profit Trader","Test","EVALUATION",50000,{"market":"FUTURES","profit_target":3000.0,"drawdown_type":"EOD_TRAILING_BALANCE","drawdown_breach_basis":"EOD_EQUITY","max_loss_distance":2000.0,"daily_loss_limit":None,"max_minis":6,"max_micros":60,"micro_to_mini_ratio":10,"consistency_percent":50.0,"minimum_trading_days":5,"news_policy":"ALLOW","forced_flatten_required":True,"forced_flatten_time":"17:00 CT","automation_policy":"PROHIBITED"},(TPT_RULES,TPT_HOME),"2026-08-20")
    ])
