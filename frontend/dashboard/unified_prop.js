let unifiedPropCatalog=[];
function uSet(id,vals){const e=document.querySelector(id);if(e)e.innerHTML=vals.map(v=>`<option value="${v}">${v}</option>`).join("");}
function uVal(id){return document.querySelector(id)?.value||"";}
function uniq(a){return [...new Set(a)];}
async function loadUnifiedProps(){
 const type=uVal("#unified-prop-type");
 if(type==="FUTURES_PROP"){document.querySelector("#unified-prop-note").textContent="Use the verified Futures Prop selector below.";return;}
 const r=await fetch("/api/prop-rules/catalog",{credentials:"same-origin"}),d=await r.json();
 unifiedPropCatalog=d.unified_catalog||[];
 uSet("#unified-prop-firm",uniq(unifiedPropCatalog.map(x=>x.firm)));uPrograms();
}
function uPrograms(){let f=uVal("#unified-prop-firm");uSet("#unified-prop-program",uniq(unifiedPropCatalog.filter(x=>x.firm===f).map(x=>x.program)));uStages();}
function uStages(){let f=uVal("#unified-prop-firm"),p=uVal("#unified-prop-program");uSet("#unified-prop-stage",uniq(unifiedPropCatalog.filter(x=>x.firm===f&&x.program===p).map(x=>x.stage)));uSizes();}
function uSizes(){let f=uVal("#unified-prop-firm"),p=uVal("#unified-prop-program"),s=uVal("#unified-prop-stage"),x=unifiedPropCatalog.find(x=>x.firm===f&&x.program===p&&x.stage===s);uSet("#unified-prop-size",(x?.account_sizes||[]).map(String));uPreview();}
async function uPreview(){let f=uVal("#unified-prop-firm"),p=uVal("#unified-prop-program"),s=uVal("#unified-prop-stage"),z=uVal("#unified-prop-size"),o=document.querySelector("#unified-prop-preview");if(!f||!p||!s||!z||!o)return;let q=new URLSearchParams({firm:f,program:p,phase:s,account_size:z});let r=await fetch(`/api/prop-rules/details?${q}`,{credentials:"same-origin"}),d=await r.json();o.textContent=JSON.stringify(d.ruleset||d,null,2);}
["#unified-prop-type","#unified-prop-firm","#unified-prop-program","#unified-prop-stage","#unified-prop-size"].forEach((id,i)=>document.querySelector(id)?.addEventListener("change",[loadUnifiedProps,uPrograms,uStages,uSizes,uPreview][i]));
loadUnifiedProps();
