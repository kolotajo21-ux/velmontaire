let futuresPropCatalog={};
function setFP(id,v){const e=document.querySelector(id);if(e)e.innerHTML=v.map(x=>`<option value="${x}">${x}</option>`).join("");}
function valFP(id){return document.querySelector(id)?.value||"";}
async function loadFPCatalog(){const r=await fetch("/api/futures-prop/catalog",{credentials:"same-origin"}),d=await r.json();futuresPropCatalog=d.catalog||{};setFP("#futures-prop-firm",Object.keys(futuresPropCatalog));refreshFPPrograms();}
function refreshFPPrograms(){let f=valFP("#futures-prop-firm");setFP("#futures-prop-program",Object.keys(futuresPropCatalog[f]||{}));refreshFPStages();}
function refreshFPStages(){let f=valFP("#futures-prop-firm"),p=valFP("#futures-prop-program");setFP("#futures-prop-stage",Object.keys(futuresPropCatalog?.[f]?.[p]||{}));refreshFPSizes();}
function refreshFPSizes(){let f=valFP("#futures-prop-firm"),p=valFP("#futures-prop-program"),s=valFP("#futures-prop-stage");setFP("#futures-prop-size",(futuresPropCatalog?.[f]?.[p]?.[s]||[]).map(String));loadFPDetails();}
async function loadFPDetails(){let f=valFP("#futures-prop-firm"),p=valFP("#futures-prop-program"),s=valFP("#futures-prop-stage"),z=valFP("#futures-prop-size"),o=document.querySelector("#futures-prop-preview");if(!f||!p||!s||!z||!o)return;let q=new URLSearchParams({firm:f,program:p,stage:s,account_size:z});let r=await fetch(`/api/futures-prop/details?${q}`,{credentials:"same-origin"}),d=await r.json();o.textContent=JSON.stringify(d.ruleset||d,null,2);}
document.querySelector("#futures-prop-firm")?.addEventListener("change",refreshFPPrograms);
document.querySelector("#futures-prop-program")?.addEventListener("change",refreshFPStages);
document.querySelector("#futures-prop-stage")?.addEventListener("change",refreshFPSizes);
document.querySelector("#futures-prop-size")?.addEventListener("change",loadFPDetails);
loadFPCatalog();
