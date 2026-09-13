const DOCS_LANGUAGE_KEY = "velmontaire_language";

const DOCS_TRANSLATIONS = {
  ru: {
    "top.strong":"Официальная документация VELMONTAIRE.",
    "top.copy":"Продукт, настройка, runtime и безопасность.",
    "top.status":"Все системы работают",
    "nav.pricing":"Тарифы","nav.support":"Поддержка","nav.product":"Продукт","nav.workflow":"Как работает","nav.controls":"Контроль","nav.safety":"Безопасность","nav.docs":"Документация","nav.signin":"ВОЙТИ","nav.start":"НАЧАТЬ",
    "sidebar.title":"ДОКУМЕНТАЦИЯ","sidebar.overview":"Обзор","sidebar.quick":"Быстрый старт","sidebar.strategy":"Конструктор стратегии","sidebar.accounts":"Счёт и Prop Rules","sidebar.mt5":"Подключение MT5","sidebar.backtest":"Бэктест","sidebar.runtime":"PAPER → LIVE","sidebar.safety":"Безопасность и восстановление","sidebar.plans":"Тарифы","sidebar.trouble":"Решение проблем","sidebar.need":"Нужна помощь?","sidebar.support":"Открыть Support Center →",
    "overview.kicker":"ОФИЦИАЛЬНАЯ ДОКУМЕНТАЦИЯ","overview.title":"Документация продукта VELMONTAIRE","overview.copy":"Официальный справочник по созданию стратегии, подключению счёта, проверке и безопасному переходу от PAPER к LIVE.","overview.rule.title":"Главное правило продукта","overview.rule.copy":"Логика стратегии, правила счёта и право на исполнение разделены. Созданная стратегия не получает LIVE-доступ автоматически.",
    "quick.kicker":"БЫСТРЫЙ СТАРТ","quick.title":"Рекомендуемый порядок настройки","quick.copy":"Новому пользователю лучше пройти эти шаги именно в таком порядке — так настройки не будут разбросаны по платформе.","quick.1.title":"Выбери тариф","quick.1.copy":"CORE для создания/тестов. PRO для Prop + LIVE. ELITE для повышенных лимитов.","quick.2.title":"Выбери правила счёта","quick.2.copy":"Личный счёт, CFD Prop или Futures Prop.","quick.3.title":"Подключи MT5","quick.3.copy":"Используй данные именно того счёта, которым должен управлять VELMONTAIRE.","quick.4.title":"Создай стратегию","quick.4.copy":"Опиши → уточни → проверь → подтверди неизменяемую версию.","quick.5.title":"Бэктест","quick.5.copy":"Проверь точную версию до запуска runtime.","quick.6.title":"Сначала PAPER","quick.6.copy":"Проверь production-путь исполнения без LIVE-доступа.","quick.7.title":"Разреши LIVE","quick.7.copy":"Только после проверки подключения, версии стратегии и требований безопасности.",
    "strategy.kicker":"КОНСТРУКТОР СТРАТЕГИИ","strategy.title":"Обычный язык → структурированная стратегия","strategy.copy":"Опиши торговую систему обычным языком. VELMONTAIRE распознаёт известные концепты, заполняет настройки и задаёт вопросы там, где правило неясно или отсутствует.","strategy.known.title":"Известное правило","strategy.known.copy":"Например Order Block, FVG, CHOCH, liquidity sweep, RSI или EMA могут напрямую сопоставляться с существующими возможностями.","strategy.unknown.title":"Неизвестное / пользовательское правило","strategy.unknown.copy":"VELMONTAIRE должен спросить, когда именно условие считается истинным. Система не должна молча угадывать.","strategy.immutable.title":"Подтверждение создаёт неизменяемую версию","strategy.immutable.copy":"Если позже изменить подтверждённое правило, должна появиться новая версия стратегии, а не переписываться старая история.",
    "accounts.kicker":"СРЕДА СЧЁТА","accounts.title":"Личный счёт или Prop Firm","accounts.personal.title":"Личный счёт","accounts.personal.copy":"Выбирай Personal, если это обычный брокерский счёт без prop-ограничений по просадке, consistency или новостям.","accounts.prop.title":"Prop Firm счёт","accounts.prop.copy":"До исполнения выбери фирму, программу, фазу/этап и размер счёта. Эти ограничения относятся к политике счёта и не смешиваются с логикой стратегии.","accounts.prop.flow.title":"Для prop-счёта","accounts.flow.1":"Prop Firm","accounts.flow.2":"Программа","accounts.flow.3":"Фаза / этап","accounts.flow.4":"Размер счёта","accounts.flow.5":"Данные MT5",
    "mt5.kicker":"ПОДКЛЮЧЕНИЕ MT5","mt5.title":"Как пользователь подключает бота к своему счёту","mt5.copy":"Сайт не должен хранить пароль MetaTrader в браузере. Пользователь передаёт данные торгового счёта в серверный broker boundary.","mt5.field":"Поле","mt5.where":"Где взять","mt5.example":"Пример","mt5.login":"Логин MT5","mt5.login.where":"Кабинет брокера / prop-фирмы / данные счёта MT5","mt5.server":"Сервер MT5","mt5.server.where":"Должен точно совпадать с сервером брокера или prop-фирмы","mt5.password":"Торговый пароль","mt5.password.where":"Пароль, которому разрешена торговля на этом счёте","mt5.prop.title":"Подключение prop-счёта","mt5.prop.copy":"Используй MT5-данные именно того challenge или funded account. Не подключай другой MT5 при выбранной политике другого prop-счёта.","mt5.cta":"ОТКРЫТЬ ПОДКЛЮЧЕНИЕ MT5 →",
    "backtest.kicker":"БЭКТЕСТ","backtest.title":"Проверяй точную версию стратегии","backtest.copy":"Бэктест должен использовать конкретную неизменяемую версию стратегии плюс явные настройки инструмента, таймфрейма, дат, начального баланса, спреда, комиссии и проскальзывания.","backtest.c1":"Точная версия стратегии","backtest.c2":"Инструмент + таймфрейм","backtest.c3":"Диапазон дат","backtest.c4":"Спред / комиссия / проскальзывание","backtest.c5":"Equity curve + аудит сделок",
    "runtime.kicker":"RUNTIME","runtime.title":"PAPER перед LIVE","runtime.paper":"Запускает защищённый runtime без права на LIVE-исполнение. Используй его для проверки runtime до реальных денег.","runtime.live":"Требует явного разрешения и подтверждённых условий: версии стратегии, брокерского подключения и состояния безопасности.","runtime.warning.title":"LIVE — не автоматическое продолжение PAPER","runtime.warning.copy":"Runtime должен блокироваться, если разрешение, соединение или состояние восстановления не подтверждено.",
    "safety.kicker":"БЕЗОПАСНОСТЬ И ВОССТАНОВЛЕНИЕ","safety.title":"Что защищает production safety layer","safety.1.title":"Fail closed","safety.1.copy":"Неизвестное или неверное состояние блокирует новое исполнение вместо догадок.","safety.2.title":"Восстановление после сбоя","safety.2.copy":"Состояние можно восстановить из checkpoint и истории событий.","safety.3.title":"Защита от дублей","safety.3.copy":"Один и тот же рыночный input не должен продвигать последовательность дважды.",
    "plans.kicker":"ТАРИФЫ","plans.title":"Как понимать CORE, PRO и ELITE","plans.plan":"Тариф","plans.best":"Для чего лучше","plans.key":"Главное отличие","plans.core.best":"Создание и тестирование","plans.core.key":"Без Prop Rules и без LIVE","plans.pro.best":"Основной полный продукт","plans.pro.key":"Prop + LIVE + 3 брокера / 3 LIVE-бота","plans.elite.best":"Повышенные рабочие лимиты","plans.elite.key":"10 брокеров / 10 LIVE-ботов + priority support","plans.rule.title":"Простой выбор","plans.rule.copy":"Если нужен prop-счёт или LIVE — PRO является обычным стартовым тарифом. ELITE нужен в основном ради повышенных лимитов.",
    "trouble.kicker":"РЕШЕНИЕ ПРОБЛЕМ","trouble.title":"Частые проблемы","trouble.login.q":"Меня разлогинило. Бот всё ещё авторизован?","trouble.login.a":"Сессия сайта и LIVE-разрешение — разные сущности. Повторно войди, чтобы проверить текущее состояние runtime.","trouble.mt5.q":"MT5 test не проходит","trouble.mt5.a":"Проверь точный логин, написание сервера и торговый пароль. Для prop-счёта убедись, что используешь данные выбранного challenge/funded account.","trouble.prop.q":"Моей prop-фирмы нет в списке","trouble.prop.a":"Сначала выбери среду счёта. Если фирма или программа не поддерживается, отправь запрос через Capability Lab / Support, а не угадывай правила.","trouble.live.q":"LIVE не запускается","trouble.live.a":"Проверь подтверждение стратегии, MT5, доступ тарифа, явное подтверждение LIVE и состояние Safety. Если хоть одно условие неясно, LIVE должен оставаться заблокирован.","trouble.cta":"ОТКРЫТЬ SUPPORT CENTER →"
  },
  uk: {
    "top.strong":"Офіційна документація VELMONTAIRE.","top.copy":"Продукт, налаштування, runtime і безпека.","top.status":"Усі системи працюють",
    "nav.pricing":"Тарифи","nav.support":"Підтримка","nav.product":"Продукт","nav.workflow":"Як працює","nav.controls":"Контроль","nav.safety":"Безпека","nav.docs":"Документація","nav.signin":"УВІЙТИ","nav.start":"ПОЧАТИ",
    "sidebar.title":"ДОКУМЕНТАЦІЯ","sidebar.overview":"Огляд","sidebar.quick":"Швидкий старт","sidebar.strategy":"Конструктор стратегії","sidebar.accounts":"Рахунок і Prop Rules","sidebar.mt5":"Підключення MT5","sidebar.backtest":"Бектест","sidebar.runtime":"PAPER → LIVE","sidebar.safety":"Безпека та відновлення","sidebar.plans":"Тарифи","sidebar.trouble":"Вирішення проблем","sidebar.need":"Потрібна допомога?","sidebar.support":"Відкрити Support Center →",
    "overview.kicker":"ОФІЦІЙНА ДОКУМЕНТАЦІЯ","overview.title":"Документація продукту VELMONTAIRE","overview.copy":"Офіційний довідник зі створення стратегії, підключення рахунку, перевірки та безпечного переходу від PAPER до LIVE.","overview.rule.title":"Головне правило продукту","overview.rule.copy":"Логіка стратегії, правила рахунку та право на виконання розділені. Створена стратегія не отримує LIVE-доступ автоматично.",
    "quick.kicker":"ШВИДКИЙ СТАРТ","quick.title":"Рекомендований порядок налаштування","quick.copy":"Новому користувачу краще пройти ці кроки саме в такому порядку.","quick.1.title":"Обери тариф","quick.1.copy":"CORE для створення/тестів. PRO для Prop + LIVE. ELITE для підвищених лімітів.","quick.2.title":"Обери правила рахунку","quick.2.copy":"Особистий рахунок, CFD Prop або Futures Prop.","quick.3.title":"Підключи MT5","quick.3.copy":"Використовуй дані саме того рахунку, яким має керувати VELMONTAIRE.","quick.4.title":"Створи стратегію","quick.4.copy":"Опиши → уточни → перевір → підтвердь незмінну версію.","quick.5.title":"Бектест","quick.5.copy":"Перевір точну версію до запуску runtime.","quick.6.title":"Спочатку PAPER","quick.6.copy":"Перевір production-шлях виконання без LIVE-доступу.","quick.7.title":"Дозволь LIVE","quick.7.copy":"Лише після перевірки підключення, версії стратегії та вимог безпеки.",
    "strategy.kicker":"КОНСТРУКТОР СТРАТЕГІЇ","strategy.title":"Звичайна мова → структурована стратегія","strategy.copy":"Опиши торгову систему звичайною мовою. VELMONTAIRE розпізнає відомі концепти, заповнює налаштування та ставить питання там, де правило неясне.","strategy.known.title":"Відоме правило","strategy.known.copy":"Наприклад Order Block, FVG, CHOCH, liquidity sweep, RSI або EMA можуть напряму зіставлятися з існуючими можливостями.","strategy.unknown.title":"Невідоме / користувацьке правило","strategy.unknown.copy":"VELMONTAIRE має запитати, коли саме умова вважається істинною. Система не повинна мовчки вгадувати.","strategy.immutable.title":"Підтвердження створює незмінну версію","strategy.immutable.copy":"Якщо пізніше змінити підтверджене правило, має з’явитися нова версія стратегії.",
    "accounts.kicker":"СЕРЕДОВИЩЕ РАХУНКУ","accounts.title":"Особистий рахунок чи Prop Firm","accounts.personal.title":"Особистий рахунок","accounts.personal.copy":"Обирай Personal для звичайного брокерського рахунку без prop-обмежень.","accounts.prop.title":"Prop Firm рахунок","accounts.prop.copy":"До виконання обери фірму, програму, фазу/етап і розмір рахунку. Ці обмеження належать до політики рахунку.","accounts.prop.flow.title":"Для prop-рахунку","accounts.flow.1":"Prop Firm","accounts.flow.2":"Програма","accounts.flow.3":"Фаза / етап","accounts.flow.4":"Розмір рахунку","accounts.flow.5":"Дані MT5",
    "mt5.kicker":"ПІДКЛЮЧЕННЯ MT5","mt5.title":"Як користувач підключає бота до свого рахунку","mt5.copy":"Сайт не повинен зберігати пароль MetaTrader у браузері. Користувач передає дані торгового рахунку до серверного broker boundary.","mt5.field":"Поле","mt5.where":"Де взяти","mt5.example":"Приклад","mt5.login":"Логін MT5","mt5.login.where":"Кабінет брокера / prop-фірми / дані рахунку MT5","mt5.server":"Сервер MT5","mt5.server.where":"Має точно збігатися із сервером брокера або prop-фірми","mt5.password":"Торговий пароль","mt5.password.where":"Пароль, якому дозволена торгівля на цьому рахунку","mt5.prop.title":"Підключення prop-рахунку","mt5.prop.copy":"Використовуй MT5-дані саме того challenge або funded account.","mt5.cta":"ВІДКРИТИ ПІДКЛЮЧЕННЯ MT5 →",
    "backtest.kicker":"БЕКТЕСТ","backtest.title":"Перевіряй точну версію стратегії","backtest.copy":"Бектест має використовувати конкретну незмінну версію стратегії плюс явні налаштування інструмента, таймфрейму, дат, балансу, спреду, комісії та прослизання.","backtest.c1":"Точна версія стратегії","backtest.c2":"Інструмент + таймфрейм","backtest.c3":"Діапазон дат","backtest.c4":"Спред / комісія / прослизання","backtest.c5":"Equity curve + аудит угод",
    "runtime.kicker":"RUNTIME","runtime.title":"PAPER перед LIVE","runtime.paper":"Запускає захищений runtime без права на LIVE-виконання.","runtime.live":"Потребує явного дозволу та підтверджених умов: версії стратегії, брокерського підключення і стану безпеки.","runtime.warning.title":"LIVE — не автоматичне продовження PAPER","runtime.warning.copy":"Runtime має блокуватися, якщо дозвіл, з’єднання або стан відновлення не підтверджені.",
    "safety.kicker":"БЕЗПЕКА ТА ВІДНОВЛЕННЯ","safety.title":"Що захищає production safety layer","safety.1.title":"Fail closed","safety.1.copy":"Невідомий або неправильний стан блокує нове виконання замість припущень.","safety.2.title":"Відновлення після збою","safety.2.copy":"Стан можна відновити з checkpoint та історії подій.","safety.3.title":"Захист від дублів","safety.3.copy":"Один і той самий ринковий input не повинен просувати послідовність двічі.",
    "plans.kicker":"ТАРИФИ","plans.title":"Як розуміти CORE, PRO та ELITE","plans.plan":"Тариф","plans.best":"Для чого краще","plans.key":"Головна відмінність","plans.core.best":"Створення і тестування","plans.core.key":"Без Prop Rules і без LIVE","plans.pro.best":"Основний повний продукт","plans.pro.key":"Prop + LIVE + 3 брокери / 3 LIVE-боти","plans.elite.best":"Підвищені робочі ліміти","plans.elite.key":"10 брокерів / 10 LIVE-ботів + priority support","plans.rule.title":"Простий вибір","plans.rule.copy":"Якщо потрібен prop-рахунок або LIVE — PRO є звичайним стартовим тарифом. ELITE потрібен переважно для вищих лімітів.",
    "trouble.kicker":"ВИРІШЕННЯ ПРОБЛЕМ","trouble.title":"Поширені проблеми","trouble.login.q":"Мене розлогінило. Бот усе ще авторизований?","trouble.login.a":"Сесія сайту та LIVE-дозвіл — різні сутності. Увійди знову, щоб перевірити поточний стан runtime.","trouble.mt5.q":"MT5 test не проходить","trouble.mt5.a":"Перевір точний логін, написання сервера та торговий пароль.","trouble.prop.q":"Моєї prop-фірми немає у списку","trouble.prop.a":"Якщо фірма або програма не підтримується, надішли запит через Capability Lab / Support, а не вгадуй правила.","trouble.live.q":"LIVE не запускається","trouble.live.a":"Перевір підтвердження стратегії, MT5, доступ тарифу, явне підтвердження LIVE та стан Safety.","trouble.cta":"ВІДКРИТИ SUPPORT CENTER →"
  }
};

function setDocsLanguage(lang) {
  const language = ["en","ru","uk"].includes(lang) ? lang : "en";
  localStorage.setItem(DOCS_LANGUAGE_KEY, language);
  document.documentElement.lang = language === "uk" ? "uk" : language;

  const dictionary = DOCS_TRANSLATIONS[language] || {};
  document.querySelectorAll("[data-docs-i18n]").forEach((node) => {
    const key = node.dataset.docsI18n;
    if (language === "en") {
      if (!node.dataset.docsEnglish) node.dataset.docsEnglish = node.textContent;
      node.textContent = node.dataset.docsEnglish;
      return;
    }
    if (dictionary[key] !== undefined) node.textContent = dictionary[key];
  });

  const current = document.querySelector("#docs-language-current");
  if (current) current.textContent = language === "uk" ? "UA" : language.toUpperCase();

  document.querySelectorAll("[data-docs-language]").forEach((node) => {
    node.classList.toggle("active", node.dataset.docsLanguage === language);
  });
}

function initDocs() {
  document.querySelectorAll("[data-docs-i18n]").forEach((node) => {
    node.dataset.docsEnglish = node.textContent;
  });

  const saved = localStorage.getItem(DOCS_LANGUAGE_KEY);
  const browser = (navigator.language || "en").toLowerCase();
  const initial = saved || (browser.startsWith("ru") ? "ru" : browser.startsWith("uk") ? "uk" : "en");

  const button = document.querySelector("#docs-language-button");
  const menu = document.querySelector("#docs-language-menu");

  button?.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
    button.setAttribute("aria-expanded", String(!menu.hidden));
  });

  menu?.querySelectorAll("[data-docs-language]").forEach((option) => {
    option.addEventListener("click", () => {
      setDocsLanguage(option.dataset.docsLanguage);
      menu.hidden = true;
      button?.setAttribute("aria-expanded","false");
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("#docs-language-switcher") && menu) {
      menu.hidden = true;
      button?.setAttribute("aria-expanded","false");
    }
  });

  const sections = [...document.querySelectorAll(".docs-content section[id]")];
  const links = [...document.querySelectorAll(".docs-sidebar nav a")];

  const updateActive = () => {
    let currentId = sections[0]?.id;
    for (const section of sections) {
      if (section.getBoundingClientRect().top <= 180) currentId = section.id;
    }
    links.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${currentId}`));
  };

  window.addEventListener("scroll", updateActive, {passive:true});
  updateActive();
  setDocsLanguage(initial);
}

document.addEventListener("DOMContentLoaded", initDocs);
