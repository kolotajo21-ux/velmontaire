let MY_STRATEGIES = [];
let MY_STRATEGIES_QUERY = "";
let MY_STRATEGIES_FILTER = "ACTIVE";
let MY_STRATEGIES_SORT = "UPDATED_DESC";

async function strategyLibraryApi(path, options = {}) {
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
    throw new Error("authentication_required");
  }

  if (!response.ok) {
    throw new Error(data.error || "request_failed");
  }

  return data;
}

function strategyEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function strategyDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function filteredStrategies() {
  let items = [...MY_STRATEGIES];

  if (MY_STRATEGIES_QUERY) {
    const q = MY_STRATEGIES_QUERY.toLowerCase();
    items = items.filter((strategy) =>
      String(strategy.name || "").toLowerCase().includes(q) ||
      String(strategy.strategy_id || "").toLowerCase().includes(q)
    );
  }

  if (MY_STRATEGIES_FILTER === "ACTIVE") {
    items = items.filter((strategy) => !strategy.archived);
  } else if (MY_STRATEGIES_FILTER === "ARCHIVED") {
    items = items.filter((strategy) => strategy.archived);
  } else if (MY_STRATEGIES_FILTER === "FAVORITES") {
    items = items.filter((strategy) => strategy.favorite && !strategy.archived);
  }

  const byUpdated = (a, b) =>
    new Date(a.updated_at || a.created_at || 0) - new Date(b.updated_at || b.created_at || 0);

  if (MY_STRATEGIES_SORT === "UPDATED_DESC") items.sort((a, b) => byUpdated(b, a));
  if (MY_STRATEGIES_SORT === "UPDATED_ASC") items.sort(byUpdated);
  if (MY_STRATEGIES_SORT === "NAME_ASC") items.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  if (MY_STRATEGIES_SORT === "NAME_DESC") items.sort((a, b) => String(b.name || "").localeCompare(String(a.name || "")));
  if (MY_STRATEGIES_SORT === "VERSIONS_DESC") items.sort((a, b) => Number(b.version_count || 0) - Number(a.version_count || 0));

  return items;
}

function renderMyStrategies() {
  const items = filteredStrategies();
  const grid = document.querySelector("#my-strategies-grid");
  const empty = document.querySelector("#my-strategies-empty");
  const total = document.querySelector("#my-strategies-count");
  const visible = document.querySelector("#my-strategies-visible-count");

  if (!grid || !empty || !total || !visible) return;

  total.textContent = String(MY_STRATEGIES.length);
  visible.textContent = String(items.length);

  empty.hidden = items.length !== 0;
  grid.hidden = items.length === 0;

  grid.innerHTML = items.map((strategy) => {
    const archived = !!strategy.archived;
    const favorite = !!strategy.favorite;

    return `
      <article class="strategy-library-card ${archived ? "archived-card" : ""}" data-strategy-id="${strategyEscape(strategy.strategy_id)}">
        <div class="strategy-card-top">
          <div class="strategy-title-wrap">
            <button
              class="strategy-favorite ${favorite ? "active" : ""}"
              data-action="favorite"
              data-id="${strategyEscape(strategy.strategy_id)}"
              data-favorite="${favorite ? "true" : "false"}"
              title="${favorite ? "Remove from favorites" : "Add to favorites"}"
              type="button"
              aria-label="${favorite ? "Remove from favorites" : "Add to favorites"}"
            >★</button>
            <div>
              <div class="eyebrow">${archived ? "Archived strategy" : "Saved strategy"}</div>
              <h2>${strategyEscape(strategy.name || "Untitled strategy")}</h2>
            </div>
          </div>

          <div class="strategy-card-badges">
            ${archived ? '<span class="strategy-state archived">ARCHIVED</span>' : ""}
            <span class="strategy-state ${strategy.has_schema ? "ready" : "draft"}">${strategy.has_schema ? "STRUCTURED" : "DRAFT"}</span>
          </div>
        </div>

        <p class="strategy-source-preview">${strategyEscape(strategy.active_source_text || "No source text available.")}</p>

        <div class="strategy-card-meta">
          <div><small>Active version</small><strong>v${strategyEscape(strategy.active_version_number ?? "—")}</strong></div>
          <div><small>Versions</small><strong>${strategyEscape(strategy.version_count ?? 0)}</strong></div>
          <div><small>Updated</small><strong>${strategyEscape(strategyDate(strategy.updated_at))}</strong></div>
        </div>

        <div class="strategy-id-line"><span>ID</span><code>${strategyEscape(strategy.strategy_id)}</code></div>

        <div class="strategy-card-actions">
          ${
            archived
              ? `<button class="btn gold" data-action="restore" data-id="${strategyEscape(strategy.strategy_id)}">Restore</button>`
              : `<button class="btn gold" data-action="open" data-id="${strategyEscape(strategy.strategy_id)}">Open</button>
                 <a class="btn" href="/dashboard/backtest?strategy_id=${encodeURIComponent(strategy.strategy_id)}">Backtest</a>`
          }
          <button class="btn" data-action="versions" data-id="${strategyEscape(strategy.strategy_id)}" data-name="${strategyEscape(strategy.name || "Strategy")}">Version history</button>
          <button class="btn strategy-more-button" data-action="manage" data-id="${strategyEscape(strategy.strategy_id)}" aria-label="Manage strategy">•••</button>
        </div>
      </article>
    `;
  }).join("");
}

async function loadMyStrategies() {
  const status = document.querySelector("#my-strategies-status");
  if (!status) return;

  status.style.color = "";
  status.textContent = "Loading strategies…";

  try {
    const data = await strategyLibraryApi("/api/strategies");
    MY_STRATEGIES = Array.isArray(data.strategies) ? data.strategies : [];
    renderMyStrategies();

    const activeCount = MY_STRATEGIES.filter((strategy) => !strategy.archived).length;
    const archivedCount = MY_STRATEGIES.length - activeCount;

    status.innerHTML = MY_STRATEGIES.length
      ? `<span>Active strategies:</span> ${activeCount} · <span>Archived strategies:</span> ${archivedCount}`
      : "No saved strategies yet.";
  } catch (error) {
    status.textContent = `Unable to load strategies: ${error.message}`;
    status.style.color = "var(--bad)";
  }
}

async function showVersionHistory(strategyId, strategyName) {
  const panel = document.querySelector("#strategy-version-panel");
  const list = document.querySelector("#strategy-version-list");
  const title = document.querySelector("#strategy-version-title");

  panel.hidden = false;
  title.textContent = `${strategyName} · Version History`;
  list.innerHTML = '<p class="status-line">Loading versions…</p>';
  panel.scrollIntoView({behavior: "smooth", block: "start"});

  try {
    const data = await strategyLibraryApi(`/api/strategies/${encodeURIComponent(strategyId)}/versions`);
    const versions = data.versions || [];

    list.innerHTML = versions.map((version) => `
      <article class="strategy-version-row ${version.active ? "active-version" : ""}">
        <div class="version-number"><small>VERSION</small><strong>v${strategyEscape(version.version_number)}</strong></div>
        <div class="version-content">
          <div>
            <strong>${version.active ? "ACTIVE VERSION" : "IMMUTABLE VERSION"}</strong>
            <span>${strategyEscape(strategyDate(version.created_at))}</span>
          </div>
          <p>${strategyEscape(version.source_text || "")}</p>
          <code>${strategyEscape(version.version_id)}</code>
        </div>
        <span class="strategy-state ${version.has_schema ? "ready" : "draft"}">${version.has_schema ? "STRUCTURED" : "DRAFT"}</span>
      </article>
    `).join("") || '<p class="status-line">No versions found.</p>';
  } catch (error) {
    list.innerHTML = `<p class="status-line" style="color:var(--bad)">${strategyEscape(error.message)}</p>`;
  }
}

function strategyById(strategyId) {
  return MY_STRATEGIES.find((strategy) => strategy.strategy_id === strategyId);
}

function closeStrategyModal() {
  const modal = document.querySelector("#strategy-library-modal");
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
}

function openStrategyModal({eyebrow = "Strategy action", title = "Strategy", html = ""}) {
  const modal = document.querySelector("#strategy-library-modal");
  const eyebrowNode = document.querySelector("#strategy-library-modal-eyebrow");
  const titleNode = document.querySelector("#strategy-library-modal-title");
  const body = document.querySelector("#strategy-library-modal-body");

  eyebrowNode.textContent = eyebrow;
  titleNode.textContent = title;
  body.innerHTML = html;
  modal.hidden = false;
  document.body.classList.add("modal-open");
}

function openManageModal(strategyId) {
  const strategy = strategyById(strategyId);
  if (!strategy) return;

  openStrategyModal({
    eyebrow: "Manage strategy",
    title: strategy.name || "Strategy",
    html: `
      <div class="strategy-manage-grid">
        <button class="strategy-manage-action" data-modal-action="rename" data-id="${strategyEscape(strategyId)}">
          <span>01</span><div><strong>Rename</strong><p>Change the library name. Strategy ID and immutable versions stay unchanged.</p></div>
        </button>

        <button class="strategy-manage-action" data-modal-action="duplicate" data-id="${strategyEscape(strategyId)}">
          <span>02</span><div><strong>Duplicate</strong><p>Create a separate strategy using the exact active source and compiled schema.</p></div>
        </button>

        <button class="strategy-manage-action" data-modal-action="${strategy.archived ? "restore" : "archive"}" data-id="${strategyEscape(strategyId)}">
          <span>03</span><div><strong>${strategy.archived ? "Restore" : "Archive"}</strong><p>${strategy.archived ? "Return this strategy to the active library." : "Hide this strategy from the active library without deleting history."}</p></div>
        </button>

        <button class="strategy-manage-action danger" data-modal-action="delete" data-id="${strategyEscape(strategyId)}">
          <span>04</span><div><strong>Delete permanently</strong><p>Allowed only when no backtests or bot instances depend on this strategy.</p></div>
        </button>
      </div>
    `,
  });
}

function openRenameModal(strategyId) {
  const strategy = strategyById(strategyId);
  if (!strategy) return;

  openStrategyModal({
    eyebrow: "Rename",
    title: strategy.name || "Strategy",
    html: `
      <form id="strategy-rename-form">
        <div class="field">
          <label>Strategy name</label>
          <input name="name" maxlength="120" required value="${strategyEscape(strategy.name || "")}">
        </div>
        <p class="sub">Renaming changes only the library name. Strategy ID and immutable version IDs remain unchanged.</p>
        <button class="btn gold" type="submit">Save name</button>
      </form>
    `,
  });

  document.querySelector("#strategy-rename-form").onsubmit = async (event) => {
    event.preventDefault();
    const name = event.currentTarget.elements.name.value.trim();

    try {
      await strategyLibraryApi(`/api/strategies/${encodeURIComponent(strategyId)}/rename`, {
        method: "POST",
        body: JSON.stringify({name}),
      });
      closeStrategyModal();
      await loadMyStrategies();
    } catch (error) {
      strategyModalError(error.message);
    }
  };
}

function openDeleteModal(strategyId) {
  const strategy = strategyById(strategyId);
  if (!strategy) return;

  openStrategyModal({
    eyebrow: "Permanent deletion",
    title: strategy.name || "Strategy",
    html: `
      <div class="strategy-danger-confirm">
        <strong>This cannot be undone.</strong>
        <p>VELMONTAIRE will refuse deletion if backtests or bot instances still reference this strategy.</p>
        <div class="field">
          <label>Type DELETE to confirm</label>
          <input id="strategy-delete-confirmation" autocomplete="off" placeholder="DELETE">
        </div>
        <button id="strategy-delete-confirm" class="btn danger-button" type="button" disabled>Delete permanently</button>
      </div>
    `,
  });

  const input = document.querySelector("#strategy-delete-confirmation");
  const button = document.querySelector("#strategy-delete-confirm");

  input.addEventListener("input", () => {
    button.disabled = input.value.trim() !== "DELETE";
  });

  button.addEventListener("click", async () => {
    try {
      await strategyLibraryApi(`/api/strategies/${encodeURIComponent(strategyId)}/delete`, {
        method: "POST",
        body: "{}",
      });
      closeStrategyModal();
      await loadMyStrategies();
    } catch (error) {
      strategyModalError(
        error.message.startsWith("strategy_delete_blocked:")
          ? "Deletion blocked because this strategy is already referenced by a backtest or bot. Archive it instead."
          : error.message
      );
    }
  });
}

function strategyModalError(message) {
  const body = document.querySelector("#strategy-library-modal-body");
  body.querySelector(".strategy-modal-error")?.remove();
  body.insertAdjacentHTML(
    "afterbegin",
    `<p class="strategy-modal-error">${strategyEscape(message)}</p>`
  );
}

async function strategyAction(strategyId, action, body = {}) {
  try {
    await strategyLibraryApi(`/api/strategies/${encodeURIComponent(strategyId)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    closeStrategyModal();
    await loadMyStrategies();
  } catch (error) {
    strategyModalError(error.message);
  }
}

document.querySelector("#my-strategies-grid")?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;

  const id = button.dataset.id;
  const action = button.dataset.action;

  if (action === "open") {
    location.href = `/dashboard/strategy?strategy_id=${encodeURIComponent(id)}`;
    return;
  }

  if (action === "backtest") {
    location.href = `/dashboard/backtest?strategy_id=${encodeURIComponent(id)}`;
    return;
  }

  if (action === "versions") {
    showVersionHistory(id, button.dataset.name || "Strategy");
    return;
  }

  if (action === "manage") {
    openManageModal(id);
    return;
  }

  if (action === "restore") {
    await strategyAction(id, "restore");
    return;
  }

  if (action === "favorite") {
    const favorite = button.dataset.favorite !== "true";

    // Keep the clicked card in place. Favorite is library metadata,
    // not a strategy-content update, so it should never reshuffle
    // "Recently updated" ordering.
    button.disabled = true;

    try {
      const result = await strategyLibraryApi(
        `/api/strategies/${encodeURIComponent(id)}/favorite`,
        {
          method: "POST",
          body: JSON.stringify({favorite}),
        }
      );

      const strategy = strategyById(id);
      if (strategy) {
        strategy.favorite = !!result.favorite;
      }

      renderMyStrategies();
    } catch (error) {
      const status = document.querySelector("#my-strategies-status");
      status.textContent = error.message;
      status.style.color = "var(--bad)";
    } finally {
      const currentButton = document.querySelector(
        `.strategy-favorite[data-id="${CSS.escape(id)}"]`
      );
      if (currentButton) currentButton.disabled = false;
    }
  }
});

document.querySelector("#strategy-library-modal")?.addEventListener("click", (event) => {
  if (event.target.closest("[data-modal-close]")) {
    closeStrategyModal();
    return;
  }

  const action = event.target.closest("[data-modal-action]");
  if (!action) return;

  const id = action.dataset.id;

  if (action.dataset.modalAction === "rename") openRenameModal(id);
  if (action.dataset.modalAction === "duplicate") strategyAction(id, "duplicate");
  if (action.dataset.modalAction === "archive") strategyAction(id, "archive");
  if (action.dataset.modalAction === "restore") strategyAction(id, "restore");
  if (action.dataset.modalAction === "delete") openDeleteModal(id);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeStrategyModal();
});

document.querySelector("#my-strategies-search")?.addEventListener("input", (event) => {
  MY_STRATEGIES_QUERY = event.currentTarget.value.trim();
  renderMyStrategies();
});

document.querySelector("#my-strategies-filter")?.addEventListener("change", (event) => {
  MY_STRATEGIES_FILTER = event.currentTarget.value;
  renderMyStrategies();
});

document.querySelector("#my-strategies-sort")?.addEventListener("change", (event) => {
  MY_STRATEGIES_SORT = event.currentTarget.value;
  renderMyStrategies();
});

document.querySelector("#my-strategies-refresh")?.addEventListener("click", loadMyStrategies);

document.querySelector("#strategy-version-close")?.addEventListener("click", () => {
  document.querySelector("#strategy-version-panel").hidden = true;
});

if (window.location.pathname.replace(/\/+$/, "") === "/dashboard/my-strategies") {
  loadMyStrategies();
}

