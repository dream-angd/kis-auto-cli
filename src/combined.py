import signal
import threading
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


def _build_monitors(scalp_codes):
    """입력 종목 리스트로 ScalpMonitor 인스턴스를 만든다."""
    if isinstance(scalp_codes, str):
        scalp_codes = [c.strip() for c in scalp_codes.split(",") if c.strip()]
    if not scalp_codes:
        scalp_codes = config.get_scalp_stocks()
    if not scalp_codes:
        raise ValueError("스캘프 대상 종목이 없습니다. SCALP_STOCKS / SCALP_STOCK / TARGET_STOCKS 중 하나 설정 필요.")

    seen = []
    monitors = []
    for code in scalp_codes:
        if code in seen:
            continue
        seen.append(code)
        monitors.append(ScalpMonitor(code))
    return monitors


def _start_scalp_threads(monitors, interval_sec, stop_event):
    """각 monitor를 자기 thread에서 무한 run_loop 실행."""
    threads = []
    for m in monitors:
        t = threading.Thread(
            target=m.run_loop,
            args=(interval_sec, stop_event),
            name=f"scalp-{m.stock_code}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    return threads


def _stop_scalp_threads(threads, stop_event, timeout=5):
    stop_event.set()
    for t in threads:
        t.join(timeout=timeout)


def _format_heartbeat(monitors) -> str:
    parts = []
    for m in monitors:
        if m.last_price > 0:
            tag = "보유" if m._has_position() else "대기"
            parts.append(f"{m.display}={m.last_price:,}({tag})")
        else:
            parts.append(f"{m.display}=조회중")
    return "[scalp 상태] " + "  ".join(parts)


def run_all_loop(swing_interval_sec=300, scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Combined strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    swing_state = load_state()
    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()
    excluded_from_swing = {m.stock_code for m in monitors}

    swing_codes = [c for c in config.get_swing_stocks() if c not in excluded_from_swing]
    swing_codes_text = ", ".join(config.format_stock(c) for c in swing_codes) or "(없음)"
    scalp_codes_text = ", ".join(config.format_stock(m.stock_code) for m in monitors)

    log_info(f"=== 자동매매 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(f"Swing  → {swing_codes_text}  (5분마다 일봉 분석/매매)")
    log_info(f"Scalp  → {scalp_codes_text}  ({scalp_interval_sec}s 모멘텀 모니터링)")

    stop_event = threading.Event()
    scalp_threads = []
    next_swing_at = 0
    next_heartbeat_at = 0
    market_threads_active = False

    try:
        while running:
            if not is_market_open():
                if market_threads_active:
                    _stop_scalp_threads(scalp_threads, stop_event)
                    scalp_threads = []
                    market_threads_active = False
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            if not market_threads_active:
                stop_event = threading.Event()
                scalp_threads = _start_scalp_threads(monitors, scalp_interval_sec, stop_event)
                market_threads_active = True
                next_heartbeat_at = time.time() + config.get_heartbeat_interval_sec()

            now = time.time()
            if now >= next_swing_at:
                if not run_swing_cycle(swing_state, excluded_codes=excluded_from_swing):
                    break
                next_swing_at = now + swing_interval_sec

            if now >= next_heartbeat_at:
                log_info(_format_heartbeat(monitors))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Combined strategy stopped ===")


def run_scalp_loop(scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Scalp strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()

    scalp_codes_text = ", ".join(config.format_stock(m.stock_code) for m in monitors)
    log_info(f"=== Scalp 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(f"Scalp  → {scalp_codes_text}  ({scalp_interval_sec}s 모멘텀 모니터링)")

    stop_event = threading.Event()
    scalp_threads = []
    next_heartbeat_at = 0
    market_threads_active = False

    try:
        while running:
            if not is_market_open():
                if market_threads_active:
                    _stop_scalp_threads(scalp_threads, stop_event)
                    scalp_threads = []
                    market_threads_active = False
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            if not market_threads_active:
                stop_event = threading.Event()
                scalp_threads = _start_scalp_threads(monitors, scalp_interval_sec, stop_event)
                market_threads_active = True
                next_heartbeat_at = time.time() + config.get_heartbeat_interval_sec()

            now = time.time()
            if now >= next_heartbeat_at:
                log_info(_format_heartbeat(monitors))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Scalp strategy stopped ===")
