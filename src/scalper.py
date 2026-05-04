import json
import time
from collections import deque
from datetime import date

from src import config
from src.fetcher import get_current_price
from src.logger import log_error, log_info, log_trade
from src.trader import buy, get_holdings, sell


class ScalpMonitor:
    def __init__(self, stock_code=None):
        self.stock_code = stock_code or config.get_scalp_stock()
        if not self.stock_code:
            raise ValueError("SCALP_STOCK or TARGET_STOCKS must contain at least one stock code.")

        self.display = config.format_stock(self.stock_code)  # 로그 표기용
        self.prices = deque(maxlen=config.get_scalp_window_size())
        self.state = self._load_state()
        # reconcile 결과를 파일에 즉시 반영(desync 발견 시 다음 실행에서 재발 방지)
        self._save_state()
        self.next_run_at = 0.0  # 종목별 다음 실행 시각 (epoch)
        self.last_price = 0     # heartbeat 표시용 최근 조회가

    def maybe_run(self, interval_sec: float) -> bool:
        """interval_sec이 경과했으면 run_once 실행. 실행했으면 True."""
        now = time.time()
        if now < self.next_run_at:
            return False
        self.run_once()
        self.next_run_at = time.time() + interval_sec
        return True

    def run_loop(self, interval_sec: float, stop_event) -> None:
        """종목 단독 thread에서 영구 루프. stop_event로 종료 가능.

        한 종목의 느림이 다른 종목에 영향을 주지 않게 한다.
        run_once 예외는 흡수해 다음 사이클 진행.
        """
        while not stop_event.is_set():
            t0 = time.time()
            try:
                self.run_once()
            except Exception as e:
                log_error(f"SCALP {self.display} run_once error: {e}")
            elapsed = time.time() - t0
            wait = max(0.0, interval_sec - elapsed)
            if stop_event.wait(wait):
                break

    def _empty_state(self):
        return {
            "date": date.today().isoformat(),
            "mode": config.get_mode(),
            "stock_code": self.stock_code,
            "position_qty": 0,
            "entry_price": 0,
            "high_price": 0,
            "entry_time": 0,
        }

    def _load_state(self):
        path = config.get_scalp_state_path(self.stock_code)
        if not path.exists():
            return self._reconcile_with_holdings(self._empty_state())
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return self._reconcile_with_holdings(self._empty_state())

        if state.get("mode") != config.get_mode():
            return self._reconcile_with_holdings(self._empty_state())
        if state.get("stock_code") != self.stock_code:
            return self._reconcile_with_holdings(self._empty_state())
        if state.get("date") != date.today().isoformat() and not state.get("position_qty"):
            return self._reconcile_with_holdings(self._empty_state())
        return self._reconcile_with_holdings({**self._empty_state(), **state})

    def _reconcile_with_holdings(self, state):
        """로컬 state를 KIS 실제 보유 수량과 비교해 동기화한다.

        외부 매도/부분체결/수동 거래 등으로 발생한 desync를 막는다.
        잔고 조회 실패 시(네트워크 오류 등) 로컬 state를 그대로 사용한다.
        """
        try:
            held = next(
                (h for h in get_holdings() if h["stock_code"] == self.stock_code),
                None,
            )
        except Exception as e:
            log_error(f"SCALP {self.display} state reconcile skipped (잔고조회 실패): {e}")
            return state

        actual_qty = int(held["quantity"]) if held else 0
        local_qty = int(state.get("position_qty", 0))

        if local_qty == actual_qty:
            return state

        if actual_qty == 0 and local_qty > 0:
            log_info(
                f"SCALP {self.display} state desync: local={local_qty}주, "
                f"actual=0 → 포지션 초기화"
            )
            return self._empty_state()

        if actual_qty < local_qty:
            log_info(
                f"SCALP {self.display} state desync: local={local_qty}주, "
                f"actual={actual_qty}주 → position_qty 동기화"
            )
            state["position_qty"] = actual_qty
            return state

        # actual_qty > local_qty: 외부 매수로 보유가 더 많음.
        # 진입 정보(entry_price/time)를 모르므로 수량만 맞추고 entry는 평균가 사용.
        log_info(
            f"SCALP {self.display} state desync: local={local_qty}주, "
            f"actual={actual_qty}주 → 외부 매수 감지, 평균가로 entry 추정"
        )
        state["position_qty"] = actual_qty
        if local_qty == 0:
            avg = int(held.get("avg_price", 0))
            state["entry_price"] = avg
            state["high_price"] = avg
            state["entry_time"] = time.time()
        return state

    def _save_state(self):
        path = config.get_scalp_state_path(self.stock_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _has_position(self):
        return int(self.state.get("position_qty", 0)) > 0

    def _buy_signal(self, price):
        if len(self.prices) < self.prices.maxlen:
            return False, "warming up"

        series = list(self.prices)
        previous = series[:-1]
        base = min(previous)
        if base <= 0:
            return False, "invalid base price"

        momentum_pct = ((price - base) / base) * 100
        breakout = price >= max(previous)
        rising = series[-1] > series[-2] > series[-3]

        if breakout and rising and momentum_pct >= config.get_scalp_min_momentum_pct():
            return True, f"breakout momentum {momentum_pct:.2f}%"
        return False, f"hold momentum {momentum_pct:.2f}%"

    def _sell_signal(self, price):
        entry_price = int(self.state.get("entry_price", 0))
        if entry_price <= 0:
            return False, "missing entry price"

        high_price = max(int(self.state.get("high_price", 0)), price)
        if high_price != self.state.get("high_price"):
            self.state["high_price"] = high_price
            self._save_state()

        pnl_pct = ((price - entry_price) / entry_price) * 100
        drop_pct = ((high_price - price) / high_price) * 100 if high_price > 0 else 0
        age_sec = time.time() - float(self.state.get("entry_time", 0))

        if pnl_pct <= config.get_scalp_stop_loss_pct():
            return True, f"stop loss {pnl_pct:.2f}%"
        if pnl_pct >= config.get_scalp_take_profit_pct():
            return True, f"take profit {pnl_pct:.2f}%"
        if pnl_pct > 0 and drop_pct >= config.get_scalp_trailing_drop_pct():
            return True, f"trailing drop {drop_pct:.2f}%"
        # 타임아웃은 '실수익 기준'으로 판정. 수수료+거래세 차감 후 0 이하면 청산.
        # (명목 0%만 잘라내던 기존 방식은 +0.1% 같은 미세 양전에서 갇히는 문제가 있었음)
        total_cost_pct = (
            config.get_buy_fee_rate()
            + config.get_sell_fee_rate()
            + config.get_sell_tax_rate()
        ) * 100
        if age_sec >= config.get_scalp_max_hold_sec() and pnl_pct <= total_cost_pct:
            return True, f"timeout {int(age_sec)}s pnl {pnl_pct:.2f}% (실수익 0 이하)"
        return False, f"holding pnl {pnl_pct:.2f}%"

    def _enter_position(self, price, reason):
        amount = config.get_scalp_max_buy_amount()
        requested_qty = amount // price
        if requested_qty <= 0:
            log_info(f"SCALP {self.display} buy skipped: amount {amount:,} < price {price:,}")
            return

        if config.is_scalp_trade_enabled():
            order = buy(self.stock_code, amount, price)
            filled_qty = int(order.get("filled_qty", 0))
            fill_price = int(order.get("avg_fill_price", 0))
            if filled_qty <= 0 or fill_price <= 0:
                log_error(
                    f"SCALP {self.display} buy unfilled: ord={order.get('ord_qty')}, "
                    f"filled={filled_qty}, odno={order.get('odno')}"
                )
                return
            action = "SCALP_BUY" if order.get("fully_filled") else "SCALP_BUY_PARTIAL"
            log_reason = self._annotate_reason(reason, order, requested_qty)
        else:
            log_info(f"SCALP {self.display} paper buy signal only: {reason}")
            filled_qty = requested_qty
            fill_price = price
            action = "SCALP_BUY"
            log_reason = reason

        self.state.update({
            "date": date.today().isoformat(),
            "mode": config.get_mode(),
            "stock_code": self.stock_code,
            "position_qty": filled_qty,
            "entry_price": fill_price,
            "high_price": fill_price,
            "entry_time": time.time(),
        })
        self._save_state()
        log_trade(self.stock_code, action, fill_price, filled_qty, fill_price * filled_qty, log_reason)

    def _exit_position(self, price, reason):
        held_qty = int(self.state.get("position_qty", 0))
        if held_qty <= 0:
            return

        entry_price = int(self.state.get("entry_price", 0))

        if config.is_scalp_trade_enabled():
            order = sell(self.stock_code, held_qty, current_price=price)
            filled_qty = int(order.get("filled_qty", 0))
            fill_price = int(order.get("avg_fill_price", 0))
            if filled_qty <= 0 or fill_price <= 0:
                log_error(
                    f"SCALP {self.display} sell unfilled: ord={order.get('ord_qty')}, "
                    f"filled={filled_qty}, odno={order.get('odno')}"
                )
                return
            action = "SCALP_SELL" if order.get("fully_filled") else "SCALP_SELL_PARTIAL"
            log_reason = self._annotate_reason(reason, order, held_qty)
        else:
            log_info(f"SCALP {self.display} paper sell signal only: {reason}")
            filled_qty = held_qty
            fill_price = price
            action = "SCALP_SELL"
            log_reason = reason

        # 수수료/거래세 반영 실현손익
        pnl = 0.0
        if entry_price > 0 and filled_qty > 0:
            gross = (fill_price - entry_price) * filled_qty
            buy_fee = entry_price * filled_qty * config.get_buy_fee_rate()
            sell_fee = fill_price * filled_qty * config.get_sell_fee_rate()
            sell_tax = fill_price * filled_qty * config.get_sell_tax_rate()
            pnl = gross - buy_fee - sell_fee - sell_tax

        log_trade(
            self.stock_code,
            action,
            fill_price,
            filled_qty,
            fill_price * filled_qty,
            log_reason,
            pnl=pnl,
        )

        remaining = held_qty - filled_qty
        if remaining > 0:
            self.state["position_qty"] = remaining
            self._save_state()
        else:
            self.state = self._empty_state()
            self._save_state()

    @staticmethod
    def _annotate_reason(base_reason: str, order: dict, requested_qty: int) -> str:
        notes = [base_reason]
        if not order.get("fully_filled", True):
            notes.append(f"체결 {order.get('filled_qty', 0)}/{requested_qty}")
        if order.get("estimated"):
            notes.append("체결조회 실패-추정")
        return " | ".join(notes)

    def run_once(self):
        try:
            price = get_current_price(self.stock_code)["price"]
        except Exception:
            # KIS 모의 500 에러 등은 흔하므로 침묵 (retry는 fetcher가 처리).
            # 5회 연속 실패시에만 한 번 알림.
            self._fetch_fail_count = getattr(self, "_fetch_fail_count", 0) + 1
            if self._fetch_fail_count == 5:
                log_info(f"SCALP {self.display} 가격 조회 5회 연속 실패 (KIS 모의 일시 부하)")
            return
        self._fetch_fail_count = 0

        if price <= 0:
            return

        self.last_price = price
        self.prices.append(price)

        try:
            if self._has_position():
                should_sell, reason = self._sell_signal(price)
                if should_sell:
                    log_info(f"SCALP {self.display} 매도 신호: {reason} @ {price:,}")
                    self._exit_position(price, reason)
            else:
                should_buy, reason = self._buy_signal(price)
                if should_buy:
                    log_info(f"SCALP {self.display} 매수 신호: {reason} @ {price:,}")
                    self._enter_position(price, reason)
        except Exception as e:
            log_error(f"SCALP {self.display} cycle failed: {e}")
