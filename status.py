from logs.logger import info


def print_status(
    symbol,
    h1,
    stage,
    balance,
    risk,
    auto_trade,
):
    info("===================================")
    info("SMC BOT STATUS")
    info(f"Symbol: {symbol}")
    info(f"H1 Trend: {h1}")
    info(f"Stage: {stage}")
    info(f"Balance: ${balance}")
    info(f"Risk: {risk}%")
    info(f"AutoTrade: {auto_trade}")
    info("===================================")