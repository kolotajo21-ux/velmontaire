class WebNotificationsApplication:
    def __init__(self,service):
        self.service=service
    def list(self,user_id):
        return 200,{"ok":True,"notifications":self.service.list_for_owner(user_id)}
    def mark_read(self,user_id,notification_id):
        try:
            x=self.service.mark_read(user_id,notification_id)
        except LookupError as e:
            return 404,{"ok":False,"error":str(e)}
        return 200,{"ok":True,"notification":x}
