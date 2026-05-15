"""백테스트 엔진.

기존 analyzer.py의 지표/신호 로직을 역사적 OHLCV 데이터에 적용하여
포트폴리오 성과를 시뮬레이션한다.

analyzer.py를 수정하지 않고 add_indicators()만 import하여 재사용한다.
실제 API 호출을 포함하는 analyze()는 사용하지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src import config
from src.analyzer import add_indicators


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    date: str
    action: str       # BUY | SELL
    price: float
    qty: int
    amount: float     # price * qty (세전)
    fee: float        # 수수료 + 거래세 합계
    pnl: float        # 실현손익 (SELL 시 세후, BUY 시 0)
    reason: str


@dataclass
class BacktestResult:
    stock_code: str
    start: str
    end: str
    initial_capital: float
    final_capital: float
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_ohlcv_from_csv(filepath: str, start: str, end: str) -> pd.DataFrame:
    """CSV 파일에서 OHLCV를 로드하고 기간 필터를 적용한다.

    CSV 컬럼: date, open, high, low, close, volume
    date 형식: YYYY-MM-DD 또는 YYYYMMDD
    """
    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip() for c in df.columns]

    if "date" not in df.columns:
        raise ValueError(f"CSV에 'date' 컬럼이 없습니다: {filepath}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].reset_index(drop=True)

    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


def load_ohlcv_from_api(stock_code: str, start: str, end: str) -> pd.DataFrame:
    """KIS API에서 OHLCV를 로드하고 기간 필터를 적용한다.

    API는 최대 100일치를 반환하므로 기간이 길면 청크로 나눠 호출한다.
    """
    from datetime import datetime, timedelta
    from src.fetcher import get_daily_ohlcv

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    total_days = (end_dt - start_dt).days + 1
    # API는 최근 N일 방식이므로 전체 기간을 커버하도록 충분한 일수 요청
    # 영업일 기준으로 실제 데이터는 더 적으므로 여유를 두고 요청
    fetch_days = max(60, int(total_days * 1.5))

    # get_daily_ohlcv는 현재 날짜 기준 days일 전까지 조회
    # 백테스트는 과거 구간이므로 전체를 한 번에 요청
    df = get_daily_ohlcv(stock_code, days=fetch_days)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    start_dt_pd = pd.to_datetime(start)
    end_dt_pd = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt_pd) & (df["date"] <= end_dt_pd)].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Signal generator
# ---------------------------------------------------------------------------

def _generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """add_indicators() 결과에서 날짜별 BUY/SELL/HOLD 신호를 생성한다.

    analyzer.py의 신호 조건과 동일하게 구현한다 (API 호출 제외).
    최소 26행(MACD slow period) 필요.
    """
    if len(df) < 26:
        df = df.copy()
        df["signal"] = "HOLD"
        df["signal_reason"] = "데이터 부족"
        return df

    df = add_indicators(df)
    signals = []
    reasons = []

    stop_loss_pct = config.get_stop_loss_pct()
    take_profit_pct = config.get_take_profit_pct()

    # 포지션 추적 (신호 생성 단계에서는 stop/take만 체크)
    # 실제 손절/익절은 simulate()에서 처리하므로 여기서는 기술적 신호만
    for i in range(len(df)):
        if i == 0:
            signals.append("HOLD")
            reasons.append("첫 행 — 전일 데이터 없음")
            continue

        cur = df.iloc[i]
        prev = df.iloc[i - 1]

        # 지표 NaN 체크
        if any(pd.isna(cur[c]) for c in ["ma5", "ma20", "rsi", "macd", "macd_signal", "bb_upper", "bb_lower"]):
            signals.append("HOLD")
            reasons.append("지표 미확정")
            continue

        golden_cross = prev["ma5"] <= prev["ma20"] and cur["ma5"] > cur["ma20"]
        dead_cross = prev["ma5"] >= prev["ma20"] and cur["ma5"] < cur["ma20"]
        rsi = cur["rsi"]
        macd = cur["macd"]
        macd_sig = cur["macd_signal"]
        close = cur["close"]
        bb_lower = cur["bb_lower"]
        bb_upper = cur["bb_upper"]

        if golden_cross and rsi < 70 and macd > macd_sig:
            signals.append("BUY")
            reasons.append(f"골든크로스 + MACD 상향 (RSI: {rsi:.1f})")
        elif close <= bb_lower and rsi < 30:
            signals.append("BUY")
            reasons.append(f"볼린저 하단 돌파 + RSI 과매도 ({rsi:.1f})")
        elif dead_cross:
            signals.append("SELL")
            reasons.append(f"데드크로스 (RSI: {rsi:.1f})")
        elif close >= bb_upper and rsi > 70:
            signals.append("SELL")
            reasons.append(f"볼린저 상단 돌파 + RSI 과매수 ({rsi:.1f})")
        else:
            signals.append("HOLD")
            reasons.append(f"대기 (RSI: {rsi:.1f})")

    df = df.copy()
    df["signal"] = signals
    df["signal_reason"] = reasons
    return df


# ---------------------------------------------------------------------------
# Trade simulator
# ---------------------------------------------------------------------------

def simulate(
    stock_code: str,
    df: pd.DataFrame,
    initial_capital: float,
) -> tuple[list[TradeRecord], list[float]]:
    """신호 데이터를 기반으로 거래를 시뮬레이션한다.

    반환: (trades, equity_curve)
    equity_curve[i] = i번째 날 종가 기준 자산 총액
    """
    buy_fee_rate = config.get_buy_fee_rate()
    sell_fee_rate = config.get_sell_fee_rate()
    sell_tax_rate = config.get_sell_tax_rate()
    max_buy = config.get_max_buy_amount()
    stop_loss_pct = config.get_stop_loss_pct()
    take_profit_pct = config.get_take_profit_pct()

    cash = initial_capital
    position_qty = 0
    position_avg_price = 0.0
    trades: list[TradeRecord] = []
    equity_curve: list[float] = []

    for i, row in df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
        close = float(row["close"])
        signal = row.get("signal", "HOLD")
        reason = row.get("signal_reason", "")

        # 보유 중 손절/익절 우선 체크
        if position_qty > 0 and position_avg_price > 0:
            pnl_pct = ((close - position_avg_price) / position_avg_price) * 100
            if pnl_pct <= stop_loss_pct:
                signal = "SELL"
                reason = f"손절 도달 ({pnl_pct:.1f}%)"
            elif pnl_pct >= take_profit_pct:
                signal = "SELL"
                reason = f"익절 도달 ({pnl_pct:.1f}%)"

        # 마지막 날 강제 청산
        is_last = (i == len(df) - 1)
        if is_last and position_qty > 0:
            signal = "SELL"
            reason = "기간 종료 — 강제 청산"

        if signal == "BUY" and position_qty == 0 and cash >= close:
            qty = int(min(max_buy, cash) // close)
            if qty > 0:
                amount = close * qty
                fee = amount * buy_fee_rate
                cash -= (amount + fee)
                position_qty = qty
                position_avg_price = close
                trades.append(TradeRecord(
                    date=date_str,
                    action="BUY",
                    price=close,
                    qty=qty,
                    amount=amount,
                    fee=fee,
                    pnl=0.0,
                    reason=reason,
                ))

        elif signal == "SELL" and position_qty > 0:
            amount = close * position_qty
            sell_fee = amount * sell_fee_rate
            sell_tax = amount * sell_tax_rate
            fee = sell_fee + sell_tax
            gross_pnl = (close - position_avg_price) * position_qty
            buy_fee_paid = position_avg_price * position_qty * buy_fee_rate
            net_pnl = gross_pnl - buy_fee_paid - fee
            cash += (amount - fee)
            trades.append(TradeRecord(
                date=date_str,
                action="SELL",
                price=close,
                qty=position_qty,
                amount=amount,
                fee=fee,
                pnl=net_pnl,
                reason=reason,
            ))
            position_qty = 0
            position_avg_price = 0.0

        # 자산 = 현금 + 평가액
        equity = cash + position_qty * close
        equity_curve.append(equity)

    return trades, equity_curve


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def calc_metrics(
    trades: list[TradeRecord],
    equity_curve: list[float],
    initial_capital: float,
) -> dict:
    """성과 지표를 계산한다."""
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100 if initial_capital > 0 else 0.0

    # Max drawdown
    max_dd = 0.0
    if equity_curve:
        peak = equity_curve[0]
        for v in equity_curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

    # Sharpe ratio (일별 수익률 기준, risk-free=0)
    sharpe = 0.0
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] if equity_curve[i - 1] > 0 else 0.0
            returns.append(r)
        if returns:
            n = len(returns)
            mean_r = sum(returns) / n
            variance = sum((r - mean_r) ** 2 for r in returns) / n
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    sell_trades = [t for t in trades if t.action == "SELL"]
    total_trades = len(sell_trades)
    win_trades = [t for t in sell_trades if t.pnl > 0]
    loss_trades = [t for t in sell_trades if t.pnl <= 0]
    win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0.0

    total_profit = sum(t.pnl for t in win_trades)
    total_loss = abs(sum(t.pnl for t in loss_trades))
    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    return {
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else None,
        "total_trades": total_trades,
        "win_count": len(win_trades),
        "loss_count": len(loss_trades),
        "final_capital": round(final_capital, 0),
        "initial_capital": round(initial_capital, 0),
        "total_pnl": round(sum(t.pnl for t in sell_trades), 0),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_backtest(
    stock_code: str,
    start: str,
    end: str,
    csv_path: str | None = None,
    initial_capital: float = 10_000_000,
) -> BacktestResult:
    """백테스트를 실행하고 결과를 반환한다.

    Args:
        stock_code: 종목 코드 (예: "005930")
        start: 시작일 YYYY-MM-DD
        end: 종료일 YYYY-MM-DD
        csv_path: 로컬 CSV 파일 경로 (None이면 KIS API 사용)
        initial_capital: 초기 자본금 (원)
    """
    if csv_path:
        df = load_ohlcv_from_csv(csv_path, start, end)
    else:
        df = load_ohlcv_from_api(stock_code, start, end)

    if df.empty:
        raise ValueError(f"데이터 없음: {stock_code} {start}~{end}")

    df = _generate_signals(df)
    trades, equity_curve = simulate(stock_code, df, initial_capital)
    metrics = calc_metrics(trades, equity_curve, initial_capital)

    return BacktestResult(
        stock_code=stock_code,
        start=start,
        end=end,
        initial_capital=initial_capital,
        final_capital=metrics["final_capital"],
        trades=trades,
        equity_curve=equity_curve,
        metrics=metrics,
    )
