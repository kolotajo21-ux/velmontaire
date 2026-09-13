let statisticsDays = 30;

function money(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const sign = number > 0 ? "+" : "";
  return `${sign}$${number.toFixed(2)}`;
}

function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number.toFixed(1)}%`;
}

function numberOrDash(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function valueClass(value) {
  const number = Number(value);
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "flat";
}

function drawDailyPnl(rows) {
  const canvas = document.querySelector("#daily-pnl-chart");
  if (!canvas) return;

  const usable = rows || [];
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(650, canvas.clientWidth || 650);
  const height = 245;

  canvas.width = width * ratio;
  canvas.height = height * ratio;

  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const values = usable.map((row) => Number(row.net_pnl || 0));
  const padding = {left: 48, right: 14, top: 18, bottom: 34};
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v)));
  const centerY = padding.top + chartH / 2;

  ctx.strokeStyle = "rgba(255,255,255,.065)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "rgba(212,175,55,.28)";
  ctx.beginPath();
  ctx.moveTo(padding.left, centerY);
  ctx.lineTo(width - padding.right, centerY);
  ctx.stroke();

  const count = Math.max(1, values.length);
  const slot = chartW / count;
  const barWidth = Math.max(3, Math.min(16, slot * .55));

  usable.forEach((row, index) => {
    const value = Number(row.net_pnl || 0);
    const h = Math.abs(value) / maxAbs * (chartH / 2 - 8);
    const x = padding.left + slot * index + slot / 2 - barWidth / 2;
    const y = value >= 0 ? centerY - h : centerY;

    ctx.fillStyle = value > 0
      ? "rgba(145,185,154,.78)"
      : value < 0
        ? "rgba(214,143,143,.78)"
        : "rgba(120,124,120,.25)";
    ctx.fillRect(x, y, barWidth, Math.max(1, h));

    if (usable.length <= 31 && (index % Math.max(1, Math.ceil(usable.length / 7)) === 0 || index === usable.length - 1)) {
      ctx.fillStyle = "#646b66";
      ctx.font = "8px Inter, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(String(row.date || "").slice(5), x + barWidth / 2, height - 13);
    }
  });
}

function renderDailyRows(rows) {
  const body = document.querySelector("#daily-statistics-rows");
  if (!body) return;

  body.innerHTML = [...(rows || [])].reverse().map((row) => {
    const wr = row.trades ? (row.wins / row.trades * 100) : 0;
    return `
      <tr>
        <td>${row.date}</td>
        <td>${row.trades}</td>
        <td>${row.wins} / ${row.losses}</td>
        <td>${row.trades ? wr.toFixed(1) + "%" : "—"}</td>
        <td class="${valueClass(row.net_pnl)}">${money(row.net_pnl)}</td>
        <td class="${valueClass(row.net_r)}">${numberOrDash(row.net_r)}R</td>
        <td>${money(-Math.abs(Number(row.max_drawdown || 0)))}</td>
      </tr>
    `;
  }).join("");
}


function compactDate(value) {
  const text = String(value || "");
  if (text.length < 10) return "—";
  const [year, month, day] = text.slice(0, 10).split("-");
  return `${day}.${month}`;
}

function drawSnapshotEquity(payload) {
  const canvas = document.querySelector("#snapshot-equity-chart");
  if (!canvas) return;

  const rows = payload.daily || [];
  const summary = payload.summary || {};
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(560, canvas.clientWidth || 560);
  const height = 190;

  canvas.width = width * ratio;
  canvas.height = height * ratio;

  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const totalPnl = rows.reduce((sum, row) => sum + Number(row.net_pnl || 0), 0);
  const endingEquity = Number(summary.equity);
  const hasEquity = Number.isFinite(endingEquity);
  let running = hasEquity ? endingEquity - totalPnl : 0;

  const points = rows.map((row) => {
    running += Number(row.net_pnl || 0);
    return running;
  });

  if (!points.length) return;

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = Math.max(1, max - min);
  const pad = {left: 12, right: 12, top: 16, bottom: 12};
  const cw = width - pad.left - pad.right;
  const ch = height - pad.top - pad.bottom;

  ctx.strokeStyle = "rgba(255,255,255,.045)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = pad.top + (ch / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  const coords = points.map((value, index) => ({
    x: pad.left + (points.length === 1 ? cw / 2 : (index / (points.length - 1)) * cw),
    y: pad.top + (1 - (value - min) / range) * ch,
  }));

  ctx.strokeStyle = "#D4AF37";
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  coords.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();

  const last = coords[coords.length - 1];
  ctx.fillStyle = "#D4AF37";
  ctx.beginPath();
  ctx.arc(last.x, last.y, 2.5, 0, Math.PI * 2);
  ctx.fill();

  document.querySelector("#snap-start-date").textContent = compactDate(rows[0]?.date);
  document.querySelector("#snap-mid-date").textContent = compactDate(rows[Math.floor((rows.length - 1) / 2)]?.date);
  document.querySelector("#snap-end-date").textContent = compactDate(rows[rows.length - 1]?.date);
}

function friendlyActivityType(type) {
  const value = String(type || "").toUpperCase();
  if (value.includes("BACKTEST")) return "Backtest activity";
  if (value.includes("MATCH")) return "Strategy signal matched";
  if (value.includes("CLOSE") || value.includes("EXIT") || value.includes("SETTLED")) return "Trade result recorded";
  if (value.includes("LIVE")) return "LIVE runtime event";
  if (value.includes("PAPER")) return "PAPER runtime event";
  if (value.includes("RECOVER") || value.includes("RESTART")) return "Runtime recovery";
  if (value.includes("BLOCK")) return "Safety event";
  return String(type || "Runtime event").replaceAll("_", " ");
}

function relativeActivityTime(createdAt) {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function renderSnapshotActivity(events) {
  const root = document.querySelector("#snapshot-recent-activity");
  if (!root) return;

  if (!events?.length) {
    root.innerHTML = '<div class="snapshot-activity-empty">No recent execution activity yet.</div>';
    return;
  }

  root.innerHTML = events.slice(0, 5).map((event) => `
    <div class="snapshot-activity-item">
      <span class="snapshot-activity-icon">✓</span>
      <div>
        <strong>${friendlyActivityType(event.event_type)}</strong>
        <p>${event.detail || "Execution log event"}</p>
      </div>
      <time>${relativeActivityTime(event.created_at)}</time>
    </div>
  `).join("");
}

function renderHomepageStyleSnapshot(payload) {
  const summary = payload.summary || {};

  document.querySelector("#snap-equity").textContent = money(summary.equity);
  document.querySelector("#snap-win-rate").textContent = percent(summary.win_rate);
  document.querySelector("#snap-profit-factor").textContent =
    summary.profit_factor == null ? "—" : numberOrDash(summary.profit_factor);
  document.querySelector("#snap-open-risk").textContent =
    summary.open_risk_percent == null ? "—" : percent(summary.open_risk_percent);

  const net = Number(summary.net_pnl || 0);
  const equityChange = document.querySelector("#snap-equity-change");
  equityChange.textContent = summary.trades
    ? `${money(net)} · ${summary.trades} trades`
    : "Waiting for closed-trade data";
  equityChange.className = valueClass(net);

  document.querySelector("#snap-win-change").textContent =
    summary.trades ? `${summary.wins || 0}W / ${summary.losses || 0}L` : "Selected period";
  document.querySelector("#snap-risk-note").textContent =
    summary.open_risk_percent == null ? "No runtime risk snapshot yet" : "Latest runtime snapshot";
  document.querySelector("#snap-period").textContent = `${payload.days || statisticsDays}D`;

  drawSnapshotEquity(payload);
  renderSnapshotActivity(payload.recent_activity || []);
}


function renderStatistics(payload) {
  renderHomepageStyleSnapshot(payload);
  const summary = payload.summary || {};
  const today = payload.today || {};
  const rows = payload.daily || [];

  document.querySelector("#stat-equity").textContent = money(summary.equity);
  document.querySelector("#stat-equity-note").textContent =
    summary.equity == null ? "Waiting for account data" : "Latest account snapshot";

  const todayPnl = document.querySelector("#stat-today-pnl");
  todayPnl.textContent = money(today.net_pnl || 0);
  todayPnl.className = valueClass(today.net_pnl || 0);

  document.querySelector("#stat-today-trades").textContent = `${today.trades || 0} trades today`;
  document.querySelector("#stat-win-rate").textContent = percent(summary.win_rate);
  document.querySelector("#stat-profit-factor").textContent =
    summary.profit_factor == null ? "—" : numberOrDash(summary.profit_factor);
  document.querySelector("#stat-open-risk").textContent =
    summary.open_risk_percent == null ? "—" : percent(summary.open_risk_percent);

  document.querySelector("#stat-trades").textContent = summary.trades || 0;
  document.querySelector("#stat-wins").textContent = summary.wins || 0;
  document.querySelector("#stat-losses").textContent = summary.losses || 0;

  const netPnl = document.querySelector("#stat-net-pnl");
  netPnl.textContent = money(summary.net_pnl || 0);
  netPnl.className = valueClass(summary.net_pnl || 0);

  const netR = document.querySelector("#stat-net-r");
  netR.textContent = `${numberOrDash(summary.net_r || 0)}R`;
  netR.className = valueClass(summary.net_r || 0);

  document.querySelector("#stat-max-dd").textContent = money(-Math.abs(Number(summary.max_drawdown || 0)));
  document.querySelector("#statistics-period-label").textContent = `${payload.days || statisticsDays} DAYS`;
  document.querySelector("#statistics-source-text").textContent =
    payload.source === "execution_logs" ? "Execution logs" : (payload.source || "Execution logs");

  const hasTrades = Number(summary.trades || 0) > 0;
  document.querySelector("#statistics-empty").hidden = hasTrades;

  drawDailyPnl(rows);
  renderDailyRows(rows);
}

async function loadStatistics(days = statisticsDays) {
  statisticsDays = days;

  document.querySelectorAll(".stats-range").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.days) === days);
  });

  try {
    const response = await fetch(`/api/dashboard/statistics?days=${days}`, {
      credentials: "same-origin",
      cache: "no-store",
    });

    if (response.status === 401) {
      location.replace("/login");
      return;
    }

    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || "statistics_request_failed");
    }

    renderStatistics(payload);
  } catch (error) {
    const empty = document.querySelector("#statistics-empty");
    if (empty) {
      empty.hidden = false;
      empty.querySelector("strong").textContent = "Statistics unavailable";
      empty.querySelector("p").textContent = error.message;
    }
  }
}

document.querySelectorAll(".stats-range").forEach((button) => {
  button.addEventListener("click", () => loadStatistics(Number(button.dataset.days)));
});

document.querySelector("#statistics-refresh")?.addEventListener("click", () => loadStatistics(statisticsDays));

if (window.location.pathname.replace(/\/+$/, "") === "/dashboard") {
  loadStatistics(30);
}

window.addEventListener("resize", () => {
  if (window.location.pathname.replace(/\/+$/, "") === "/dashboard") {
    loadStatistics(statisticsDays);
  }
});
