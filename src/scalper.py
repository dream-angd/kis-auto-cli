import json
import time
from collections import deque
from datetime import date

from src import config
from src.fetcher import get_current_price
from src.logger import log_error, log_info, log_trade
from src.trader import buy, sell


class ScalpMonitor:
    def __init__(self, stock_code=None):
        self.stock_code = stock_code or config.get_scalp_stock()
        if not self.stock_code:
            raise ValueError("SCALP_STOCK or TARGET_STOCKS must contain at least one stock code.")

        self.prices = deque(maxlen=config.get_scalp_window_size())
        self.state = self._load_state()

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
        path = config.get_scalp_state_path()
        if not path.exists():
            return self._empty_state()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_state()

        if state.get("mode") != config.get_mode():
            return self._empty_state()
        if state.get("stock_code") != self.stock_code:
            return self._empty_state()
        if state.get("date") != date.today().isoformat() and not state.get("position_qty"):
            return self._empty_state()
        return {**self._empty_state(), **state}

    def _save_state(self):
        path = config.get_scalp_state_path()
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
        if age_sec >= config.get_scalp_max_hold_sec() and pnl_pct <= 0:
            return True, f"timeout {int(age_sec)}s pnl {pnl_pct:.2f}%"
        return False, f"holding pnl {pnl_pct:.2f}%"

    def _enter_position(self, price, reason):
        amount = config.get_scalp_max_buy_amount()
        requested_qty = amount // price
        if requested_qty <= 0:
            log_info(f"SCALP {self.stock_code} buy skipped: amount {amount:,} < price {price:,}")
            return

        if config.is_scalp_trade_enabled():
            order = buy(self.stock_code, amount, price)
            filled_qty = int(order.get("filled_qty", 0))
            fill_price = int(order.get("avg_fill_price", 0))
            if filled_qty <= 0 or fill_price <= 0:
                log_error(
                    f"SCALP {self.stock_code} buy unfilled: ord={order.get('ord_qty')}, "
                    f"filled={filled_qty}, odno={order.get('odno')}"
                )
                return
            action = "SCALP_BUY" if order.get("fully_filled") else "SCALP_BUY_PARTIAL"
            log_reason = self._annotate_reason(reason, order, requested_qty)
        else:
            log_info(f"SCALP {self.stock_code} paper buy signal only: {reason}")
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
                    f"SCALP {self.stock_code} sell unfilled: ord={order.get('ord_qty')}, "
                    f"filled={filled_qty}, odno={order.get('odno')}"
                )
                return
            action = "SCALP_SELL" if order.get("fully_filled") else "SCALP_SELL_PARTIAL"
            log_reason = self._annotate_reason(reason, order, held_qty)
        else:
            log_info(f"SCALP {self.stock_code} paper sell signal only: {reason}")
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
        except Exception as e:
            log_error(f"SCALP {self.stock_code} price fetch failed: {e}")
            return

        if price <= 0:
            log_error(f"SCALP {self.stock_code} invalid price: {price}")
            return

        self.prices.append(price)

        try:
            if self._has_position():
                should_sell, reason = self._sell_signal(price)
                log_info(f"SCALP {self.stock_code} price={price:,} position=on {reason}")
                if should_sell:
                    self._exit_position(price, reason)
            else:
                should_buy, reason = self._buy_signal(price)
                log_info(f"SCALP {self.stock_code} price={price:,} position=off {reason}")
                if should_buy:
                    self._enter_position(price, reason)
        except Exception as e:
            log_error(f"SCALP {self.stock_code} cycle failed: {e}")
