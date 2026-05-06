import json
import os
import time
from datetime import date, datetime

import holidays

from src import config, risk
from src.analyzer import analyze, calc_position_size
from src.logger import log_error, log_info, log_signal, log_trade
from src.signals import install_shutdown_handlers, restore_handlers
from src.trader import buy, get_account_info, sell

KR_HOLIDAYS = holidays.KR()


# 하위 호환: 기존 _load_state / _save_state 호출부가 동작하도록 risk.py로 위임.
# 새 코드는 src.risk를 직접 import해서 record_realized_pnl/is_daily_loss_limit_hit 사용 권장.
def _load_state() -> dict:
    return risk.load_state()


def _save_state(state: dict) -> None:
    risk.save_state(state)


def load_state() -> dict:
    return risk.load_state()


def save_state(state: dict) -> None:
    risk.save_state(state)


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date() in KR_HOLIDAYS:
        return False
    market_start = now.replace(hour=9, minute=10, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now <= market_end


def _calc_realized_pnl(avg_price: float, fill_price: float, qty: int) -> float:
    """매매 수수료 + 매도 거래세를 차감한 실현손익."""
    if qty <= 0:
        return 0.0
    gross = (fill_price - avg_price) * qty
    buy_fee = avg_price * qty * config.get_buy_fee_rate()
    sell_fee = fill_price * qty * config.get_sell_fee_rate()
    sell_tax = fill_price * qty * config.get_sell_tax_rate()
    return gross - buy_fee - sell_fee - sell_tax


def _annotate_reason(base_reason: str, order: dict, requested_qty: int) -> str:
    notes = [base_reason]
    if not order.get("fully_filled", True):
        notes.append(f"체결 {order['filled_qty']}/{requested_qty}")
    if order.get("estimated"):
        notes.append("체결조회 실패-추정")
    return " | ".join(notes)


def _check_holdings(holdings, state, excluded_codes=None):
    excluded_codes = excluded_codes or set()
    for h in holdings:
        if h["stock_code"] in excluded_codes:
            continue

        try:
            result = analyze(h["stock_code"], avg_price=h["avg_price"])
        except Exception as e:
            # 한 종목 분석 실패가 다른 종목 매매를 막지 않게 격리
            log_error(f"Swing analyze failed [{config.format_stock(h['stock_code'])}]: {e}")
            continue
        log_signal(h["stock_code"], result["signal"], result["current_price"], result["reason"])

        if result["signal"] != "SELL":
            continue

        try:
            order = sell(h["stock_code"], h["quantity"], current_price=result["current_price"])
        except Exception as e:
            log_error(f"Swing sell failed [{config.format_stock(h['stock_code'])}]: {e}")
            continue

        filled_qty = int(order.get("filled_qty", 0))
        fill_price = int(order.get("avg_fill_price", 0))
        if filled_qty <= 0 or fill_price <= 0:
            log_error(
                f"Swing sell unfilled [{config.format_stock(h['stock_code'])}]: ord={order.get('ord_qty')}, "
                f"filled={filled_qty}, odno={order.get('odno')}"
            )
            continue

        pnl = _calc_realized_pnl(h["avg_price"], fill_price, filled_qty)
        # risk.record_realized_pnl: daily_loss + wins/losses + consecutive_losses + trade_count 일괄 갱신
        risk.record_realized_pnl("swing", pnl)
        # 호출 측 state 인자 (run_swing_cycle에서 전달)도 최신 값으로 동기화
        state.update(risk.load_state())

        action = "SELL" if order.get("fully_filled") else "SELL_PARTIAL"
        log_trade(
            h["stock_code"],
            action,
            fill_price,
            filled_qty,
            int(fill_price * filled_qty),
            _annotate_reason(result["reason"], order, h["quantity"]),
            pnl=pnl,
        )


def _check_targets(holdings, balance, state, excluded_codes=None):
    excluded_codes = excluded_codes or set()
    target_stocks = config.get_swing_stocks()
    max_buy = config.get_swing_max_buy_amount()
    available_cash = balance["cash"]
    max_total_exposure = config.get_max_total_exposure()
    # 현재 노출 = 보유 종목 평가액 합 (swing+scalp 모두 포함)
    current_exposure = sum(int(h.get("current_price", 0)) * int(h.get("quantity", 0)) for h in holdings)

    holdings_codes = {h["stock_code"] for h in holdings}

    for code in target_stocks:
        if code in excluded_codes:
            continue
        if code in holdings_codes:
            continue
        if available_cash <= 0:
            break

        try:
            result = analyze(code)
        except Exception as e:
            # 한 종목 분석 실패가 다른 종목 매매를 막지 않게 격리
            log_error(f"Swing analyze failed [{config.format_stock(code)}]: {e}")
            continue

        if result["signal"] != "BUY":
            # 매수 후보의 BUY 외 신호(SELL/HOLD)는 보유 0이라 의미 없음.
            # 콘솔 노이즈 줄이기 위해 log_signal 호출 안 함 (raw_signals 파일에도 기록 안 됨).
            continue
        log_signal(code, result["signal"], result["current_price"], result["reason"])

        atr = result.get("atr", 0.0)
        qty = calc_position_size(result["current_price"], atr, max_buy)
        amount = qty * result["current_price"]
        if available_cash < amount:
            log_info(f"매수 가능 현금 부족: {available_cash:,}원 < {amount:,}원 (ATR={atr:.0f})")
            continue
        if max_total_exposure > 0 and current_exposure + amount > max_total_exposure:
            log_info(
                f"Swing buy skipped [{config.format_stock(code)}]: 노출 한도 초과 "
                f"(현재 {current_exposure:,} + 신규 {amount:,} > {max_total_exposure:,})"
            )
            continue

        try:
            order = buy(code, amount, result["current_price"])
        except Exception as e:
            log_error(f"Swing buy failed [{config.format_stock(code)}]: {e}")
            continue

        filled_qty = int(order.get("filled_qty", 0))
        fill_price = int(order.get("avg_fill_price", 0))
        if filled_qty <= 0 or fill_price <= 0:
            log_error(
                f"Swing buy unfilled [{config.format_stock(code)}]: ord={order.get('ord_qty')}, "
                f"filled={filled_qty}, odno={order.get('odno')}"
            )
            continue

        actual_amount = int(fill_price * filled_qty)
        buy_fee = int(actual_amount * config.get_buy_fee_rate())
        available_cash -= actual_amount + buy_fee

        action = "BUY" if order.get("fully_filled") else "BUY_PARTIAL"
        log_trade(
            code,
            action,
            fill_price,
            filled_qty,
            actual_amount,
            _annotate_reason(result["reason"], order, qty),
        )


def _check_circuit_breaker(state):
    max_daily_loss = config.get_max_daily_loss()
    max_consecutive = config.get_max_consecutive_losses()

    # daily_loss는 누적 실현손익(부호 보존). 손실 한도 초과는 음수 방향에서만 판정.
    if state["daily_loss"] <= -max_daily_loss:
        log_error(
            f"Circuit breaker: daily PnL {state['daily_loss']:,.0f}, "
            f"limit -{max_daily_loss:,.0f}"
        )
        return True
    if state["consecutive_losses"] >= max_consecutive:
        log_error(f"Circuit breaker: consecutive losses {state['consecutive_losses']}")
        return True
    return False


def _write_status() -> None:
    path = config.get_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "pid": os.getpid(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "mode": config.get_mode(),
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _clear_status() -> None:
    path = config.get_status_path()
    if path.exists():
        path.unlink()


def _snapshot_holdings_at_open() -> None:
    """장 시작 후 최초 보유 종목과 잔고를 start_snapshot_YYYYMMDD.json에 저장한다.

    API 오류 시 log_error 후 무시한다 (스냅샷 실패가 트레이딩을 막으면 안 됨).
    """
    today = datetime.now().strftime("%Y%m%d")
    snap_path = config.get_logs_dir() / f"start_snapshot_{today}.json"
    if snap_path.exists():
        return  # 이미 저장됨 (재시작 등 중복 방지)
    try:
        balance, holdings = get_account_info()
        data = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "holdings": [
                {
                    "stock_code": h["stock_code"],
                    "stock_name": h.get("stock_name", ""),
                    "quantity": h["quantity"],
                    "avg_price": h["avg_price"],
                }
                for h in holdings
            ],
            "balance": {
                "total_eval": balance.get("total_eval", 0),
                "cash": balance.get("cash", 0),
                "profit_loss": balance.get("profit_loss", 0),
            },
        }
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_info(f"시작 스냅샷 저장: {snap_path}")
    except Exception as e:
        log_error(f"시작 스냅샷 저장 실패 (무시): {e}")


def _maybe_generate_report() -> None:
    """장 마감 이후(15:30) 종료된 경우에만 리포트를 생성한다.

    15:30 이전 종료(조기 중단)이면 log_info 메시지만 남기고 반환한다.
    generate_daily_report 예외는 log_error로 처리하고 전파하지 않는다.
    """
    now = datetime.now()
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        log_info("장 마감 전 종료: 일별 리포트를 생성하지 않습니다.")
        return
    today = now.strftime("%Y%m%d")
    balance: dict | None = None
    holdings: list | None = None
    try:
        balance, holdings = get_account_info()
    except Exception as e:
        log_error(f"마감 잔고 조회 실패 (리포트에 balance 제외): {e}")
    try:
        from src.reporter import generate_daily_report
        paths = generate_daily_report(today, balance_snapshot=balance, holdings_snapshot=holdings)
        for p in paths:
            log_info(f"리포트 생성 완료: {p}")
    except Exception as e:
        log_error(f"일별 리포트 생성 실패: {e}")


def run_swing_cycle(state, excluded_codes=None):
    if _check_circuit_breaker(state):
        log_info("Swing strategy stopped by circuit breaker.")
        return False

    # 잔고 조회 실패는 사이클 자체 포기 (이후 분석/매매 불가능)
    try:
        balance, holdings = get_account_info()
    except Exception as e:
        log_error(f"Swing balance fetch failed (사이클 skip): {e}")
        return True  # 다음 사이클(5분 후) 재시도

    # 종목별 분석/매매는 _check_holdings, _check_targets 내부에서
    # 종목 단위로 try/except 격리되어 있음. 한 종목 실패가 다른 종목 매매를 막지 않는다.
    try:
        _check_holdings(holdings, state, excluded_codes=excluded_codes)
    except Exception as e:
        log_error(f"Swing _check_holdings unexpected error: {e}")
    try:
        _check_targets(holdings, balance, state, excluded_codes=excluded_codes)
    except Exception as e:
        log_error(f"Swing _check_targets unexpected error: {e}")
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

    prev_handlers = install_shutdown_handlers(signal_handler)
    _write_status()
    state = _load_state()

    from src.combined import _format_swing_block
    log_info(f"=== Swing 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(_format_swing_block(config.get_swing_stocks(), interval_sec))

    try:
        while running:
            if not is_market_open():
                if _log_closed_market_message():
                    break
                time.sleep(60)
                continue

            _snapshot_holdings_at_open()

            if not run_swing_cycle(state):
                break

            for _ in range(interval_sec):
                if not running:
                    break
                time.sleep(1)
    finally:
        _clear_status()
        _maybe_generate_report()
        restore_handlers(prev_handlers)
        from src.combined import print_daily_summary
        print_daily_summary()

    log_info("=== Swing strategy stopped ===")
