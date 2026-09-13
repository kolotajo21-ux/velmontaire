async function loadNotifications(){
 const box=document.querySelector("#notification-list");
 if(!box)return;
 try{
  const r=await fetch("/api/notifications",{credentials:"same-origin"});
  if(!r.ok)throw new Error("notifications_unavailable");
  const d=await r.json();
  const items=d.notifications||[];
  const unread=items.filter(x=>!x.read).length;
  document.querySelectorAll("[data-notification-badge]").forEach((badge)=>{
   badge.textContent=unread?String(unread):"";
   badge.hidden=!unread;
  });
  box.innerHTML=items.length?items.map(x=>{
   const add=x.action?.type==="ADD_TO_STRATEGY"
    ? `<button class="btn" data-capability="${notificationEscape(x.action.capability_id)}">Add to strategy</button>`:"";
   const read=x.read?"":`<button class="btn" data-notification-read="${notificationEscape(x.notification_id)}">Mark read</button>`;
   return `<div class="notification-item ${x.read?"":"unread"}"><strong>${notificationEscape(x.title)}</strong><div>${notificationEscape(x.message)}</div><small>${notificationEscape(x.request_id||"")}</small>${add}${read}</div>`;
  }).join(""):"No notifications yet.";
 }catch(_){box.textContent="Notifications unavailable."}
}
function notificationEscape(value){
 return String(value??"")
  .replaceAll("&","&amp;")
  .replaceAll("<","&lt;")
  .replaceAll(">","&gt;")
  .replaceAll('"',"&quot;");
}
async function markNotificationRead(id){
 await fetch(`/api/notifications/${id}/read`,{method:"POST",credentials:"same-origin"});
 await loadNotifications();
}
document.querySelector("#notification-list")?.addEventListener("click",(event)=>{
 const button=event.target.closest("[data-notification-read]");
 if(button)markNotificationRead(button.dataset.notificationRead);
});
loadNotifications();
