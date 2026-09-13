# ==========================
# MT5
# ==========================

MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_TIMEOUT = 120000


# ==========================
# SYMBOLS
# ==========================

SYMBOLS = [
    "CHFJPY",
    "CADCHF",
    "XAUUSD",
    "AUDJPY",
    
]

# Если понадобится тест только одного инструмента

SYMBOL = "EURUSD"


# ==========================
# TIMEFRAMES
# ==========================

D1_TIMEFRAME = "D1"
H4_TIMEFRAME = "H4"
M5_TIMEFRAME = "M5"


# ==========================
# HISTORY
# ==========================

D1_CANDLES = 400
H4_CANDLES = 800
M5_CANDLES = 3000


# ==========================
# STRUCTURE
# ==========================

SWING_LENGTH = 2

BOS_LOOKBACK = 20

MAX_OB_AGE = 120


# ==========================
# PROP ACCOUNT
# ==========================

PROP_FIRM = "FUNDINGPIPS"

# Варианты:
# "2_STEP_STANDARD"
# "2_STEP_PRO"
# "1_STEP"
# "2_STEP_FLEX"
# "ZERO"
PROP_MODEL = "2_STEP_STANDARD"

ACCOUNT_SIZE = 5000.0


# ==========================
# RISK PER TRADE
# ==========================

# Безопасный риск на одну сделку
RISK_PERCENT = 0.25

# Одновременно только одна сделка
MAX_SIMULTANEOUS_TRADES = 1

# Максимальный суммарный открытый риск
MAX_OPEN_RISK_PERCENT = 0.75

# Не больше сделок за день
MAX_TRADES_PER_DAY = 3

# После двух стопов бот прекращает торговлю до следующего дня
MAX_LOSSES_PER_DAY = 2


# ==========================
# INTERNAL SAFETY LIMITS
# ==========================

# Мы специально ставим лимиты ниже официальных
SOFT_DAILY_LOSS_PERCENT = 1.50
HARD_DAILY_LOSS_PERCENT = 2.00

SOFT_TOTAL_DRAWDOWN_PERCENT = 3.00
HARD_TOTAL_DRAWDOWN_PERCENT = 4.00

# После этой прибыли бот прекращает торговлю на день
DAILY_PROFIT_STOP_PERCENT = 1.00

# Минимальный запас до официального лимита
DRAWDOWN_SAFETY_BUFFER_PERCENT = 1.00


# ==========================
# TRADE PROTECTION
# ==========================

MINIMUM_RR = 2.0
MAXIMUM_RR = 3.0

BREAK_EVEN_TRIGGER_R = 1.0

# Запрет увеличивать риск после убытка
ALLOW_MARTINGALE = False

# Запрет усреднения убыточной позиции
ALLOW_AVERAGING_DOWN = False

# Запрет нескольких сделок одной торговой идеи
ALLOW_POSITION_STACKING = False


# ==========================
# NEWS PROTECTION
# ==========================

NEWS_FILTER_ENABLED = True

# Не открывать сделки за 15 минут до новости
NEWS_BLOCK_BEFORE_MINUTES = 15

# Не открывать сделки 15 минут после новости
NEWS_BLOCK_AFTER_MINUTES = 15

# Для Zero запрещено даже держать позицию во время новости
CLOSE_BEFORE_HIGH_IMPACT_NEWS = (
    PROP_MODEL == "ZERO"
)


# ==========================
# WEEKEND PROTECTION
# ==========================

WEEKEND_FILTER_ENABLED = True

# Не открывать новые сделки после этого времени в пятницу
FRIDAY_ENTRY_CUTOFF_HOUR = 17

# Принудительно закрывать перед выходными только для Zero
CLOSE_BEFORE_WEEKEND = (
    PROP_MODEL == "ZERO"
)


# ==========================
# DAILY RESET
# ==========================

# FundingPips использует время платформы
PLATFORM_TIMEZONE = "Europe/Kyiv"

DAILY_RESET_HOUR = 0

# ==========================
# EXECUTION
# ==========================

PENDING_EXPIRY_BARS = 24

BREAK_EVEN_TRIGGER_R = 1.0

INTRABAR_PRIORITY = "STOP_FIRST"

H1_CANDLES = 300