from markets.models import InstrumentSpec,MarketType
from markets.registry import UniversalInstrumentRegistry
def build_default_instrument_registry():
    S=InstrumentSpec;F=MarketType
    return UniversalInstrumentRegistry([
      S("XAUUSD",F.METAL.value,"XAU","USD",("GOLD",)),S("XAGUSD",F.METAL.value,"XAG","USD",("SILVER",)),
      S("NAS100",F.INDEX_CFD.value,aliases=("US100","USTEC","NASDAQ","NASDAQ100")),S("US30",F.INDEX_CFD.value,aliases=("DJ30","DOW","DOWJONES")),
      S("SPX500",F.INDEX_CFD.value,aliases=("US500","SP500","S&P500")),S("GER40",F.INDEX_CFD.value,aliases=("DE40","DAX40","DAX")),
      S("UK100",F.INDEX_CFD.value,aliases=("FTSE100","FTSE")),S("USOIL",F.COMMODITY_CFD.value,aliases=("WTI","XTIUSD")),S("UKOIL",F.COMMODITY_CFD.value,aliases=("BRENT","XBRUSD")),
      S("BTCUSD",F.CRYPTO_CFD.value,"BTC","USD",("BITCOIN",)),S("ETHUSD",F.CRYPTO_CFD.value,"ETH","USD",("ETHEREUM",)),S("SOLUSD",F.CRYPTO_CFD.value,"SOL","USD",("SOLANA",)),
      S("ES",F.FUTURE.value,aliases=("E-MINI S&P 500",),tick_size=.25,tick_value=12.5,contract_multiplier=50,family="SP500",size_class="MINI",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("MES",F.FUTURE.value,tick_size=.25,tick_value=1.25,contract_multiplier=5,family="SP500",size_class="MICRO",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("NQ",F.FUTURE.value,tick_size=.25,tick_value=5,contract_multiplier=20,family="NASDAQ100",size_class="MINI",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("MNQ",F.FUTURE.value,tick_size=.25,tick_value=.5,contract_multiplier=2,family="NASDAQ100",size_class="MICRO",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("YM",F.FUTURE.value,tick_size=1,tick_value=5,contract_multiplier=5,family="DOW",size_class="MINI",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("MYM",F.FUTURE.value,tick_size=1,tick_value=.5,contract_multiplier=.5,family="DOW",size_class="MICRO",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("RTY",F.FUTURE.value,tick_size=.1,tick_value=5,contract_multiplier=50,family="RUSSELL2000",size_class="MINI",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("M2K",F.FUTURE.value,tick_size=.1,tick_value=.5,contract_multiplier=5,family="RUSSELL2000",size_class="MICRO",expiry_model="QUARTERLY",session_model="EXCHANGE"),
      S("GC",F.FUTURE.value,tick_size=.1,tick_value=10,contract_multiplier=100,family="GOLD",size_class="STANDARD",expiry_model="CONTRACT_MONTH",session_model="EXCHANGE"),
      S("MGC",F.FUTURE.value,tick_size=.1,tick_value=1,contract_multiplier=10,family="GOLD",size_class="MICRO",expiry_model="CONTRACT_MONTH",session_model="EXCHANGE"),
      S("CL",F.FUTURE.value,tick_size=.01,tick_value=10,contract_multiplier=1000,family="WTI",size_class="STANDARD",expiry_model="MONTHLY",session_model="EXCHANGE"),
      S("MCL",F.FUTURE.value,tick_size=.01,tick_value=1,contract_multiplier=100,family="WTI",size_class="MICRO",expiry_model="MONTHLY",session_model="EXCHANGE")
    ])
