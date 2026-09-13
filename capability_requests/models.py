from dataclasses import dataclass,asdict
@dataclass(slots=True)
class CapabilityRequest:
    request_id:str
    owner_id:str
    text:str
    normalized_key:str
    status:str
    classification:str
    demand_count:int=1
    matched_capabilities:tuple[str,...]=()
    missing_capabilities:tuple[str,...]=()
    proposal:dict|None=None
    def to_dict(self): return asdict(self)
