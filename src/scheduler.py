import json
import signal
import time
from datetime import date, datetime

import holidays

from src import config
from src.analyzer import analyze
from src.logger import log_error, log_info, log_signal, log_trade
from src.trader import buy, get_account_info, sell

KR_HOLIDAYS = holidays.KR()


def _load_state() -> dict:
    today = date.today().isoformat()
    path = config.get_state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return data
        except Exception:
            pass
    return {"date": today, "daily_loss": 0, "consecutive_losses": 0}


def _save_state(state: dict) -> None:
    path = config.get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    return _load_state()


def save_state(state: dict) -> None:
    _save_state(state)


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date() in KR_HOLIDAYS:
        return False
    market_start = now.replace(hour=9, minute=10, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now <= market_end


def _check_holdings(holdings, state, excluded_codes=None):
    excluded_codes = excluded_codes or set()
    for h in holdings:
        if h["stock_code"] in excluded_codes:
            continue

        result = analyze(h["stock_code"], avg_price=h["avg_price"])
        log_signal(h["stock_code"], result["signal"], result["current_price"], result["reason"])

        if result["signal"] == "SELL":
            try:
                sell(h["stock_code"], h["quantity"])
                pnl = (result["current_price"] - h["avg_price"]) * h["quantity"]
                state["daily_loss"] += pnl
                if pnl < 0:
                    state["consecutive_losses"] += 1
                else:
                    state["consecutive_losses"] = 0
                _save_state(state)
                log_trade(
                    h["stock_code"],
                    "SELL",
                    result["current_price"],
                    h["quantity"],
                    result["current_price"] * h["quantity"],
                    result["reason"],
                )
            except Exception as e:
                log_error(f"Swing sell failed [{h['stock_code']}]: {e}")


def _check_targets(holdings, balance, state, excluded_codes=None):
    excluded_codes = excluded_codes or set()
    target_stocks = config.get_target_stocks()
    max_buy = config.get_max_buy_amount()
    available_cash = balance["cash"]

    holdings_codes = {h["stock_code"] for h in holdings}

    for code in target_stocks:
        if code in excluded_codes:
            continue
        if code in holdings_codes:
            continue
        if available_cash < max_buy:
            log_info(f"Swing buy skipped: cash {available_cash:,} < {max_buy:,}")
            break

        result = analyze(code)
        log_signal(code, result["signal"], result["current_price"], result["reason"])

        if result["signal"] == "BUY":
            try:
                order = buy(code, max_buy, result["current_price"])
                qty = order.get("_qty", max_buy // result["current_price"])
                available_cash -= qty * result["current_price"]
                log_trade(
                    code,
                    "BUY",
                    result["current_price"],
                    qty,
                    result["current_price"] * qty,
                    result["reason"],
                )
            except Exception as e:
                log_error(f"Swing buy failed [{code}]: {e}")


def _check_circuit_breaker(state):
    max_daily_loss = config.get_max_daily_loss()
    max_consecutive = config.get_max_consecutive_losses()

    if abs(state["daily_loss"]) >= max_daily_loss:
        log_error(
            f"Circuit breaker: daily PnL {state['daily_loss']:,.0f}, "
            f"limit {max_daily_loss:,.0f}"
        )
        return True
    if state["consecutive_losses"] >= max_consecutive:
        log_error(f"Circuit breaker: consecutive losses {state['consecutive_losses']}")
        return True
    return False


def run_swing_cycle(state, excluded_codes=None):
    if _check_circuit_breaker(state):
        log_info("Swing strategy stopped by circuit breaker.")
        return False

    try:
        balance, holdings = get_account_info()
        _check_holdings(holdings, state, excluded_codes=excluded_codes)
        _check_targets(holdings, balance, state, excluded_codes=excluded_codes)
    except Exception as e:
        log_error(f"Swing cycle failed: {e}")
    return True


def _log_closed_market_message():
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 10):
        log_info("Waiting for market open...")
        return False
    if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
        log_info("Market closed. Auto trading finished for today.")
        return True
    log_info("Waiting outside market hours...")
    return False


def run_loop(interval_sec=300):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Graceful shutdown...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)
    state = _load_state()

    log_info(f"=== Swing strategy started (MODE: {config.get_mode()}) ===")
    log_info(f"Targets: {','.join(config.get_target_stocks())}")
    log_info(f"Max buy amount: {config.get_max_buy_amount()}")
    log_info(f"Interval: {interval_sec}s")

    try:
        while running:
            if not is_market_open():
                if _log_closed_market_message():
                    break
                time.sleep(60)
                continue

            if not run_swing_cycle(state):
                break

            for _ in range(interval_sec):
                if not running:
                    break
                time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Swing strategy stopped ===")
