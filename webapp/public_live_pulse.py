from datetime import datetime,timezone
from market_data_free.prices import FreeMarketPriceAdapter
from market_events.biquote_calendar import BiQuoteCalendarAdapter
class PublicLivePulse:
 def __init__(self):self.prices=FreeMarketPriceAdapter();self.calendar=BiQuoteCalendarAdapter()
 def get(self):
  markets=self.prices.fetch()
  try:events=self.calendar.fetch()[:8];cal="LIVE"
  except Exception:events=[];cal="UNAVAILABLE"
  return 200,{"ok":True,"updated_at":datetime.now(timezone.utc).isoformat(),"system":{"status":"OPERATIONAL"},"markets":markets,"events":events,"activity":[],"feeds":{"economic_calendar":{"provider":"BiQuote Economic Calendar","status":cal},"market_prices":{"status":"LIVE" if markets else "NOT_CONNECTED","providers":["BiQuote Batch","XAUS"]}},"data_policy":"REAL_DATA_ONLY"}
