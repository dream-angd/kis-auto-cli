import json
import signal
import time
from datetime import date, datetime

import holidays

from src import config
from src.analyzer import analyze
from src.trader import buy, sell, get_account_info
from src.logger import log_info, log_error, log_trade, log_signal

KR_HOLIDAYS = holidays.KR()


def _load_state() -> dict:
    """오늘 날짜 기준으로 상태를 로드한다. 날짜 불일치·파일 없음·파싱 오류 시 초기화."""
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
    """상태를 파일에 저장한다. 디렉토리가 없으면 생성한다."""
    path = config.get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date() in KR_HOLIDAYS:
        return False
    market_start = now.replace(hour=9, minute=10, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now <= market_end


def _check_holdings(holdings, state):
    for h in holdings:
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
                    h["stock_code"], "SELL", result["current_price"],
                    h["quantity"], result["current_price"] * h["quantity"],
                    result["reason"],
                )
            except Exception as e:
                log_error(f"매도 주문 실패 [{h['stock_code']}]: {e}")


def _check_targets(holdings, balance, state):
    target_stocks = config.get_target_stocks()
    max_buy = config.get_max_buy_amount()
    available_cash = balance["cash"]

    holdings_codes = {h["stock_code"] for h in holdings}

    for code in target_stocks:
        if code in holdings_codes:
            continue
        if available_cash < max_buy:
            log_info(f"매수 가능 현금 부족: {available_cash:,}원 < {max_buy:,}원")
            break

        result = analyze(code)
        log_signal(code, result["signal"], result["current_price"], result["reason"])

        if result["signal"] == "BUY":
            try:
                order = buy(code, max_buy, result["current_price"])
                qty = order.get("_qty", max_buy // result["current_price"])
                available_cash -= qty * result["current_price"]
                log_trade(
                    code, "BUY", result["current_price"],
                    qty, result["current_price"] * qty,
                    result["reason"],
                )
            except Exception as e:
                log_error(f"매수 주문 실패 [{code}]: {e}")


def _check_circuit_breaker(state):
    max_daily_loss = config.get_max_daily_loss()
    max_consecutive = config.get_max_consecutive_losses()

    if abs(state["daily_loss"]) >= max_daily_loss:
        log_error(f"서킷 브레이커 발동: 일일 손실 {state['daily_loss']:,.0f}원 (한도: {max_daily_loss:,.0f}원)")
        return True
    if state["consecutive_losses"] >= max_consecutive:
        log_error(f"서킷 브레이커 발동: 연속 손실 {state['consecutive_losses']}회")
        return True
    return False


def run_loop(interval_sec=300):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("종료 신호 수신. Graceful shutdown...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)
    state = _load_state()

    log_info(f"=== 자동매매 시작 (MODE: {config.get_mode()}) ===")
    log_info(f"감시 종목: {','.join(config.get_target_stocks())}")
    log_info(f"매수 한도: {config.get_max_buy_amount()}원")
    log_info(f"실행 간격: {interval_sec}초")

    try:
        while running:
            if not is_market_open():
                now = datetime.now()
                if now.hour < 9 or (now.hour == 9 and now.minute < 10):
                    log_info("장 시작 전 대기 중...")
                elif now.hour > 15 or (now.hour == 15 and now.minute >= 30):
                    log_info("장 마감. 오늘 자동매매 종료.")
                    break
                else:
                    log_info("장외 시간 대기 중...")
                time.sleep(60)
                continue

            if _check_circuit_breaker(state):
                log_info("서킷 브레이커 발동으로 거래 중단.")
                break

            try:
                balance, holdings = get_account_info()
                _check_holdings(holdings, state)
                _check_targets(holdings, balance, state)
            except Exception as e:
                log_error(f"루프 실행 중 오류: {e}")

            for _ in range(interval_sec):
                if not running:
                    break
                time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== 자동매매 종료 ===")
