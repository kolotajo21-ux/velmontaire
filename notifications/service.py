from __future__ import annotations
import hashlib
from datetime import datetime,timezone

class NotificationService:
    def __init__(self):
        self._items={}
        self._by_owner={}
    def create(self,owner_id,kind,title,message,request_id=None,action=None):
        seed=f"{owner_id}|{kind}|{request_id}|{title}|{len(self._items)}"
        nid="NT-"+hashlib.sha256(seed.encode()).hexdigest()[:12].upper()
        item={"notification_id":nid,"owner_id":str(owner_id),"kind":kind,"title":title,
              "message":message,"request_id":request_id,"action":action,"read":False,
              "created_at":datetime.now(timezone.utc).isoformat()}
        self._items[nid]=item
        self._by_owner.setdefault(str(owner_id),[]).append(nid)
        return dict(item)
    def list_for_owner(self,owner_id):
        return [dict(self._items[x]) for x in reversed(self._by_owner.get(str(owner_id),[]))]
    def mark_read(self,owner_id,notification_id):
        x=self._items.get(str(notification_id))
        if x is None or x["owner_id"]!=str(owner_id):
            raise LookupError("notification_not_found")
        x["read"]=True
        return dict(x)
