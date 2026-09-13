(function () {
  "use strict";

  function isStrategyPage() {
    return (
      location.pathname.replace(/\/+$/, "") ===
      "/dashboard/strategy"
    );
  }

  function currentStrategyId() {
    /*
     * Единственный допустимый источник для открытия
     * сохранённой стратегии — URL.
     *
     * Никакого localStorage/sessionStorage fallback.
     */
    return new URLSearchParams(
      location.search
    ).get("strategy_id");
  }

  async function request(
    path,
    options = {}
  ) {
    const response = await fetch(
      path,
      {
        credentials: "same-origin",
        cache: "no-store",
        ...options,

        headers: {
          "Content-Type":
            "application/json",

          ...(options.headers || {}),
        },
      }
    );

    const data =
      await response
        .json()
        .catch(() => ({}));

    if (response.status === 401) {
      location.replace("/login");

      throw new Error(
        "authentication_required"
      );
    }

    if (!response.ok) {
      throw new Error(
        data.error ||
        "request_failed"
      );
    }

    return data;
  }

  function status(
    text,
    error = false
  ) {
    if (
      typeof window.setFlowStatus ===
      "function"
    ) {
      window.setFlowStatus(
        text,
        error
      );

      return;
    }

    const node =
      document.querySelector(
        "#strategy-status"
      );

    if (!node) return;

    node.textContent = text;

    node.style.color =
      error
        ? "#d6a4a4"
        : "var(--gold)";
  }

  function setContext(
    strategyId,
    versionId = null
  ) {
    if (
      typeof window
        .setActiveStrategyContext !==
      "function"
    ) {
      throw new Error(
        "strategy_context_bridge_unavailable"
      );
    }

    window.setActiveStrategyContext(
      strategyId,
      versionId
    );
  }

  function setLoadedForm(
    strategy
  ) {
    const form =
      document.querySelector(
        "#strategy-create-form"
      );

    if (!form) return;

    if (form.elements.name) {
      form.elements.name.value =
        strategy.name || "";
    }

    if (form.elements.source_text) {
      form.elements.source_text.value =
        strategy.source_text || "";
    }

    const submit =
      form.querySelector(
        'button[type="submit"]'
      );

    if (!submit) return;

    /*
     * Сохранённая стратегия открыта явно.
     * Не разрешаем случайно создать duplicate
     * повторным нажатием основной кнопки.
     */
    submit.disabled = true;

    submit.title =
      "Existing strategy opened. Use My Strategies duplicate/edit actions to create a new strategy.";

    submit.textContent =
      "Saved strategy loaded";
  }

  async function loadExactReview(
    strategyId
  ) {
    const result =
      await request(
        `/api/strategies/${encodeURIComponent(
          strategyId
        )}/review`
      );

    const review =
      result.review || {};

    setContext(
      strategyId,
      review.version_id || null
    );

    /*
     * Use the canonical Human Review renderer from strategy.js.
     * This keeps newly-created and reopened strategies visually identical.
     */
    if (
      typeof window.loadReview ===
      "function"
    ) {
      await window.loadReview();
      return;
    }

    const box =
      document.querySelector(
        "#review-box"
      );

    if (!box) return;

    const escape =
      typeof window.escapeHtml ===
      "function"
        ? window.escapeHtml
        : (value) =>
            String(value ?? "")
              .replaceAll(
                "&",
                "&amp;"
              )
              .replaceAll(
                "<",
                "&lt;"
              )
              .replaceAll(
                ">",
                "&gt;"
              )
              .replaceAll(
                '"',
                "&quot;"
              );

    const reviewItem = (
      label,
      value
    ) => `
      <div class="review-item">
        <small>
          ${escape(label)}
        </small>

        <pre>${escape(
          JSON.stringify(
            value,
            null,
            2
          )
        )}</pre>
      </div>
    `;

    box.innerHTML = `
      <div class="eyebrow">
        Human review
      </div>

      <h3>
        Version ${
          review.version_number ??
          "—"
        }
      </h3>

      <div class="review-grid">

        ${reviewItem(
          "Entry",
          review.entry
        )}

        ${reviewItem(
          "Filters",
          review.filters
        )}

        ${reviewItem(
          "Stop Loss",
          review.stop_loss
        )}

        ${reviewItem(
          "Take Profit",
          review.take_profit
        )}

        ${reviewItem(
          "Risk",
          review.risk
        )}

        ${reviewItem(
          "Management",
          review.management
        )}

      </div>

      <p class="sub">
        Unresolved:
        ${
          (
            review.unresolved_items ||
            []
          ).length
        }
      </p>

      <button
        id="approve-version"
        class="btn gold"
        type="button"
      >
        Approve exact version
      </button>
    `;

    /*
     * approveVersion находится в strategy.js.
     * Контекст уже установлен через bridge.
     */
    const approveButton =
      document.querySelector(
        "#approve-version"
      );

    if (
      approveButton &&
      typeof window.approveVersion ===
        "function"
    ) {
      approveButton.onclick =
        window.approveVersion;
    }
  }

  async function resumeCompilation(
    strategyId
  ) {
    const button =
      document.querySelector(
        "#resume-strategy-compilation"
      );

    if (button) {
      button.disabled = true;
    }

    status(
      "Resuming strategy compilation…"
    );

    try {
      setContext(
        strategyId,
        null
      );

      const result =
        await request(
          `/api/strategies/${encodeURIComponent(
            strategyId
          )}/compile`,
          {
            method: "POST",
            body: "{}",
          }
        );

      const clarification =
        result.clarification || {};

      if (clarification.ready) {
        const versionId =
          clarification
            .persisted_version
            ?.version_id ||
          null;

        setContext(
          strategyId,
          versionId
        );

        status(
          "Strategy schema compiled."
        );

        await loadExactReview(
          strategyId
        );

        return;
      }

      if (
        typeof window
          .renderClarification !==
        "function"
      ) {
        throw new Error(
          "clarification_ui_unavailable"
        );
      }

      setContext(
        strategyId,
        null
      );

      window.renderClarification(
        clarification
      );

      status(
        "Clarification required before backtest."
      );
    } catch (error) {
      status(
        error.message,
        true
      );

      if (button) {
        button.disabled = false;
      }
    }
  }

  async function openSavedStrategy(
    strategyId
  ) {
    status(
      "Loading saved strategy…"
    );

    try {
      const detail =
        await request(
          `/api/strategies/${encodeURIComponent(
            strategyId
          )}`
        );

      const strategy =
        detail.strategy || {};

      if (
        !strategy.strategy_id
      ) {
        throw new Error(
          "saved_strategy_missing"
        );
      }

      /*
       * Никогда не доверяем чужому/другому ID
       * из payload вместо ID из маршрута.
       */
      if (
        String(
          strategy.strategy_id
        ) !==
        String(strategyId)
      ) {
        throw new Error(
          "saved_strategy_id_mismatch"
        );
      }

      setContext(
        strategyId,
        strategy.active_version_id ||
          null
      );

      setLoadedForm(
        strategy
      );

      status(
        `Saved strategy loaded · ${strategyId} · v${
          strategy
            .active_version_number ??
          "—"
        }`
      );

      if (strategy.has_schema) {
        await loadExactReview(
          strategyId
        );

        return;
      }

      const box =
        document.querySelector(
          "#review-box"
        );

      if (!box) return;

      box.innerHTML = `
        <div class="eyebrow">
          Saved draft
        </div>

        <h3>
          Compilation required
        </h3>

        <p class="sub">
          This saved strategy has no executable
          schema yet. Resume parsing and
          clarification before starting a
          backtest.
        </p>

        <button
          id="resume-strategy-compilation"
          class="btn gold"
          type="button"
        >
          Resume compilation
        </button>
      `;

      document
        .querySelector(
          "#resume-strategy-compilation"
        )
        ?.addEventListener(
          "click",
          () =>
            resumeCompilation(
              strategyId
            )
        );
    } catch (error) {
      status(
        error.message,
        true
      );
    }
  }

  document.addEventListener(
    "DOMContentLoaded",
    () => {
      if (!isStrategyPage()) {
        return;
      }

      const strategyId =
        currentStrategyId();

      /*
       * КЛЮЧЕВОЕ ПОВЕДЕНИЕ:
       *
       * /dashboard/strategy
       * -> НИЧЕГО не восстанавливаем.
       * -> чистая форма.
       *
       * /dashboard/strategy?strategy_id=ABC
       * -> открываем только ABC.
       */
      if (!strategyId) {
        return;
      }

      openSavedStrategy(
        strategyId
      );
    }
  );
})();
