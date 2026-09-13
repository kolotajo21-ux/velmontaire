from __future__ import annotations
from dataclasses import dataclass,asdict
from enum import Enum

class MarketType(str,Enum):
    FOREX="FOREX";METAL="METAL";INDEX_CFD="INDEX_CFD";COMMODITY_CFD="COMMODITY_CFD"
    CRYPTO_CFD="CRYPTO_CFD";CRYPTO_SPOT="CRYPTO_SPOT";CRYPTO_PERP="CRYPTO_PERP";FUTURE="FUTURE"

@dataclass(frozen=True,slots=True)
class InstrumentSpec:
    canonical_id:str
    market_type:str
    base:str=""
    quote:str=""
    aliases:tuple[str,...]=()
    tick_size:float|None=None
    tick_value:float|None=None
    contract_multiplier:float|None=None
    currency:str="USD"
    family:str=""
    size_class:str=""
    expiry_model:str="NONE"
    session_model:str="BROKER"
    def to_dict(self):return asdict(self)
