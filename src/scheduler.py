import os
import signal
import time
from datetime import datetime

import holidays

from src.analyzer import analyze
from src.trader import buy, sell, get_holdings, get_balance
from src.logger import log_info, log_error, log_trade, log_signal

_running = True
_daily_loss = 0
_consecutive_losses = 0
MAX_CONSECUTIVE_LOSSES = 3


def _signal_handler(sig, frame):
    global _running
    log_info("종료 신호 수신. Graceful shutdown...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)

KR_HOLIDAYS = holidays.KR()


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date() in KR_HOLIDAYS:
        return False
    market_start = now.replace(hour=9, minute=10, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now <= market_end


def _check_circuit_breaker():
    global _daily_loss, _consecutive_losses
    max_daily_loss = float(os.getenv("MAX_BUY_AMOUNT", 500000)) * 0.1  # 일일 최대손실 10%

    if abs(_daily_loss) >= max_daily_loss:
        log_error(f"서킷 브레이커 발동: 일일 손실 {_daily_loss:,.0f}원 (한도: {max_daily_loss:,.0f}원)")
        return True
    if _consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        log_error(f"서킷 브레이커 발동: 연속 손실 {_consecutive_losses}회")
        return True
    return False


def _check_holdings():
    global _daily_loss, _consecutive_losses
    holdings = get_holdings()
    for h in holdings:
        result = analyze(h["stock_code"], avg_price=h["avg_price"])
        log_signal(h["stock_code"], result["signal"], result["current_price"], result["reason"])

        if result["signal"] == "SELL":
            try:
                sell(h["stock_code"], h["quantity"])
                pnl = h["profit_loss"]
                _daily_loss += pnl
                if pnl < 0:
                    _consecutive_losses += 1
                else:
                    _consecutive_losses = 0
                log_trade(
                    h["stock_code"], "SELL", result["current_price"],
                    h["quantity"], result["current_price"] * h["quantity"],
                    result["reason"],
                )
            except Exception as e:
                log_error(f"매도 주문 실패 [{h['stock_code']}]: {e}")


def _check_targets():
    global _daily_loss, _consecutive_losses
    target_stocks = os.getenv("TARGET_STOCKS", "").split(",")
    max_buy = int(os.getenv("MAX_BUY_AMOUNT", 500000))

    holdings_codes = {h["stock_code"] for h in get_holdings()}
    balance = get_balance()

    for code in target_stocks:
        code = code.strip()
        if not code:
            continue
        if code in holdings_codes:
            continue
        if balance["cash"] < max_buy:
            log_info(f"매수 가능 현금 부족: {balance['cash']:,}원 < {max_buy:,}원")
            break

        result = analyze(code)
        log_signal(code, result["signal"], result["current_price"], result["reason"])

        if result["signal"] == "BUY":
            try:
                buy(code, max_buy, result["current_price"])
                qty = max_buy // result["current_price"]
                log_trade(
                    code, "BUY", result["current_price"],
                    qty, result["current_price"] * qty,
                    result["reason"],
                )
            except Exception as e:
                log_error(f"매수 주문 실패 [{code}]: {e}")


def run_loop(interval_sec=300):
    global _running, _daily_loss, _consecutive_losses
    _daily_loss = 0
    _consecutive_losses = 0

    log_info(f"=== 자동매매 시작 (MODE: {os.getenv('MODE', 'mock')}) ===")
    log_info(f"감시 종목: {os.getenv('TARGET_STOCKS', '')}")
    log_info(f"매수 한도: {os.getenv('MAX_BUY_AMOUNT', '500000')}원")
    log_info(f"실행 간격: {interval_sec}초")

    while _running:
        if not is_market_open():
            now = datetime.now()
            if now.hour < 9 or (now.hour == 9 and now.minute < 10):
                log_info("장 시작 전 대기 중...")
            elif now.hour >= 15 and now.minute > 30:
                log_info("장 마감. 오늘 자동매매 종료.")
                break
            else:
                log_info("장외 시간 대기 중...")
            time.sleep(60)
            continue

        if _check_circuit_breaker():
            log_info("서킷 브레이커 발동으로 거래 중단.")
            break

        try:
            _check_holdings()
            _check_targets()
        except Exception as e:
            log_error(f"루프 실행 중 오류: {e}")

        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)

    log_info("=== 자동매매 종료 ===")
