import signal
import time
from datetime import datetime

from src import config
from src.logger import log_info
from src.scalper import ScalpMonitor
from src.scheduler import is_market_open, load_state, run_swing_cycle


def _market_closed_for_today():
    now = datetime.now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 30)


def _log_waiting_for_market():
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 10):
        log_info("Waiting for market open...")
    elif _market_closed_for_today():
        log_info("Market closed. Strategy finished for today.")
    else:
        log_info("Waiting outside market hours...")


def run_all_loop(swing_interval_sec=300, scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Combined strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    swing_state = load_state()
    scalp = ScalpMonitor(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()
    excluded_from_swing = {scalp.stock_code}

    log_info(f"=== Combined strategy started (MODE: {config.get_mode()}) ===")
    log_info(f"Swing interval: {swing_interval_sec}s")
    log_info(f"Scalp stock: {scalp.stock_code}")
    log_info(f"Scalp interval: {scalp_interval_sec}s")
    log_info(f"Scalp trade enabled: {config.is_scalp_trade_enabled()}")
    log_info(f"Swing excludes scalp stock: {','.join(excluded_from_swing)}")

    next_swing_at = 0
    next_scalp_at = 0

    try:
        while running:
            if not is_market_open():
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            now = time.time()

            if now >= next_swing_at:
                if not run_swing_cycle(swing_state, excluded_codes=excluded_from_swing):
                    break
                next_swing_at = now + swing_interval_sec

            if now >= next_scalp_at:
                scalp.run_once()
                next_scalp_at = now + scalp_interval_sec

            time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Combined strategy stopped ===")


def run_scalp_loop(scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Scalp strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    scalp = ScalpMonitor(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()

    log_info(f"=== Scalp strategy started (MODE: {config.get_mode()}) ===")
    log_info(f"Scalp stock: {scalp.stock_code}")
    log_info(f"Scalp interval: {scalp_interval_sec}s")
    log_info(f"Scalp trade enabled: {config.is_scalp_trade_enabled()}")

    try:
        while running:
            if not is_market_open():
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            scalp.run_once()
            end_sleep = time.time() + scalp_interval_sec
            while running and time.time() < end_sleep:
                time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Scalp strategy stopped ===")
