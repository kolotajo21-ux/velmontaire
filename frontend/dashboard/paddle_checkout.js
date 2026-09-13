let paddleReady=false,paddleCfg=null;
async function ensurePaddle(){if(paddleReady)return;let r=await fetch("/api/billing/checkout-config",{credentials:"same-origin",cache:"no-store"}),d=await r.json();if(!r.ok)throw Error(d.error||"checkout_unavailable");paddleCfg=d;Paddle.Environment.set("sandbox");Paddle.Initialize({token:d.client_token});paddleReady=true}
async function openPlan(plan){try{await ensurePaddle();Paddle.Checkout.open({items:[{priceId:paddleCfg.prices[plan],quantity:1}],customData:{user_id:window.VELMONTAIRE_USER_ID||"",plan_code:plan}})}catch(e){alert("Checkout unavailable: "+e.message)}}
document.addEventListener("click",e=>{let b=e.target.closest("[data-paddle-plan]");if(b)openPlan(b.dataset.paddlePlan)});
