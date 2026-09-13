class WebCapabilityRequestsApplication:
    def __init__(self,service): self.service=service
    def submit(self,user_id,body):
        try: r=self.service.submit(user_id,body.get("text",""))
        except ValueError as e: return 400,{"ok":False,"error":str(e)}
        return 200,{"ok":True,"request":r.to_dict()}
    def list(self,user_id):
        return 200,{"ok":True,"requests":self.service.list_for_owner(user_id)}
