let activeBacktestId = null;
let activeBacktestIds = [];

async function B(path, options = {}) {
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
    location.replace("/login");
    throw Error("authentication_required");
  }

  if (!response.ok) {
    throw Error(data.error || "request_failed");
  }

  return data;
}

function M(text, error = false) {
  const node = document.querySelector("#backtest-status");
  if (!node) return;

  node.textContent = text;
  node.style.color = error ? "#d6a4a4" : "var(--gold)";
}

function chart(points) {
  const canvas = document.querySelector("#equity-chart");

  if (!canvas || !points?.length) {
    return;
  }

  canvas.width =
    Math.max(600, canvas.clientWidth) *
    devicePixelRatio;

  canvas.height =
    240 *
    devicePixelRatio;

  const ctx = canvas.getContext("2d");

  const values =
    points.map((point) => +point.equity);

  const min =
    Math.min(...values);

  const max =
    Math.max(...values);

  const padding =
    24 *
    devicePixelRatio;

  ctx.clearRect(
    0,
    0,
    canvas.width,
    canvas.height
  );

  ctx.strokeStyle = "#c7a86b";

  ctx.lineWidth =
    2 *
    devicePixelRatio;

  ctx.beginPath();

  values.forEach((value, index) => {
    const X =
      padding +
      index *
        (canvas.width - 2 * padding) /
        Math.max(
          1,
          values.length - 1
        );

    const Y =
      canvas.height -
      padding -
      (value - min) *
        (canvas.height - 2 * padding) /
        Math.max(
          1,
          max - min
        );

    if (index) {
      ctx.lineTo(X, Y);
    } else {
      ctx.moveTo(X, Y);
    }
  });

  ctx.stroke();
}

function R(job) {
  const result =
    job.result || {};

  const metrics =
    result.metrics || {};

  const jobNode =
    document.querySelector("#backtest-job");

  if (jobNode) {
    jobNode.textContent =
      `${job.status} · ${job.backtest_id || ""} · version ${job.version_id || "—"}`;
  }

  const metricsNode =
    document.querySelector(
      "#backtest-metrics"
    );

  if (metricsNode) {
    metricsNode.innerHTML = [
      "trades",
      "win_rate",
      "net_r",
      "net_profit",
      "profit_factor",
      "max_drawdown",
      "expectancy_r",
      "ending_balance",
    ]
      .map(
        (key) => `
          <div class="stat">
            <small>
              ${key.replaceAll("_", " ")}
            </small>

            <strong>
              ${metrics[key] ?? "—"}
            </strong>
          </div>
        `
      )
      .join("");
  }

  chart(result.equity_curve);

  const tradesNode =
    document.querySelector(
      "#backtest-trades"
    );

  if (tradesNode) {
    tradesNode.innerHTML =
      (result.trades || [])
        .map(
          (trade) => `
            <tr>
              <td>${trade.side ?? ""}</td>
              <td>${trade.entry_time ?? ""}</td>
              <td>${trade.exit_time ?? ""}</td>
              <td>${trade.outcome ?? ""}</td>
              <td>${trade.r ?? ""}</td>
              <td>${trade.pnl_money ?? ""}</td>
              <td>${trade.cost_money ?? ""}</td>
            </tr>
          `
        )
        .join("");
  }

  const diagnosticsNode =
    document.querySelector(
      "#backtest-result"
    );

  if (diagnosticsNode) {
    diagnosticsNode.textContent =
      JSON.stringify(
        result.diagnostics || {},
        null,
        2
      );
  }
}

/* =========================================================
   ASSET UNIVERSE
   ========================================================= */

const ASSETS = {
  forex: [
    "AUDCAD",
    "AUDCHF",
    "AUDJPY",
    "AUDNZD",
    "AUDUSD",

    "CADCHF",
    "CADJPY",

    "CHFJPY",

    "EURAUD",
    "EURCAD",
    "EURCHF",
    "EURGBP",
    "EURJPY",
    "EURNZD",
    "EURUSD",

    "GBPAUD",
    "GBPCAD",
    "GBPCHF",
    "GBPJPY",
    "GBPNZD",
    "GBPUSD",

    "NZDCAD",
    "NZDCHF",
    "NZDJPY",
    "NZDUSD",

    "USDCAD",
    "USDCHF",
    "USDJPY",
  ],

  indices: [
    "US30",
    "US100",
    "US500",
    "UK100",
    "GER40",
    "FRA40",
    "EU50",
    "JP225",
    "AUS200",
    "HK50",
  ],

  metals: [
    "XAUUSD",
    "XAGUSD",
    "XPTUSD",
    "XPDUSD",
  ],
};

const selectedAssets =
  new Set();

let assetGroup = "forex";

function allAssets() {
  return [
    ...ASSETS.forex,
    ...ASSETS.indices,
    ...ASSETS.metals,
  ];
}

function visibleAssets() {
  const search =
    (
      document.querySelector(
        "#asset-search"
      )?.value || ""
    )
      .trim()
      .toUpperCase();

  const source =
    assetGroup === "all"
      ? allAssets()
      : ASSETS[assetGroup] || [];

  return source.filter(
    (symbol) =>
      !search ||
      symbol.includes(search)
  );
}

/* =========================================================
   CREATE MULTI-ASSET UI AUTOMATICALLY
   ========================================================= */

function installAssetSelector() {
  const form =
    document.querySelector(
      "#backtest-form"
    );

  if (!form) {
    return;
  }

  if (
    document.querySelector(
      "#asset-selector"
    )
  ) {
    return;
  }

  const symbolInput =
    form.elements.symbol;

  if (!symbolInput) {
    return;
  }

  let symbolContainer =
    symbolInput.closest(
      ".field"
    );

  if (!symbolContainer) {
    symbolContainer =
      symbolInput.parentElement;
  }

  if (!symbolContainer) {
    return;
  }

  /*
   * Старое одиночное поле остаётся в DOM
   * для backward compatibility,
   * но пользователь его больше не видит.
   */
  symbolInput.value = "EURUSD";
  symbolInput.hidden = true;

  const oldLabel =
    symbolContainer.querySelector(
      "label"
    );

  if (oldLabel) {
    oldLabel.hidden = true;
  }

  const selector =
    document.createElement("div");

  selector.id =
    "asset-selector";

  selector.innerHTML = `
    <div
      style="
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        margin-bottom:10px;
      "
    >
      <label
        style="
          margin:0;
          text-transform:uppercase;
          font-size:11px;
        "
      >
        Assets
      </label>

      <div
        id="asset-selected-count"
        style="
          border:1px solid rgba(212,175,55,.35);
          padding:8px 12px;
          font-size:11px;
          color:var(--gold);
        "
      >
        0 selected
      </div>
    </div>

    <input
      id="asset-search"
      type="text"
      placeholder="Search EURUSD, XAUUSD, US100..."
      autocomplete="off"
      style="
        width:100%;
        margin-bottom:10px;
      "
    >

    <div
      style="
        display:flex;
        flex-wrap:wrap;
        gap:8px;
        margin-bottom:12px;
      "
    >
      <button
        type="button"
        class="asset-tab active"
        data-asset-group="forex"
      >
        FOREX
      </button>

      <button
        type="button"
        class="asset-tab"
        data-asset-group="indices"
      >
        INDICES
      </button>

      <button
        type="button"
        class="asset-tab"
        data-asset-group="metals"
      >
        METALS
      </button>

      <button
        type="button"
        class="asset-tab"
        data-asset-group="all"
      >
        ALL
      </button>

      <button
        type="button"
        id="asset-select-visible"
      >
        SELECT VISIBLE
      </button>

      <button
        type="button"
        id="asset-clear"
      >
        CLEAR
      </button>
    </div>

    <div
      id="asset-grid"
      style="
        display:grid;
        grid-template-columns:
          repeat(
            auto-fit,
            minmax(135px,1fr)
          );
        gap:7px;
        max-height:320px;
        overflow:auto;
        padding:10px;
        border:
          1px solid
          rgba(255,255,255,.08);
      "
    ></div>
  `;

  symbolContainer.appendChild(
    selector
  );

  /*
   * Minimal styles so selector works
   * even without additional CSS.
   */
  const style =
    document.createElement("style");

  style.textContent = `
    .asset-tab,
    #asset-select-visible,
    #asset-clear {
      background:#0f1419;
      color:#f4f1e9;
      border:1px solid rgba(255,255,255,.12);
      padding:9px 14px;
      cursor:pointer;
      font-size:10px;
      font-weight:700;
      letter-spacing:.04em;
    }

    .asset-tab.active {
      color:#e6bd29;
      border-color:#e6bd29;
    }

    .asset-chip {
      display:flex;
      align-items:center;
      gap:7px;
      min-height:34px;
      padding:8px 10px;
      border:
        1px solid
        rgba(255,255,255,.10);
      background:#0d1217;
      cursor:pointer;
      font-size:11px;
    }

    .asset-chip.selected {
      border-color:
        rgba(230,189,41,.65);
      background:
        rgba(230,189,41,.05);
    }

    .asset-chip input {
      margin:0;
    }

    .portfolio-asset-row {
      display:grid;
      grid-template-columns:
        100px 110px 1fr 220px;
      gap:12px;
      align-items:center;
      border-bottom:
        1px solid
        rgba(255,255,255,.08);
      padding:10px;
    }

    @media (max-width:900px) {
      .portfolio-asset-row {
        grid-template-columns:1fr;
      }
    }
  `;

  document.head.appendChild(
    style
  );

  bindAssetSelector();
  renderAssets();
}

function bindAssetSelector() {
  document
    .querySelectorAll(
      ".asset-tab"
    )
    .forEach((button) => {
      button.onclick = () => {
        document
          .querySelectorAll(
            ".asset-tab"
          )
          .forEach((other) =>
            other.classList.remove(
              "active"
            )
          );

        button.classList.add(
          "active"
        );

        assetGroup =
          button.dataset.assetGroup;

        renderAssets();
      };
    });

  document
    .querySelector(
      "#asset-search"
    )
    ?.addEventListener(
      "input",
      renderAssets
    );

  document
    .querySelector(
      "#asset-select-visible"
    )
    ?.addEventListener(
      "click",
      () => {
        visibleAssets().forEach(
          (symbol) =>
            selectedAssets.add(
              symbol
            )
        );

        renderAssets();
      }
    );

  document
    .querySelector(
      "#asset-clear"
    )
    ?.addEventListener(
      "click",
      () => {
        selectedAssets.clear();
        renderAssets();
      }
    );
}

function renderAssets() {
  const grid =
    document.querySelector(
      "#asset-grid"
    );

  if (!grid) {
    return;
  }

  grid.innerHTML =
    visibleAssets()
      .map(
        (symbol) => `
          <label
            class="
              asset-chip
              ${
                selectedAssets.has(
                  symbol
                )
                  ? "selected"
                  : ""
              }
            "
          >
            <input
              type="checkbox"
              value="${symbol}"
              ${
                selectedAssets.has(
                  symbol
                )
                  ? "checked"
                  : ""
              }
            >

            <span>
              ${symbol}
            </span>
          </label>
        `
      )
      .join("");

  grid
    .querySelectorAll("input")
    .forEach((input) => {
      input.onchange = () => {
        if (input.checked) {
          selectedAssets.add(
            input.value
          );
        } else {
          selectedAssets.delete(
            input.value
          );
        }

        renderAssets();
      };
    });

  const counter =
    document.querySelector(
      "#asset-selected-count"
    );

  if (counter) {
    counter.textContent =
      `${selectedAssets.size} selected`;
  }
}

/* =========================================================
   BACKTEST BODY
   ========================================================= */

function bodyFor(
  form,
  symbol
) {
  return {
    strategy_id:
      (
        window.activeStrategyId ||
        form.elements.strategy_id.value
      ).trim(),

    symbol,

    timeframe:
      form.elements.timeframe.value,

    date_from:
      form.elements.date_from.value,

    date_to:
      form.elements.date_to.value,

    starting_balance:
      +form.elements.starting_balance.value,

    spread_pips:
      +form.elements.spread_pips.value,

    commission_per_lot:
      +form.elements.commission_per_lot.value,

    slippage_pips:
      +form.elements.slippage_pips.value,
  };
}

/* =========================================================
   PORTFOLIO RESULTS UI
   ========================================================= */

function ensurePortfolioBox() {
  let box =
    document.querySelector(
      "#portfolio-backtest-summary"
    );

  if (box) {
    return box;
  }

  const form =
    document.querySelector(
      "#backtest-form"
    );

  if (!form) {
    return null;
  }

  box =
    document.createElement(
      "section"
    );

  box.id =
    "portfolio-backtest-summary";

  box.hidden = true;

  box.style.marginTop =
    "18px";

  box.style.border =
    "1px solid rgba(255,255,255,.10)";

  box.style.padding =
    "16px";

  box.innerHTML = `
    <div class="eyebrow">
      PORTFOLIO BACKTEST
    </div>

    <h3>
      Selected assets
    </h3>

    <div
      id="portfolio-backtest-rows"
    ></div>
  `;

  form.parentElement.appendChild(
    box
  );

  return box;
}

function rows(symbols) {
  const box =
    ensurePortfolioBox();

  if (!box) {
    return;
  }

  const rowContainer =
    box.querySelector(
      "#portfolio-backtest-rows"
    );

  box.hidden = false;

  rowContainer.innerHTML =
    symbols
      .map(
        (symbol) => `
          <div
            class="portfolio-asset-row"
            data-symbol="${symbol}"
          >
            <strong>
              ${symbol}
            </strong>

            <span class="state">
              WAITING
            </span>

            <span class="detail">
            </span>

            <span class="id">
            </span>
          </div>
        `
      )
      .join("");
}

function upd(
  symbol,
  state,
  detail = "",
  id = ""
) {
  const row =
    document.querySelector(
      `.portfolio-asset-row[data-symbol="${symbol}"]`
    );

  if (!row) {
    return;
  }

  row.querySelector(
    ".state"
  ).textContent = state;

  row.querySelector(
    ".detail"
  ).textContent = detail;

  row.querySelector(
    ".id"
  ).textContent = id;
}

/* =========================================================
   CREATE PORTFOLIO BACKTESTS
   ========================================================= */

document
  .querySelector(
    "#backtest-form"
  )
  ?.addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();

      const form =
        event.currentTarget;

      const strategyId =
        (
          window.activeStrategyId ||
          form.elements.strategy_id.value
        ).trim();

      const symbols =
        [...selectedAssets];

      if (!strategyId) {
        return M(
          "Create/approve a strategy first.",
          true
        );
      }

      if (!symbols.length) {
        return M(
          "Select at least one asset.",
          true
        );
      }

      if (
        !form.elements.date_from.value ||
        !form.elements.date_to.value
      ) {
        return M(
          "Select backtest dates.",
          true
        );
      }

      activeBacktestIds = [];
      activeBacktestId = null;

      rows(symbols);

      for (
        let i = 0;
        i < symbols.length;
        i++
      ) {
        const symbol =
          symbols[i];

        try {
          M(
            `Creating ${i + 1}/${symbols.length}: ${symbol}`
          );

          const job =
            await B(
              "/api/backtests",
              {
                method: "POST",

                body:
                  JSON.stringify(
                    bodyFor(
                      form,
                      symbol
                    )
                  ),
              }
            );

          activeBacktestIds.push({
            symbol,
            backtest_id:
              job.backtest_id,
          });

          activeBacktestId =
            job.backtest_id;

          upd(
            symbol,
            job.status ||
              "QUEUED",
            "Ready",
            job.backtest_id
          );
        } catch (error) {
          upd(
            symbol,
            "FAILED",
            error.message
          );
        }
      }

      M(
        `Created ${activeBacktestIds.length}/${symbols.length}. Press Run selected assets.`
      );
    }
  );

/* =========================================================
   RUN PORTFOLIO
   ========================================================= */

const runButton =
  document.querySelector(
    "#run-backtest"
  );

if (runButton) {
  runButton.textContent =
    "RUN SELECTED ASSETS";

  runButton.addEventListener(
    "click",
    async () => {
      if (
        !activeBacktestIds.length
      ) {
        return M(
          "Create selected backtests first.",
          true
        );
      }

      let completed = 0;
      let failed = 0;
      let last = null;

      for (
        let i = 0;
        i <
        activeBacktestIds.length;
        i++
      ) {
        const item =
          activeBacktestIds[i];

        try {
          M(
            `Running ${i + 1}/${activeBacktestIds.length}: ${item.symbol}`
          );

          upd(
            item.symbol,
            "RUNNING",
            "Historical test in progress",
            item.backtest_id
          );

          const job =
            await B(
              `/api/backtests/${item.backtest_id}/run`,
              {
                method: "POST",
                body: "{}",
              }
            );

          last = job;

          const metrics =
            job.result?.metrics ||
            {};

          upd(
            item.symbol,
            job.status ||
              "COMPLETED",
            `Trades ${metrics.trades ?? "—"} · WR ${metrics.win_rate ?? "—"} · Net R ${metrics.net_r ?? "—"} · PF ${metrics.profit_factor ?? "—"}`,
            item.backtest_id
          );

          completed++;
        } catch (error) {
          failed++;

          upd(
            item.symbol,
            "FAILED",
            error.message,
            item.backtest_id
          );
        }
      }

      if (last) {
        R(last);
      }

      M(
        `Finished: ${completed} completed, ${failed} failed.`
      );
    }
  );
}

/* =========================================================
   STRATEGY ID FROM URL
   ========================================================= */

const queryStrategyId =
  new URLSearchParams(
    location.search
  ).get("strategy_id");

if (queryStrategyId) {
  const input =
    document.querySelector(
      '#backtest-form [name="strategy_id"]'
    );

  if (input) {
    input.value =
      queryStrategyId;
  }
}

/* =========================================================
   INITIALIZE
   ========================================================= */

installAssetSelector();