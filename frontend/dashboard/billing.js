async function BL(path) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
  });

  const data = await response.json().catch(() => ({}));

  if (response.status === 401) {
    location.replace("/login");
    throw new Error("authentication_required");
  }

  if (!response.ok) {
    throw new Error(data.error || "request_failed");
  }

  return data;
}

const FALLBACK_PLANS = [
  {
    code: "CORE",
    name: "Core",
    monthly_usd: 29,
    annual_monthly_usd: 23,
    limits: {strategies: 3, backtests_monthly: 30, broker_connections: 0, active_live_bots: 0},
  },
  {
    code: "PRO",
    name: "Pro",
    monthly_usd: 49,
    annual_monthly_usd: 39,
    limits: {strategies: 15, backtests_monthly: 150, broker_connections: 3, active_live_bots: 3},
  },
  {
    code: "ELITE",
    name: "Elite",
    monthly_usd: 89,
    annual_monthly_usd: 71,
    limits: {strategies: 50, backtests_monthly: 500, broker_connections: 10, active_live_bots: 10},
  },
];

function usageCard(label, current, limit) {
  const safeCurrent = Number(current || 0);
  const safeLimit = Number(limit || 0);
  const pct = safeLimit > 0 ? Math.min(100, (safeCurrent / safeLimit) * 100) : 0;

  return `
    <div class="usage-card">
      <div><small>${label}</small><strong>${safeCurrent}<span> / ${safeLimit}</span></strong></div>
      <div class="usage-track"><i style="width:${pct}%"></i></div>
    </div>
  `;
}

function billingRender(data) {
  const subscription = data.subscription || null;
  const plan = data.plan || null;
  const usage = data.usage || {};
  const current = document.querySelector("#billing-current-plan");
  const status = document.querySelector("#billing-status");
  const cards = document.querySelector("#billing-usage-cards");

  if (current) {
    current.textContent = subscription?.plan_code || "No active plan";
  }

  if (status) {
    if (!subscription) {
      status.textContent = "Choose a plan below to unlock the workspace.";
    } else {
      status.textContent = `${subscription.subscription_status || "UNKNOWN"} · server-verified entitlements`;
    }
  }

  document.querySelectorAll("[data-plan-card]").forEach((node) => {
    node.classList.toggle(
      "current-plan",
      !!subscription && node.dataset.planCard === String(subscription.plan_code || "").toUpperCase()
    );
  });

  if (cards) {
    const limits = plan?.limits || {};
    cards.innerHTML = [
      usageCard("Strategies", usage.strategies, limits.strategies || 0),
      usageCard("Backtests", usage.backtests_this_month, limits.backtests_monthly || 0),
      usageCard("Brokers", usage.broker_connections, limits.broker_connections || 0),
      usageCard("Live bots", usage.active_bots, limits.active_live_bots || 0),
    ].join("");
  }

  const rawSub = document.querySelector("#billing-subscription");
  const rawUsage = document.querySelector("#billing-usage");
  if (rawSub) rawSub.textContent = JSON.stringify(subscription, null, 2);
  if (rawUsage) rawUsage.textContent = JSON.stringify(usage, null, 2);
}

async function billingRefresh() {
  const status = document.querySelector("#billing-status");

  try {
    const data = await BL("/api/billing/me");
    billingRender(data);
  } catch (error) {
    if (status) status.textContent = `Account status unavailable: ${error.message}`;
  }
}

document
  .querySelector("#billing-refresh")
  ?.addEventListener("click", billingRefresh);

billingRefresh();
