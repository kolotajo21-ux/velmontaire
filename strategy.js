let activeStrategyId = null;
let activeVersionId = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.replace("/login");
    throw new Error("authentication_required");
  }
  if (!response.ok) throw new Error(data.error || "request_failed");
  return data;
}

function setFlowStatus(text, error = false) {
  const node = document.querySelector("#strategy-status");
  node.textContent = text;
  node.style.color = error ? "#d6a4a4" : "var(--gold)";
}

function renderClarification(data) {
  const box = document.querySelector("#clarification-box");
  const questions = data.questions || [];
  const blockers = data.blockers || [];

  if (data.ready) {
    box.innerHTML = `<div class="eyebrow">Clarification complete</div>
      <p class="sub">A new immutable strategy version has been created. Human review is now required.</p>
      <button id="load-review" class="btn gold">Open review</button>`;
    activeVersionId = data.persisted_version?.version_id || activeVersionId;
    document.querySelector("#load-review").onclick = loadReview;
    return;
  }

  box.innerHTML = `<div class="eyebrow">Clarification required</div>
    <h3>${questions.length} question${questions.length === 1 ? "" : "s"}</h3>
    <p class="sub">${blockers.map(x => escapeHtml(x)).join("<br>")}</p>
    <form id="clarification-form">
      ${questions.map((q, i) => `<div class="field"><label>${escapeHtml(q)}</label>
        <input name="answer_${i}" required placeholder="Your answer"></div>`).join("")}
      <button class="btn gold" type="submit">Submit answers</button>
    </form>`;

  document.querySelector("#clarification-form").onsubmit = async (event) => {
    event.preventDefault();
    const answers = {};
    questions.forEach((q, i) => {
      // Existing parser questions expose paths in blockers; bind by unresolved path when available.
      const blocker = blockers[i] || "";
      const key = blocker.startsWith("unresolved:") ? blocker.slice(11) : q;
      answers[key] = event.currentTarget.elements[`answer_${i}`].value;
    });
    try {
      const result = await api(`/api/strategies/${activeStrategyId}/clarification`, {
        method: "POST",
        body: JSON.stringify({answers}),
      });
      renderClarification(result.clarification);
    } catch (e) {
      setFlowStatus(e.message, true);
    }
  };
}

async function loadReview() {
  try {
    const result = await api(`/api/strategies/${activeStrategyId}/review`);
    const r = result.review;
    activeVersionId = r.version_id;
    const box = document.querySelector("#review-box");
    box.innerHTML = `<div class="eyebrow">Human review</div>
      <h3>Version ${r.version_number}</h3>
      <div class="review-grid">
        ${reviewItem("Entry", r.entry)}
        ${reviewItem("Filters", r.filters)}
        ${reviewItem("Stop Loss", r.stop_loss)}
        ${reviewItem("Take Profit", r.take_profit)}
        ${reviewItem("Risk", r.risk)}
        ${reviewItem("Management", r.management)}
      </div>
      <p class="sub">Unresolved: ${(r.unresolved_items || []).length}</p>
      <button id="approve-version" class="btn gold">Approve exact version</button>`;
    document.querySelector("#approve-version").onclick = approveVersion;
  } catch (e) {
    setFlowStatus(e.message, true);
  }
}

async function approveVersion() {
  try {
    await api(`/api/strategies/${activeStrategyId}/approve`, {
      method: "POST",
      body: JSON.stringify({version_id: activeVersionId}),
    });
    setFlowStatus(`Version ${activeVersionId} HUMAN APPROVED`);
    document.querySelector("#review-box").insertAdjacentHTML(
      "beforeend",
      `<p style="color:var(--gold)">✓ Exact immutable version approved. Backtest/MT5 stages may now be unlocked by the product journey.</p>`
    );
  } catch (e) {
    setFlowStatus(e.message, true);
  }
}

function reviewItem(label, value) {
  return `<div class="review-item"><small>${label}</small><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

document.querySelector("#strategy-create-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFlowStatus("Creating strategy…");
  const form = event.currentTarget;

  try {
    const result = await api("/api/strategies", {
      method: "POST",
      body: JSON.stringify({
        name: form.elements.name.value.trim(),
        source_text: form.elements.source_text.value.trim(),
      }),
    });
    activeStrategyId = result.strategy.strategy_id;
    activeVersionId = result.strategy.active_version_id;
    rememberStrategy(result.strategy);
    setFlowStatus(`Strategy created · ${activeStrategyId}`);
    renderClarification(result.clarification);
  } catch (e) {
    setFlowStatus(e.message, true);
  }
});


// Strategy Library ---------------------------------------------------------
const STRATEGY_LIBRARY_KEY = "velmontaire_strategy_library";
function readStrategyLibrary(){ try{return JSON.parse(localStorage.getItem(STRATEGY_LIBRARY_KEY)||"[]")}catch(_){return []} }
function writeStrategyLibrary(items){ localStorage.setItem(STRATEGY_LIBRARY_KEY, JSON.stringify(items.slice(0,100))); }
function rememberStrategy(strategy){
  if(!strategy?.strategy_id) return;
  const items=readStrategyLibrary().filter(x=>x.strategy_id!==strategy.strategy_id);
  items.unshift({strategy_id:strategy.strategy_id,name:strategy.name||"Untitled strategy",active_version_id:strategy.active_version_id||null,updated_at:new Date().toISOString()});
  writeStrategyLibrary(items); renderStrategyLibrary(items);
}
function normalizeStrategyList(data){
  const raw=Array.isArray(data)?data:(data?.strategies||data?.items||[]);
  return raw.map(x=>({strategy_id:x.strategy_id||x.id,name:x.name||"Untitled strategy",active_version_id:x.active_version_id||x.version_id||null,updated_at:x.updated_at||x.created_at||null})).filter(x=>x.strategy_id);
}
function renderStrategyLibrary(items=readStrategyLibrary()){
  const box=document.querySelector("#strategy-library-list"); if(!box) return;
  if(!items.length){box.innerHTML='<div class="strategy-library-empty">No strategies yet. Create your first strategy above.</div>';return;}
  box.innerHTML=items.map(x=>`<article class="strategy-library-card" data-strategy-id="${escapeHtml(x.strategy_id)}"><div><small>Strategy</small><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.strategy_id)}</p></div><div class="strategy-library-meta"><span>${x.active_version_id?`Version ${escapeHtml(x.active_version_id)}`:"No active version"}</span><button class="btn gold open-saved-strategy" type="button">Open</button></div></article>`).join("");
  box.querySelectorAll(".open-saved-strategy").forEach(btn=>btn.onclick=()=>{const card=btn.closest("[data-strategy-id]");activeStrategyId=card.dataset.strategyId;const item=items.find(x=>String(x.strategy_id)===activeStrategyId);activeVersionId=item?.active_version_id||null;setFlowStatus(`Strategy selected · ${activeStrategyId}`);if(activeVersionId) loadReview();document.querySelector("#strategy-create-form")?.scrollIntoView({behavior:"smooth",block:"start"});});
}
async function loadStrategyLibrary(){
  let items=readStrategyLibrary();
  try{const server=await api("/api/strategies");const remote=normalizeStrategyList(server);if(remote.length){items=remote;writeStrategyLibrary(items)}}catch(_){/* keep local index if list endpoint is unavailable */}
  renderStrategyLibrary(items);
}
document.querySelector("#refresh-strategies")?.addEventListener("click",loadStrategyLibrary);
document.addEventListener("DOMContentLoaded",loadStrategyLibrary);
