async function comparisonApi(path, options={}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: {"Content-Type":"application/json", ...(options.headers||{})},
  });
  const data = await response.json().catch(()=>({}));
  if (response.status === 401) {
    location.replace("/login");
    throw new Error("authentication_required");
  }
  if (!response.ok) throw new Error(data.error || "request_failed");
  return data;
}
function comparisonMessage(text, error=false) {
  const node=document.querySelector("#comparison-status");
  node.textContent=text;
  node.style.color=error?"#d6a4a4":"var(--gold)";
}
function drawComparisonEquity(previous, candidate) {
  const canvas=document.querySelector("#comparison-equity");
  if (!canvas) return;
  const d=devicePixelRatio;
  canvas.width=Math.max(600,canvas.clientWidth)*d;
  canvas.height=260*d;
  const ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const series=[previous||[],candidate||[]].filter(x=>x.length);
  if (!series.length) return;
  const all=series.flat().map(p=>Number(p.equity)).filter(Number.isFinite);
  if (!all.length) return;
  const min=Math.min(...all),max=Math.max(...all),span=max-min||1,pad=28*d;
  const draw=(points,dash)=>{
    const vals=points.map(p=>Number(p.equity)).filter(Number.isFinite);
    if(vals.length<2)return;
    ctx.beginPath();ctx.setLineDash(dash);ctx.lineWidth=2*d;
    vals.forEach((v,i)=>{
      const x=pad+i*(canvas.width-2*pad)/Math.max(1,vals.length-1);
      const y=canvas.height-pad-(v-min)*(canvas.height-2*pad)/span;
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    });
    ctx.stroke();
  };
  draw(previous||[],[]);
  draw(candidate||[],[6*d,4*d]);
  ctx.setLineDash([]);
}
function renderComparison(payload) {
  const c=payload.comparison||{};
  const metrics=c.metrics||{};
  document.querySelector("#comparison-summary").textContent =
    `${c.summary||"UNKNOWN"} · automatic activation: ${c.automatic_activation===false?"NO":"—"}`;
  document.querySelector("#comparison-metrics").innerHTML =
    Object.entries(metrics).map(([name,item])=>`
      <tr><td>${name.replaceAll("_"," ")}</td><td>${item.previous ?? "—"}</td><td>${item.candidate ?? "—"}</td><td>${item.delta ?? "—"}</td><td>${item.direction ?? "UNKNOWN"}</td></tr>`).join("");
  const changes=c.schema_changes||[];
  document.querySelector("#comparison-changes").innerHTML =
    changes.length ? changes.map(x=>`<li>${x}</li>`).join("") : "<li>No schema differences reported.</li>";
  drawComparisonEquity(payload.previous_equity_curve,payload.candidate_equity_curve);
}
document.querySelector("#comparison-form")?.addEventListener("submit", async event=>{
  event.preventDefault();
  const form=event.currentTarget;
  try {
    comparisonMessage("Comparing immutable versions…");
    const result=await comparisonApi("/api/comparisons",{
      method:"POST",
      body:JSON.stringify({
        previous_backtest_id:form.elements.previous_backtest_id.value.trim(),
        candidate_backtest_id:form.elements.candidate_backtest_id.value.trim(),
      }),
    });
    renderComparison(result);
    comparisonMessage("COMPARISON READY");
  } catch(error) {
    comparisonMessage(error.message,true);
  }
});
