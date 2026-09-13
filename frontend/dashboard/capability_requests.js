async function submitCapabilityRequest(event){
 event.preventDefault();
 const text=document.querySelector("#capability-request-text")?.value?.trim();
 const status=document.querySelector("#capability-request-status");
 if(!text)return;
 status.textContent="Analyzing request...";
 try{
  const r=await fetch("/api/capability-requests",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})});
  const d=await r.json(); if(!r.ok)throw new Error(d.error||"request_failed");
  const x=d.request;
  status.textContent=(x.classification==="NEW_CAPABILITY_REQUIRED")
   ? `New capability required · ${x.request_id} · queued for controlled validation/release.`
   : `Available now · ${x.request_id} · ${(x.matched_capabilities||[]).join(", ")}`;
  await loadCapabilityRequests();
 }catch(e){status.textContent="Unable to submit: "+e.message;}
}
async function loadCapabilityRequests(){
 const box=document.querySelector("#capability-request-list"); if(!box)return;
 try{
  const r=await fetch("/api/capability-requests",{credentials:"same-origin"}); const d=await r.json();
  box.textContent=(d.requests||[]).map(x=>`${x.request_id} · ${x.status} · ${x.text}`).join("\n")||"No requests yet.";
 }catch(_){}
}
document.querySelector("#capability-request-form")?.addEventListener("submit",submitCapabilityRequest);
loadCapabilityRequests();
