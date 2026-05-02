import pandas as pd
from src import config
from src.fetcher import get_daily_ohlcv, get_current_price


def _calc_ma(series, window):
    return series.rolling(window=window).mean()


def _calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rsi = pd.Series(index=series.index, dtype=float)
    both_valid = (gain.notna()) & (loss.notna())
    rsi[both_valid & (loss == 0)] = 100.0
    rsi[both_valid & (gain == 0)] = 0.0
    normal = both_valid & (loss > 0) & (gain >= 0)
    rs = gain[normal] / loss[normal]
    rsi[normal] = 100 - (100 / (1 + rs))
    return rsi


def _calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _calc_bollinger(series, window=20, num_std=2):
    ma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, ma, lower


def add_indicators(df):
    df = df.copy()
    df["ma5"] = _calc_ma(df["close"], 5)
    df["ma20"] = _calc_ma(df["close"], 20)
    df["rsi"] = _calc_rsi(df["close"])
    df["macd"], df["macd_signal"] = _calc_macd(df["close"])
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = _calc_bollinger(df["close"])
    return df


def _check_stop_loss_take_profit(current_price, avg_price):
    stop_loss_pct = config.get_stop_loss_pct()
    take_profit_pct = config.get_take_profit_pct()

    if avg_price <= 0:
        return "HOLD", ""

    pnl_pct = ((current_price - avg_price) / avg_price) * 100

    if pnl_pct <= stop_loss_pct:
        return "SELL", f"손절 도달 ({pnl_pct:.1f}%)"
    if pnl_pct >= take_profit_pct:
        return "SELL", f"익절 도달 ({pnl_pct:.1f}%)"
    return "HOLD", ""


def analyze(stock_code, avg_price=0):
    price_info = get_current_price(stock_code)
    current_price = price_info["price"]

    if avg_price > 0:
        signal, reason = _check_stop_loss_take_profit(current_price, avg_price)
        if signal == "SELL":
            return {"signal": "SELL", "reason": reason, "current_price": current_price}

    df = get_daily_ohlcv(stock_code, days=60)
    if df.empty or len(df) < 26:
        return {"signal": "HOLD", "reason": "데이터 부족", "current_price": current_price}

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # 골든크로스: MA5가 MA20 위로 돌파
    golden_cross = prev["ma5"] <= prev["ma20"] and latest["ma5"] > latest["ma20"]
    # 데드크로스: MA5가 MA20 아래로 돌파
    dead_cross = prev["ma5"] >= prev["ma20"] and latest["ma5"] < latest["ma20"]

    rsi = latest["rsi"]
    macd = latest["macd"]
    macd_sig = latest["macd_signal"]
    bb_lower = latest["bb_lower"]
    bb_upper = latest["bb_upper"]
    close = latest["close"]

    # 복합 매수: 골든크로스 + RSI < 70 + MACD 상향
    if golden_cross and rsi < 70 and macd > macd_sig:
        return {
            "signal": "BUY",
            "reason": f"골든크로스 + MACD 상향 (RSI: {rsi:.1f})",
            "current_price": current_price,
        }

    # 볼린저 하단 근접 + RSI 과매도 → 매수
    if close <= bb_lower and rsi < 30:
        return {
            "signal": "BUY",
            "reason": f"볼린저 하단 돌파 + RSI 과매도 ({rsi:.1f})",
            "current_price": current_price,
        }

    # 데드크로스 or 볼린저 상단 돌파 + RSI 과매수
    if dead_cross:
        return {
            "signal": "SELL",
            "reason": f"데드크로스 (RSI: {rsi:.1f})",
            "current_price": current_price,
        }

    if close >= bb_upper and rsi > 70:
        return {
            "signal": "SELL",
            "reason": f"볼린저 상단 돌파 + RSI 과매수 ({rsi:.1f})",
            "current_price": current_price,
        }

    return {"signal": "HOLD", "reason": f"대기 (RSI: {rsi:.1f}, MACD: {macd:.1f})", "current_price": current_price}
