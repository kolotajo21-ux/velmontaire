class CapabilityLifecycleService:
    ALLOWED={
        "PROPOSED":{"UNDER_VALIDATION"},
        "UNDER_VALIDATION":{"APPROVED_FOR_DEVELOPMENT"},
        "APPROVED_FOR_DEVELOPMENT":{"COMING_NEXT_UPDATE"},
        "COMING_NEXT_UPDATE":{"RELEASED"},
    }
    def __init__(self,requests,notifications):
        self.requests=requests
        self.notifications=notifications
    def transition(self,request_id,new_status,release_version=None,capability_id=None):
        r=self.requests._requests.get(str(request_id))
        if r is None:
            raise LookupError("capability_request_not_found")
        if new_status not in self.ALLOWED.get(r.status,set()):
            raise ValueError("invalid_capability_lifecycle_transition")
        if new_status=="RELEASED":
            if not release_version or not capability_id:
                raise ValueError("release_metadata_required")
            affected=[x for x in self.requests._requests.values() if x.normalized_key==r.normalized_key]
            for x in affected:
                x.status="RELEASED"
                self.notifications.create(
                    x.owner_id,"CAPABILITY_RELEASED",
                    "Your requested capability is now available",
                    f"{capability_id} is available in VELMONTAIRE {release_version}.",
                    request_id=x.request_id,
                    action={"type":"ADD_TO_STRATEGY","capability_id":capability_id,"release_version":release_version},
                )
            return {"status":"RELEASED","notified_users":len({x.owner_id for x in affected})}
        r.status=new_status
        self.notifications.create(
            r.owner_id,"CAPABILITY_STATUS","Capability request updated",
            f"{r.request_id}: {new_status.replace('_',' ').title()}.",
            request_id=r.request_id,
        )
        return {"status":new_status}
