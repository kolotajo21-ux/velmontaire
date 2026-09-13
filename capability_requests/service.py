from __future__ import annotations
import hashlib,re
from capability_requests.models import CapabilityRequest
from capability_requests.catalog import CAPABILITIES,ALIASES

class CapabilityRequestService:
    def __init__(self):
        self._requests={}
        self._by_owner={}
        self._demand={}
    @staticmethod
    def _normalize(text):
        return re.sub(r"[^a-z0-9а-яё]+"," ",str(text).lower()).strip()
    def _analyze(self,text):
        n=self._normalize(text); matched=set()
        for phrase,cap in ALIASES.items():
            pattern = r"(?<![a-z0-9а-яё])" + re.escape(phrase) + r"(?![a-z0-9а-яё])"
            if re.search(pattern, n):
                matched.add(cap)
        for cap in CAPABILITIES:
            phrase = cap.replace("_", " ")
            pattern = r"(?<![a-z0-9а-яё])" + re.escape(phrase) + r"(?![a-z0-9а-яё])"
            if re.search(pattern, n):
                matched.add(cap)
        composable=bool(matched) and any(x in n for x in ("после","если","только","after","if","when","выше","ниже","above","below"))
        if composable: return "COMPOSABLE_NOW",tuple(sorted(matched)),()
        if matched: return "AVAILABLE_NOW",tuple(sorted(matched)),()
        words=[w for w in n.split() if len(w)>3][:8]
        return "NEW_CAPABILITY_REQUIRED",(),("_".join(words[:4]) or "unspecified_capability",)
    def submit(self,owner_id,text):
        text=str(text).strip()
        if len(text)<8: raise ValueError("capability_request_too_short")
        if len(text)>4000: raise ValueError("capability_request_too_long")
        key=hashlib.sha256(self._normalize(text).encode()).hexdigest()[:20]
        cls,matched,missing=self._analyze(text)
        self._demand[key]=self._demand.get(key,0)+1
        rid="VR-"+hashlib.sha256((str(owner_id)+"|"+key).encode()).hexdigest()[:10].upper()
        if rid in self._requests:
            r=self._requests[rid]; r.demand_count=self._demand[key]; return r
        status="READY_TO_COMPOSE" if cls in {"COMPOSABLE_NOW","AVAILABLE_NOW"} else "PROPOSED"
        proposal=None
        if cls=="NEW_CAPABILITY_REQUIRED":
            proposal={"kind":"MODULE_PROPOSAL","schema_version":1,"requested_behavior":text,
            "missing_capabilities":list(missing),
            "required_gates":["SPEC_REVIEW","UNIT_TESTS","REGRESSION_TESTS","SECURITY_REVIEW","RELEASE_APPROVAL"],
            "production_code_mutation":False,"auto_activation":False}
        r=CapabilityRequest(rid,str(owner_id),text,key,status,cls,self._demand[key],matched,missing,proposal)
        self._requests[rid]=r; self._by_owner.setdefault(str(owner_id),[]).append(rid); return r
    def list_for_owner(self,owner_id):
        return [self._requests[x].to_dict() for x in self._by_owner.get(str(owner_id),[])]
    def get_for_owner(self,owner_id,request_id):
        r=self._requests.get(str(request_id))
        if r is None or r.owner_id!=str(owner_id): raise LookupError("capability_request_not_found")
        return r.to_dict()
    def release(self,request_id,approved=False,tests_passed=False,security_passed=False):
        r=self._requests.get(str(request_id))
        if r is None: raise LookupError("capability_request_not_found")
        if not (approved and tests_passed and security_passed): raise PermissionError("release_gates_not_satisfied")
        r.status="RELEASED_NEXT_UPDATE"; return r
