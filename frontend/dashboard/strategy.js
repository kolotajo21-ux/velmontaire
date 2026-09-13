let activeStrategyId = null;
let activeVersionId = null;

/*
 * Bridge для strategy_resume.js.
 * Позволяет безопасно обновлять внутренний контекст strategy.js.
 */
window.setActiveStrategyContext = function (
  strategyId,
  versionId = null
) {
  activeStrategyId =
    String(strategyId || "").trim() || null;

  activeVersionId =
    versionId
      ? String(versionId).trim()
      : null;
};


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

  const data =
    await response
      .json()
      .catch(() => ({}));

  if (response.status === 401) {
    window.location.replace("/login");

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


function setFlowStatus(
  text,
  error = false
) {
  const node =
    document.querySelector(
      "#strategy-status"
    );

  if (!node) {
    return;
  }

  node.textContent = text;

  node.style.color =
    error
      ? "#d6a4a4"
      : "var(--gold)";
}


/*
 * Только синхронизация внутри текущей страницы.
 *
 * Никакого localStorage/sessionStorage здесь нет.
 *
 * /dashboard/strategy
 * -> новая чистая стратегия
 *
 * /dashboard/strategy?strategy_id=...
 * -> существующую ТС открывает strategy_resume.js
 */
function syncBacktestStrategyId(
  strategyId
) {
  const value =
    String(
      strategyId || ""
    ).trim();

  if (!value) {
    return;
  }

  const input =
    document.querySelector(
      '#backtest-form input[name="strategy_id"]'
    );

  if (!input) {
    return;
  }

  input.value = value;

  input.dispatchEvent(
    new Event(
      "input",
      {
        bubbles: true,
      }
    )
  );

  input.dispatchEvent(
    new Event(
      "change",
      {
        bubbles: true,
      }
    )
  );
}


function clarificationItems(data) {
  /*
   * Новый backend contract:
   * question_items содержит точный parser path.
   */
  if (
    Array.isArray(
      data.question_items
    ) &&
    data.question_items.length
  ) {
    return data.question_items.map(
      (item) => ({
        question_id:
          item.question_id || "",

        path:
          item.path || "",

        question:
          item.question ||
          item.path ||
          "Clarification required",

        reason:
          item.reason || "",

        required:
          item.required !== false,
      })
    );
  }

  /*
   * Fallback для старого backend.
   *
   * Используем только unresolved:*.
   * conflict:* сюда намеренно не смешиваем.
   */
  const questions =
    Array.isArray(
      data.questions
    )
      ? data.questions
      : [];

  const unresolved =
    (
      Array.isArray(
        data.blockers
      )
        ? data.blockers
        : []
    )
      .filter((value) =>
        String(value).startsWith(
          "unresolved:"
        )
      )
      .map((value) =>
        String(value).slice(
          "unresolved:".length
        )
      );

  return questions.map(
    (question, index) => ({
      question_id: "",
      path:
        unresolved[index] ||
        "",
      question,
      reason: "",
      required: true,
    })
  );
}


const ENGLISH_CLARIFICATION_QUESTIONS = {
  "entry.side": "Which trade directions are allowed: LONG, SHORT, or both?",
  "entry.condition": "What exact condition must be met to enter a trade?",
  "stop_loss": "How should the stop loss be calculated?",
  "take_profit": "How should the take profit be calculated?",
  "entry.price": "How should the limit or stop entry price be calculated?",
};


function clarificationQuestion(item) {
  const language =
    localStorage.getItem("velmontaire_language") ||
    document.documentElement.lang ||
    "en";

  if (language.startsWith("en")) {
    return ENGLISH_CLARIFICATION_QUESTIONS[item.path] || item.question;
  }

  return item.question;
}


function clarificationAnswerControl(item, index) {
  const name = `answer_${index}`;
  const path = escapeHtml(item.path);

  if (item.path === "entry.side") {
    return `
      <select name="${name}" data-path="${path}" required>
        <option value="">Select direction</option>
        <option value="LONG">LONG only</option>
        <option value="SHORT">SHORT only</option>
        <option value="BOTH">LONG and SHORT</option>
      </select>
    `;
  }

  return `
    <input
      name="${name}"
      data-path="${path}"
      required
      placeholder="Your answer"
    >
  `;
}


function normalizedClarificationAnswer(item, rawValue) {
  const value = String(rawValue || "").trim();
  const upper = value.toUpperCase();

  if (item.path === "entry.side") {
    return upper;
  }

  if (item.path === "stop_loss") {
    const pips = upper.match(/(?:SL\s*)?(\d+(?:\.\d+)?)\s*PIPS?/);

    if (pips) {
      return {
        type: "FIXED_DISTANCE",
        value: Number(pips[1]),
        metadata: {unit: "PIPS"},
      };
    }

    if (/STRUCTURE|ORDER BLOCK|FVG/.test(upper)) {
      return {
        type: "STRUCTURE",
        value: null,
        metadata: {
          expression: value,
          source: "USER_CLARIFICATION",
        },
      };
    }
  }

  if (item.path === "take_profit") {
    const rr = upper.match(/(?:RR|R)\s*[:=@-]?\s*(\d+(?:\.\d+)?)/);

    if (rr) {
      return {
        type: "R_MULTIPLE",
        value: Number(rr[1]),
      };
    }

    const pips = upper.match(/(?:TP\s*)?(\d+(?:\.\d+)?)\s*PIPS?/);

    if (pips) {
      return {
        type: "FIXED_DISTANCE",
        value: Number(pips[1]),
        metadata: {unit: "PIPS"},
      };
    }
  }

  return value;
}


function renderClarification(data) {
  const box =
    document.querySelector(
      "#clarification-box"
    );

  if (!box) {
    return;
  }

  const items =
    clarificationItems(
      data || {}
    );

  /*
   * Все обязательные данные собраны.
   */
  if (data?.ready) {
    box.innerHTML = `
      <div class="eyebrow">
        Clarification complete
      </div>

      <p class="sub">
        A new immutable strategy version has been created.
        Human review is now required.
      </p>

      <button
        id="load-review"
        class="btn gold"
        type="button"
      >
        Open review
      </button>
    `;

    activeVersionId =
      data.persisted_version
        ?.version_id ||
      activeVersionId;

    syncBacktestStrategyId(
      activeStrategyId
    );

    const reviewButton =
      document.querySelector(
        "#load-review"
      );

    if (reviewButton) {
      reviewButton.onclick =
        loadReview;
    }

    return;
  }


  box.innerHTML = `
    <div class="eyebrow">
      Clarification required
    </div>

    <h3>
      ${items.length}
      question${
        items.length === 1
          ? ""
          : "s"
      }
    </h3>

    <p class="sub">
      Answer each item to complete the strategy schema.
      VELMONTAIRE will not guess missing execution rules.
    </p>

    <form id="clarification-form">

      ${items
        .map(
          (item, index) => `
            <div class="field">

              <label>
                ${escapeHtml(
                  clarificationQuestion(item)
                )}
              </label>

              ${clarificationAnswerControl(
                item,
                index
              )}

            </div>
          `
        )
        .join("")}

      <button
        class="btn gold"
        type="submit"
      >
        Submit answers
      </button>

    </form>
  `;


  const form =
    document.querySelector(
      "#clarification-form"
    );

  if (!form) {
    return;
  }


  form.onsubmit =
    async (event) => {
      event.preventDefault();

      if (!activeStrategyId) {
        setFlowStatus(
          "active_strategy_missing",
          true
        );

        return;
      }

      const answers = {};

      for (
        let index = 0;
        index < items.length;
        index++
      ) {
        const item =
          items[index];

        const input =
          event.currentTarget
            .elements[
              `answer_${index}`
            ];

        const value =
          String(
            input?.value || ""
          ).trim();


        /*
         * FAIL CLOSED.
         *
         * Без точного parser path
         * ответ не отправляем.
         */
        if (!item.path) {
          setFlowStatus(
            `Clarification path missing for: ${item.question}`,
            true
          );

          return;
        }


        if (!value) {
          setFlowStatus(
            `Answer required: ${item.question}`,
            true
          );

          return;
        }


        answers[
          item.path
        ] = normalizedClarificationAnswer(
          item,
          value
        );
      }


      try {
        const result =
          await api(
            `/api/strategies/${encodeURIComponent(
              activeStrategyId
            )}/clarification`,
            {
              method: "POST",

              body:
                JSON.stringify({
                  answers,
                }),
            }
          );

        const clarification =
          result.clarification ||
          {};

        setFlowStatus(
          clarification.ready
            ? "Clarification complete. Strategy compiled."
            : "Clarification answers saved."
        );

        renderClarification(
          clarification
        );

      } catch (error) {
        setFlowStatus(
          error.message,
          true
        );
      }
    };
}


async function loadReview() {
  if (!activeStrategyId) {
    setFlowStatus(
      "active_strategy_missing",
      true
    );

    return;
  }

  try {
    const result =
      await api(
        `/api/strategies/${encodeURIComponent(
          activeStrategyId
        )}/review`
      );

    const review =
      result.review || {};

    activeVersionId =
      review.version_id ||
      null;

    syncBacktestStrategyId(
      activeStrategyId
    );

    const unresolvedCount =
      (review.unresolved_items || []).length;
    const previewCard =
      document.querySelector(".unresolved-card");

    if (previewCard && unresolvedCount === 0) {
      const previewLabel = previewCard.querySelector("label");
      const previewInput = previewCard.querySelector("input");

      previewCard.classList.add("resolved-card");
      if (previewLabel) previewLabel.textContent = "Validation";
      if (previewInput) previewInput.value = "All rules resolved";
    }


    const box =
      document.querySelector(
        "#review-box"
      );

    if (!box) {
      return;
    }


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

      <p class="sub review-intro">
        Confirm the execution rules below before creating the immutable version.
      </p>

      <div class="review-summary-grid">
        ${reviewSummaryItems(review)}
      </div>

      <details class="review-technical">
        <summary>Technical schema JSON</summary>
        <div class="review-grid">
          ${reviewItem("Entry", review.entry)}
          ${reviewItem("Filters", review.filters)}
          ${reviewItem("Stop Loss", review.stop_loss)}
          ${reviewItem("Take Profit", review.take_profit)}
          ${reviewItem("Risk", review.risk)}
          ${reviewItem("Management", review.management)}
        </div>
      </details>

      <div class="review-approval-bar">
        <div>
          <small>Validation status</small>
          <strong>${unresolvedCount === 0 ? "All required rules resolved" : `${unresolvedCount} unresolved rule(s)`}</strong>
        </div>
        <button
          id="approve-version"
          class="btn gold"
          type="button"
        >
          Approve exact version
        </button>
      </div>
    `;


    const approveButton =
      document.querySelector(
        "#approve-version"
      );

    if (approveButton) {
      approveButton.onclick =
        approveVersion;
    }

  } catch (error) {
    setFlowStatus(
      error.message,
      true
    );
  }
}


async function approveVersion() {
  if (!activeStrategyId) {
    setFlowStatus(
      "active_strategy_missing",
      true
    );

    return;
  }

  if (!activeVersionId) {
    setFlowStatus(
      "active_version_missing",
      true
    );

    return;
  }


  try {
    await api(
      `/api/strategies/${encodeURIComponent(
        activeStrategyId
      )}/approve`,
      {
        method: "POST",

        body:
          JSON.stringify({
            version_id:
              activeVersionId,
          }),
      }
    );


    syncBacktestStrategyId(
      activeStrategyId
    );


    setFlowStatus(
      `Version ${activeVersionId} HUMAN APPROVED`
    );


    const reviewBox =
      document.querySelector(
        "#review-box"
      );

    if (reviewBox) {
      reviewBox.insertAdjacentHTML(
        "beforeend",
        `
          <p style="color:var(--gold)">
            ✓ Exact immutable version approved.
            Backtest/MT5 stages may now be unlocked
            by the product journey.
          </p>
        `
      );
    }

  } catch (error) {
    setFlowStatus(
      error.message,
      true
    );
  }
}


function reviewItem(
  label,
  value
) {
  return `
    <div class="review-item">

      <small>
        ${escapeHtml(label)}
      </small>

      <pre>${escapeHtml(
        JSON.stringify(
          value,
          null,
          2
        )
      )}</pre>

    </div>
  `;
}


function reviewSummaryItems(review) {
  const entryRules = Array.isArray(review.entry)
    ? review.entry
    : review.entry
      ? [review.entry]
      : [];
  const entry = entryRules[0] || {};
  const condition =
    entry.conditions?.description ||
    entry.condition?.description ||
    entry.description ||
    "Structured entry condition";
  const stopLoss = review.stop_loss || {};
  const takeProfit = review.take_profit || {};
  const risk = review.risk || {};
  const management = Array.isArray(review.management)
    ? review.management
    : review.management
      ? [review.management]
      : [];
  const filters = Array.isArray(review.filters)
    ? review.filters
    : review.filters
      ? [review.filters]
      : [];

  const stopExpression =
    stopLoss.metadata?.expression ||
    stopLoss.reference?.metadata?.expression ||
    stopLoss.reference?.field ||
    "Configured";
  const tpValue = takeProfit.type === "R_MULTIPLE"
    ? `${takeProfit.value ?? "—"}R`
    : takeProfit.value ?? "Configured";
  const riskValue = risk.value !== undefined && risk.value !== null
    ? `${risk.value}%`
    : "Configured";

  return [
    reviewSummaryItem("Entry", [
      ["Rules", entryRules.length || 1],
      ["Condition", condition],
    ]),
    reviewSummaryItem("Stop Loss", [
      ["Type", stopLoss.type || "STRUCTURE"],
      ["Reference", stopExpression],
    ]),
    reviewSummaryItem("Take Profit", [
      ["Type", takeProfit.type || "Configured"],
      ["Target", tpValue],
    ]),
    reviewSummaryItem("Risk", [
      ["Per trade", riskValue],
      ["Sizing", risk.sizing_type || "BALANCE_PERCENT"],
    ]),
    reviewSummaryItem("Management", [
      ["Rules", management.length],
      ["Status", management.length ? "Configured" : "No additional rules"],
    ]),
    reviewSummaryItem("Filters", [
      ["Rules", filters.length],
      ["Status", filters.length ? "Configured" : "No additional filters"],
    ]),
  ].join("");
}


function reviewSummaryItem(label, rows) {
  return `
    <article class="review-summary-card">
      <small>${escapeHtml(label)}</small>
      ${rows.map(([name, value]) => `
        <div>
          <span>${escapeHtml(name)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </article>
  `;
}


function escapeHtml(value) {
  return String(
    value ?? ""
  )
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
}


/*
 * CREATE NEW STRATEGY
 *
 * Эта форма используется только для новой стратегии.
 *
 * Существующие стратегии открываются через
 * strategy_resume.js по ?strategy_id=...
 */
document
  .querySelector(
    "#strategy-create-form"
  )
  ?.addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();


      const form =
        event.currentTarget;


      const name =
        String(
          form.elements
            .name
            ?.value || ""
        ).trim();


      const sourceText =
        String(
          form.elements
            .source_text
            ?.value || ""
        ).trim();


      if (!name) {
        setFlowStatus(
          "Strategy name is required.",
          true
        );

        return;
      }


      if (!sourceText) {
        setFlowStatus(
          "Trading rules are required.",
          true
        );

        return;
      }


      setFlowStatus(
        "Creating strategy…"
      );


      try {
        const result =
          await api(
            "/api/strategies",
            {
              method:
                "POST",

              body:
                JSON.stringify({
                  name,
                  source_text:
                    sourceText,
                }),
            }
          );


        activeStrategyId =
          result.strategy
            ?.strategy_id ||
          null;


        activeVersionId =
          result.clarification
            ?.persisted_version
            ?.version_id ||
          result.strategy
            ?.active_version_id ||
          null;


        if (!activeStrategyId) {
          throw new Error(
            "created_strategy_id_missing"
          );
        }


        syncBacktestStrategyId(
          activeStrategyId
        );


        setFlowStatus(
          `Strategy created · ${activeStrategyId}`
        );


        renderClarification(
          result.clarification ||
          {}
        );

      } catch (error) {
        setFlowStatus(
          error.message,
          true
        );
      }
    }
  );


/*
 * PUBLIC BRIDGE
 *
 * strategy_resume.js работает отдельным файлом,
 * поэтому нужные функции явно экспортируются.
 */
window.setFlowStatus =
  setFlowStatus;

window.renderClarification =
  renderClarification;

window.loadReview =
  loadReview;

window.approveVersion =
  approveVersion;

window.escapeHtml =
  escapeHtml;

window.syncBacktestStrategyId =
  syncBacktestStrategyId;


/*
 * ВАЖНО:
 *
 * Здесь специально НЕТ:
 *
 * localStorage.getItem(...)
 * sessionStorage.getItem(...)
 * автоматического loadSavedStrategy(...)
 *
 * Поэтому:
 *
 * /dashboard/strategy
 * -> чистая форма новой стратегии
 *
 * /dashboard/strategy?strategy_id=ABC
 * -> ABC загружает strategy_resume.js
 */
