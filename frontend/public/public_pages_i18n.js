const PUBLIC_PAGE_LANG_KEY = "velmontaire_language";

const PUBLIC_PAGE_TRANSLATIONS = {
  ru: {
    "Systematic trading infrastructure.":"Инфраструктура системного трейдинга.",
    "Built for traders who think in rules.":"Для трейдеров, которые работают по правилам.",
    "All Systems Operational":"Все системы работают",
    "Docs":"Документация","Pricing":"Тарифы","Support":"Поддержка",
    "Product":"Продукт","Workflow":"Как работает","Controls":"Контроль","Safety":"Безопасность","Resources":"Ресурсы",
    "SIGN IN":"ВОЙТИ","START BUILDING":"НАЧАТЬ",

    "What VELMONTAIRE actually does.":"Что на самом деле делает VELMONTAIRE.",
    "The product is a controlled path from trading idea to validated and executable strategy infrastructure.":"Продукт проводит торговую идею по контролируемому пути до проверенной и исполняемой стратегии.",
    "AI Strategy Builder":"AI-конструктор стратегии",
    "Describe rules in natural language, clarify ambiguity and compile a structured strategy version.":"Опиши правила обычным языком, уточни неоднозначности и создай структурированную версию стратегии.",
    "Build a strategy →":"Создать стратегию →",
    "Backtest":"Бэктест",
    "Validate an exact strategy version with historical data, costs, metrics and trade-level audit.":"Проверь точную версию стратегии на истории с учётом издержек, метрик и аудита каждой сделки.",
    "See workflow →":"Посмотреть процесс →",
    "PAPER → LIVE":"PAPER → LIVE",
    "Move through the same guarded runtime with explicit LIVE authorization only when prerequisites pass.":"Используй тот же защищённый runtime, а LIVE разрешай только после выполнения всех условий.",
    "See safety →":"Посмотреть безопасность →",

    "From an idea to controlled execution.":"От идеи до контролируемого исполнения.",
    "Each stage has one purpose. The user should always know what comes next.":"У каждого этапа одна задача. Пользователь всегда должен понимать, что делать дальше.",
    "Describe":"Опиши","Write the strategy in normal language.":"Напиши стратегию обычным языком.",
    "Clarify":"Уточни","VELMONTAIRE asks only where a rule is unresolved or ambiguous.":"VELMONTAIRE задаёт вопросы только там, где правило не определено или неоднозначно.",
    "Compile":"Собери","Confirmed rules become an immutable structured strategy version.":"Подтверждённые правила превращаются в неизменяемую структурированную версию стратегии.",
    "Test the exact version using the selected market and cost assumptions.":"Проверь точную версию на выбранном рынке с заданными издержками.",
    "Connect account":"Подключи счёт","Choose personal or prop rules, then verify the exact MT5 account.":"Выбери личные или prop-правила и проверь именно тот MT5-счёт.",
    "Dry-run first. LIVE requires explicit authorization and safety checks.":"Сначала тестовый запуск. LIVE требует явного разрешения и проверок безопасности.",
    "Recommended order":"Рекомендуемый порядок",
    "Plan → Account Rules → MT5 → Strategy → Backtest → PAPER → LIVE":"Тариф → Правила счёта → MT5 → Стратегия → Бэктест → PAPER → LIVE",

    "Every important rule has a control surface.":"Для каждого важного правила есть отдельная настройка.",
    "Strategy logic, account policy and runtime safety are separated so they can be reviewed independently.":"Логика стратегии, правила счёта и безопасность runtime разделены и проверяются независимо.",
    "Strategy controls":"Настройки стратегии",
    "Market, symbol, timeframe, direction, entry, stop loss, take profit, sessions and position management remain structured and editable.":"Рынок, инструмент, таймфрейм, направление, вход, стоп, тейк, сессии и управление позицией остаются структурированными и редактируемыми.",
    "Account controls":"Настройки счёта",
    "Personal accounts use your risk policy. Prop accounts add server-owned firm, phase, drawdown, news and consistency constraints.":"Личные счета используют твою риск-политику. Prop-счета дополнительно получают правила фирмы, фазы, просадки, новостей и consistency.",
    "Runtime controls":"Контроль runtime",
    "Checkpointing, recovery, idempotency, fail-closed validation and explicit execution authority protect the production path.":"Checkpoint, восстановление, защита от дублей, fail-closed проверки и явное разрешение на исполнение защищают production-путь.",

    "Execution stops when the system cannot prove safety.":"Исполнение останавливается, если система не может подтвердить безопасность.",
    "The runtime prefers blocking an uncertain action over guessing.":"Runtime лучше заблокирует неопределённое действие, чем будет угадывать.",
    "Fail closed":"Fail closed",
    "If required information or runtime state is uncertain, new execution is blocked.":"Если важные данные или состояние runtime не подтверждены, новое исполнение блокируется.",
    "Crash recovery":"Восстановление после сбоя",
    "Runtime state, checkpoints and event journal can recover and reconcile after restart.":"Состояние runtime, checkpoints и журнал событий восстанавливаются и сверяются после перезапуска.",
    "No duplicate execution":"Нет двойного исполнения",
    "Duplicate bars and replayed market inputs do not advance the same sequence twice.":"Повторный бар или replay рыночных данных не продвигает одну последовательность дважды.",

    "Choose by what you need to do.":"Выбирай тариф по тому, что тебе реально нужно.",
    "The difference between plans is mainly execution access and operating limits — not hidden complexity.":"Главная разница между тарифами — доступ к исполнению и рабочие лимиты, а не скрытые функции.",
    "Build + test":"Создание + тесты",
    "For a trader who wants to create strategies, backtest them and run PAPER. No prop rules or LIVE execution.":"Для трейдера, который хочет создавать стратегии, делать бэктест и запускать PAPER. Без prop-правил и LIVE.",
    "Personal + Prop + LIVE":"Личный + Prop + LIVE",
    "The normal full product: prop rules, broker connections, LIVE bots and advanced analytics.":"Полный основной продукт: prop-правила, подключения брокеров, LIVE-боты и расширенная аналитика.",
    "Higher operating limits":"Повышенные лимиты",
    "Same full feature set as PRO, but designed for more strategies, brokers and simultaneous LIVE bots.":"Те же функции, что в PRO, но больше стратегий, брокеров и одновременно работающих LIVE-ботов.",
    "Build, backtest and PAPER.":"Создание, бэктест и PAPER.",
    "Build, backtest and PAPER":"Создание, бэктест и PAPER",
    "Full product for serious personal and prop trading.":"Полный продукт для серьёзной личной и prop-торговли.",
    "Higher limits for multi-account operation.":"Повышенные лимиты для работы с несколькими счетами.",
    "3 strategies":"3 стратегии","30 backtests / month":"30 бэктестов / месяц","PAPER trading":"PAPER-торговля",
    "No prop rules":"Без prop-правил","No LIVE execution":"Без LIVE",
    "15 strategies":"15 стратегий","150 backtests / month":"150 бэктестов / месяц","3 broker connections":"3 подключения брокера","3 active LIVE bots":"3 активных LIVE-бота","CFD + Futures Prop Rules":"CFD + Futures Prop Rules","Advanced analytics":"Расширенная аналитика",
    "50 strategies":"50 стратегий","500 backtests / month":"500 бэктестов / месяц","10 broker connections":"10 подключений брокера","10 active LIVE bots":"10 активных LIVE-ботов","All prop features":"Все prop-функции","Priority support":"Приоритетная поддержка",
    "CHOOSE CORE":"ВЫБРАТЬ CORE","CHOOSE PRO":"ВЫБРАТЬ PRO","CHOOSE ELITE":"ВЫБРАТЬ ELITE","RECOMMENDED":"РЕКОМЕНДУЕМ",
    "Simple rule":"Простое правило",
    "If you need Prop or LIVE — start with PRO. CORE is for building/testing. ELITE is mainly higher limits.":"Если нужен Prop или LIVE — начинай с PRO. CORE нужен для создания и тестов. ELITE — в основном повышенные лимиты.",

    "Everything useful in one place.":"Всё нужное в одном месте.",
    "Documentation, support and direct access to the workspace.":"Документация, поддержка и прямой доступ к рабочему пространству.",
    "Documentation":"Документация",
    "Product concepts, runtime flow and operator references.":"Описание продукта, runtime-процесса и справочник пользователя.",
    "Open docs →":"Открыть документацию →",
    "Support Center":"Центр поддержки",
    "Get help with account setup, MT5, billing, strategies or missing capabilities.":"Помощь с аккаунтом, MT5, тарифами, стратегиями и недостающими возможностями.",
    "Open support →":"Открыть поддержку →",
    "Workspace":"Рабочее пространство",
    "Authenticated strategy, broker, PAPER, LIVE, safety and billing tools.":"Стратегии, брокер, PAPER, LIVE, безопасность и тарифы после входа.",
    "Sign in →":"Войти →",

    "SUPPORT CENTER":"ЦЕНТР ПОДДЕРЖКИ",
    "Choose what you need help with.":"Выбери, с чем нужна помощь.",
    "Support should route you directly to the right part of the product instead of making you search.":"Поддержка должна сразу вести в нужный раздел продукта, а не заставлять искать.",
    "Account / Login":"Аккаунт / Вход",
    "Problems signing in, account access or session behavior.":"Проблемы со входом, доступом к аккаунту или сессией.",
    "MT5 Connection":"Подключение MT5",
    "Login, server, password, personal or prop account connection.":"Логин, сервер, пароль, подключение личного или prop-счёта.",
    "Plan / Billing":"Тариф / Оплата",
    "Choose a plan, check usage, entitlements or subscription status.":"Выбор тарифа, использование, доступные функции и статус подписки.",
    "Strategy Builder":"Конструктор стратегии",
    "Parser, clarification, review, strategy versions and backtests.":"Парсер, уточнения, проверка, версии стратегии и бэктесты.",
    "Runtime / Safety":"Runtime / Безопасность",
    "PAPER, LIVE, recovery, blocked entries or runtime state.":"PAPER, LIVE, восстановление, заблокированные входы и состояние runtime.",
    "Missing Capability":"Недостающая возможность",
    "Submit a rule or module that the platform does not support yet.":"Отправь правило или модуль, которого пока нет в платформе.",
    "HOW SUPPORT SHOULD WORK":"КАК ДОЛЖНА РАБОТАТЬ ПОДДЕРЖКА",
    "No hunting for a generic contact form.":"Не нужно искать общую форму обратной связи.",
    "Pick the problem type above. The link takes you directly to the relevant product surface. Missing functionality is submitted through Capability Lab so it enters the controlled request lifecycle.":"Выбери тип проблемы выше. Ссылка сразу откроет нужный раздел. Недостающие функции отправляются через Capability Lab и попадают в контролируемый процесс обработки запросов.",
    "SIGN IN TO WORKSPACE →":"ВОЙТИ В РАБОЧЕЕ ПРОСТРАНСТВО →"
  },

  uk: {
    "Systematic trading infrastructure.":"Інфраструктура системного трейдингу.",
    "Built for traders who think in rules.":"Для трейдерів, які працюють за правилами.",
    "All Systems Operational":"Усі системи працюють",
    "Docs":"Документація","Pricing":"Тарифи","Support":"Підтримка",
    "Product":"Продукт","Workflow":"Як працює","Controls":"Контроль","Safety":"Безпека","Resources":"Ресурси",
    "SIGN IN":"УВІЙТИ","START BUILDING":"ПОЧАТИ",
    "What VELMONTAIRE actually does.":"Що насправді робить VELMONTAIRE.",
    "The product is a controlled path from trading idea to validated and executable strategy infrastructure.":"Продукт проводить торгову ідею контрольованим шляхом до перевіреної та виконуваної стратегії.",
    "AI Strategy Builder":"AI-конструктор стратегії",
    "Describe rules in natural language, clarify ambiguity and compile a structured strategy version.":"Опиши правила звичайною мовою, уточни неоднозначності та створи структуровану версію стратегії.",
    "Build a strategy →":"Створити стратегію →","Backtest":"Бектест",
    "Validate an exact strategy version with historical data, costs, metrics and trade-level audit.":"Перевір точну версію стратегії на історії з урахуванням витрат, метрик та аудиту угод.",
    "See workflow →":"Переглянути процес →","PAPER → LIVE":"PAPER → LIVE",
    "Move through the same guarded runtime with explicit LIVE authorization only when prerequisites pass.":"Використовуй той самий захищений runtime, а LIVE дозволяй лише після виконання всіх умов.",
    "See safety →":"Переглянути безпеку →",

    "From an idea to controlled execution.":"Від ідеї до контрольованого виконання.",
    "Each stage has one purpose. The user should always know what comes next.":"Кожен етап має одну мету. Користувач завжди має розуміти, що далі.",
    "Describe":"Опиши","Write the strategy in normal language.":"Напиши стратегію звичайною мовою.",
    "Clarify":"Уточни","VELMONTAIRE asks only where a rule is unresolved or ambiguous.":"VELMONTAIRE ставить питання лише там, де правило невизначене або неоднозначне.",
    "Compile":"Збери","Confirmed rules become an immutable structured strategy version.":"Підтверджені правила стають незмінною структурованою версією стратегії.",
    "Connect account":"Підключи рахунок","Choose personal or prop rules, then verify the exact MT5 account.":"Обери особисті або prop-правила та перевір саме той MT5-рахунок.",
    "Recommended order":"Рекомендований порядок",
    "Plan → Account Rules → MT5 → Strategy → Backtest → PAPER → LIVE":"Тариф → Правила рахунку → MT5 → Стратегія → Бектест → PAPER → LIVE",

    "Every important rule has a control surface.":"Для кожного важливого правила є окреме налаштування.",
    "Strategy controls":"Налаштування стратегії","Account controls":"Налаштування рахунку","Runtime controls":"Контроль runtime",
    "Execution stops when the system cannot prove safety.":"Виконання зупиняється, якщо система не може підтвердити безпеку.",
    "The runtime prefers blocking an uncertain action over guessing.":"Runtime краще заблокує невизначену дію, ніж буде вгадувати.",
    "Crash recovery":"Відновлення після збою","No duplicate execution":"Немає подвійного виконання",

    "Choose by what you need to do.":"Обирай тариф за тим, що тобі реально потрібно.",
    "Build + test":"Створення + тести","Personal + Prop + LIVE":"Особистий + Prop + LIVE","Higher operating limits":"Підвищені ліміти",
    "Build, backtest and PAPER.":"Створення, бектест і PAPER.",
    "Full product for serious personal and prop trading.":"Повний продукт для серйозної особистої та prop-торгівлі.",
    "Higher limits for multi-account operation.":"Підвищені ліміти для роботи з кількома рахунками.",
    "CHOOSE CORE":"ОБРАТИ CORE","CHOOSE PRO":"ОБРАТИ PRO","CHOOSE ELITE":"ОБРАТИ ELITE","RECOMMENDED":"РЕКОМЕНДУЄМО",
    "Simple rule":"Просте правило",
    "If you need Prop or LIVE — start with PRO. CORE is for building/testing. ELITE is mainly higher limits.":"Якщо потрібен Prop або LIVE — починай з PRO. CORE потрібен для створення й тестів. ELITE — переважно підвищені ліміти.",

    "Everything useful in one place.":"Усе потрібне в одному місці.",
    "Documentation":"Документація","Open docs →":"Відкрити документацію →","Support Center":"Центр підтримки","Open support →":"Відкрити підтримку →","Workspace":"Робочий простір","Sign in →":"Увійти →",
    "SUPPORT CENTER":"ЦЕНТР ПІДТРИМКИ","Choose what you need help with.":"Обери, з чим потрібна допомога.",
    "Account / Login":"Акаунт / Вхід","MT5 Connection":"Підключення MT5","Plan / Billing":"Тариф / Оплата",
    "Strategy Builder":"Конструктор стратегії","Runtime / Safety":"Runtime / Безпека","Missing Capability":"Відсутня можливість",
    "HOW SUPPORT SHOULD WORK":"ЯК МАЄ ПРАЦЮВАТИ ПІДТРИМКА","No hunting for a generic contact form.":"Не потрібно шукати загальну форму зворотного зв’язку.",
    "SIGN IN TO WORKSPACE →":"УВІЙТИ В РОБОЧИЙ ПРОСТІР →"
  }
};

const PUBLIC_ORIGINAL_TEXT = new WeakMap();

function publicNormalize(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function translatePublicTextNode(node, lang) {
  const parent = node.parentElement;
  if (!parent || parent.closest("script,style,code,pre")) return;

  if (!PUBLIC_ORIGINAL_TEXT.has(node)) {
    const source = publicNormalize(node.nodeValue);
    if (source) PUBLIC_ORIGINAL_TEXT.set(node, source);
  }

  const source = PUBLIC_ORIGINAL_TEXT.get(node);
  if (!source) return;

  if (lang === "en") {
    const leading = /^\s*/.exec(node.nodeValue)?.[0] || "";
    const trailing = /\s*$/.exec(node.nodeValue)?.[0] || "";
    node.nodeValue = leading + source + trailing;
    return;
  }

  const translated = PUBLIC_PAGE_TRANSLATIONS[lang]?.[source];
  if (translated !== undefined) {
    const leading = /^\s*/.exec(node.nodeValue)?.[0] || "";
    const trailing = /\s*$/.exec(node.nodeValue)?.[0] || "";
    node.nodeValue = leading + translated + trailing;
  }
}

function translatePublicPage(lang) {
  const language = ["en","ru","uk"].includes(lang) ? lang : "en";
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    translatePublicTextNode(node, language);
    node = walker.nextNode();
  }
}

function initPublicSubpageTranslation() {
  document.querySelectorAll("body *").forEach((element) => {
    element.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const source = publicNormalize(node.nodeValue);
        if (source) PUBLIC_ORIGINAL_TEXT.set(node, source);
      }
    });
  });

  const saved = localStorage.getItem(PUBLIC_PAGE_LANG_KEY) || "en";
  setTimeout(() => translatePublicPage(saved), 0);

  document.querySelectorAll("[data-language]").forEach((option) => {
    option.addEventListener("click", () => {
      const lang = option.dataset.language;
      // Existing homepage language handler saves the same key.
      setTimeout(() => translatePublicPage(lang), 0);
    });
  });
}

document.addEventListener("DOMContentLoaded", initPublicSubpageTranslation);
