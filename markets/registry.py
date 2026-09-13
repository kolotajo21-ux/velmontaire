from __future__ import annotations
import re
from markets.models import InstrumentSpec,MarketType
_CCY={"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD","NOK","SEK","DKK","SGD","HKD","CNH","MXN","ZAR","TRY","PLN","CZK","HUF"}
_SUFFIX=re.compile(r"(?i)(?:[._-]?(?:pro|raw|ecn|std|m|a|b|c|x|i))$")
class UniversalInstrumentRegistry:
    def __init__(self,specs=()):
        self._specs={};self._alias={}
        for x in specs:self.add(x)
    def add(self,spec):
        self._specs[spec.canonical_id.upper()]=spec
        for a in (spec.canonical_id,*spec.aliases):self._alias[self._clean(a)]=spec.canonical_id.upper()
    @staticmethod
    def _clean(v):return re.sub(r"[^A-Z0-9]","",str(v).upper())
    def resolve(self,symbol):
        raw=str(symbol).strip();key=self._clean(raw)
        cid=self._alias.get(key)
        if cid:return self._specs[cid]
        stripped=_SUFFIX.sub("",raw);key2=self._clean(stripped);cid=self._alias.get(key2)
        if cid:return self._specs[cid]
        if len(key2)==6 and key2[:3] in _CCY and key2[3:] in _CCY and key2[:3]!=key2[3:]:
            return InstrumentSpec(key2,MarketType.FOREX.value,key2[:3],key2[3:],aliases=(raw,))
        raise ValueError("instrument_unresolved")
    def normalize_broker_symbols(self,symbols):
        out=[]
        for s in symbols:
            try:
                x=self.resolve(s);out.append({"broker_symbol":s,"canonical_id":x.canonical_id,"market_type":x.market_type})
            except ValueError:out.append({"broker_symbol":s,"canonical_id":None,"market_type":"UNRESOLVED"})
        return out
    def catalog(self):return [x.to_dict() for x in sorted(self._specs.values(),key=lambda z:z.canonical_id)]
