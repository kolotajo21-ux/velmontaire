async function F(p,o={}){let r=await fetch(p,{credentials:"same-origin",cache:"no-store",...o,headers:{"Content-Type":"application/json"}}),d=await r.json().catch(()=>({}));if(r.status===401){location.replace("/login");throw Error("authentication_required")}if(!r.ok)throw Error(d.error||"request_failed");return d}
function failureId(){return document.querySelector("#failure-bot-id")?.value.trim()||""}
function failureMessage(t,e=false){let n=document.querySelector("#failure-status");if(n){n.textContent=t;n.style.color=e?"#d6a4a4":"var(--gold)"}}
function renderFailure(d){let b=document.querySelector("#failure-banner"),x=document.querySelector("#failure-diagnostics");if(b){b.textContent=d.fail_closed?"EXECUTION BLOCKED · FAIL-CLOSED":"RUNTIME READY";b.dataset.state=d.fail_closed?"BLOCKED":"READY"}if(x)x.textContent=JSON.stringify(d,null,2)}
async function failurePost(suffix,body={}){let id=failureId();if(!id)return failureMessage("bot_id_required",true);try{let d=await F("/api/runtime/resilience/"+id+"/"+suffix,{method:"POST",body:JSON.stringify(body)});renderFailure(d);failureMessage(d.reason||suffix,d.fail_closed)}catch(e){failureMessage(e.message,true)}}
async function refreshFailure(){let id=failureId();if(!id)return failureMessage("bot_id_required",true);try{let d=await F("/api/runtime/resilience/"+id+"/status");renderFailure(d);failureMessage(d.fail_closed?"Runtime remains blocked.":"Runtime status refreshed.",d.fail_closed)}catch(e){failureMessage(e.message,true)}}
document.querySelector("#failure-disconnect")?.addEventListener("click",()=>failurePost("disconnect"));
document.querySelector("#failure-recover")?.addEventListener("click",()=>failurePost("recover",{connection_status:document.querySelector("#failure-connection-status").value}));
document.querySelector("#failure-restart")?.addEventListener("click",()=>failurePost("restart-recovery"));
document.querySelector("#failure-refresh")?.addEventListener("click",refreshFailure);
