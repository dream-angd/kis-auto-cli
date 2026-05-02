import pytest
import pandas as pd
import numpy as np

from src.analyzer import (
    _calc_ma,
    _calc_rsi,
    _calc_macd,
    _calc_bollinger,
    _calc_atr,
    add_indicators,
    calc_position_size,
)


def make_ohlcv(n=60, start_price=50000, seed=42):
    rng = np.random.default_rng(seed)
    closes = start_price + np.cumsum(rng.normal(0, 500, n))
    closes = closes.clip(min=1000)
    highs = closes * rng.uniform(1.001, 1.02, n)
    lows = closes * rng.uniform(0.98, 0.999, n)
    df = pd.DataFrame({
        "open": closes.astype(int),
        "high": highs.astype(int),
        "low": lows.astype(int),
        "close": closes.astype(int),
        "volume": rng.integers(100000, 1000000, n),
    })
    return df


# --- _calc_ma ---

def test_calc_ma_basic():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    ma3 = _calc_ma(s, 3)
    assert ma3.iloc[-1] == pytest.approx(4.0)
    assert pd.isna(ma3.iloc[0])


def test_calc_ma_window_1():
    s = pd.Series([10.0, 20.0, 30.0])
    assert _calc_ma(s, 1).tolist() == pytest.approx([10.0, 20.0, 30.0])


# --- _calc_rsi ---

def test_calc_rsi_range():
    df = make_ohlcv(60)
    rsi = _calc_rsi(df["close"])
    valid = rsi.dropna()
    assert len(valid) > 0
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_calc_rsi_all_gains():
    s = pd.Series([100.0 + i for i in range(30)])
    rsi = _calc_rsi(s, period=14)
    assert rsi.dropna().iloc[-1] == pytest.approx(100.0)


def test_calc_rsi_all_losses():
    s = pd.Series([100.0 - i for i in range(30)])
    rsi = _calc_rsi(s, period=14)
    # 모두 하락 → RSI 0에 수렴 (avg_gain=0)
    assert rsi.dropna().iloc[-1] == pytest.approx(0.0)


# --- _calc_macd ---

def test_calc_macd_returns_two_series():
    df = make_ohlcv(60)
    macd, signal = _calc_macd(df["close"])
    assert len(macd) == len(df)
    assert len(signal) == len(df)


def test_calc_macd_signal_lagged():
    df = make_ohlcv(60)
    macd, signal = _calc_macd(df["close"])
    # signal은 macd의 EMA이므로 두 시리즈의 길이가 같아야 함
    assert not macd.equals(signal)


# --- _calc_bollinger ---

def test_calc_bollinger_band_order():
    df = make_ohlcv(60)
    upper, mid, lower = _calc_bollinger(df["close"])
    valid_idx = upper.dropna().index
    assert (upper[valid_idx] >= mid[valid_idx]).all()
    assert (mid[valid_idx] >= lower[valid_idx]).all()


def test_calc_bollinger_mid_is_ma():
    df = make_ohlcv(60)
    _, mid, _ = _calc_bollinger(df["close"], window=20)
    expected_ma = _calc_ma(df["close"], 20)
    pd.testing.assert_series_equal(mid, expected_ma, check_names=False)


# --- _calc_atr ---

def test_calc_atr_positive():
    df = make_ohlcv(60)
    atr = _calc_atr(df, period=14)
    valid = atr.dropna()
    assert len(valid) > 0
    assert (valid > 0).all()


def test_calc_atr_length():
    df = make_ohlcv(60)
    atr = _calc_atr(df)
    assert len(atr) == len(df)


def test_calc_atr_first_values_nan():
    df = make_ohlcv(30)
    atr = _calc_atr(df, period=14)
    # min_periods=14이므로 첫 13개는 NaN
    assert pd.isna(atr.iloc[0])


# --- add_indicators ---

def test_add_indicators_columns():
    df = make_ohlcv(60)
    result = add_indicators(df)
    expected_cols = ["ma5", "ma20", "rsi", "macd", "macd_signal",
                     "bb_upper", "bb_mid", "bb_lower", "atr"]
    for col in expected_cols:
        assert col in result.columns, f"컬럼 누락: {col}"


def test_add_indicators_does_not_mutate_input():
    df = make_ohlcv(60)
    original_cols = set(df.columns)
    add_indicators(df)
    assert set(df.columns) == original_cols


# --- calc_position_size ---

def test_calc_position_size_normal(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "2.0")
    monkeypatch.setenv("ATR_RISK_PCT", "0.01")
    # risk_amount = 500000 * 0.01 = 5000
    # stop_distance = 500 * 2.0 = 1000
    # qty_atr = 5000 / 1000 = 5
    # max_qty = 500000 // 50000 = 10
    # result = min(5, 10) = 5
    qty = calc_position_size(50000, 500.0, 500000)
    assert qty == 5


def test_calc_position_size_zero_atr(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "2.0")
    monkeypatch.setenv("ATR_RISK_PCT", "0.01")
    # ATR=0 → fallback: 500000 // 50000 = 10
    qty = calc_position_size(50000, 0.0, 500000)
    assert qty == 10


def test_calc_position_size_cap_at_max(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "2.0")
    monkeypatch.setenv("ATR_RISK_PCT", "0.01")
    # 아주 작은 ATR → qty 폭증, max_qty=10으로 제한
    # max_qty = 500000 // 50000 = 10
    qty = calc_position_size(50000, 1.0, 500000)
    assert qty == 10


def test_calc_position_size_minimum_1(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "2.0")
    monkeypatch.setenv("ATR_RISK_PCT", "0.01")
    # 주가가 매우 높아 qty가 0이 될 수 있어도 최소 1 보장
    # max_qty = 100000 // 1000000 = 0 → max(1, 0) = 1
    qty = calc_position_size(1000000, 50000.0, 100000)
    assert qty >= 1


def test_calc_position_size_high_atr_reduces_qty(monkeypatch):
    monkeypatch.setenv("ATR_MULTIPLIER", "2.0")
    monkeypatch.setenv("ATR_RISK_PCT", "0.01")
    qty_low_atr = calc_position_size(50000, 200.0, 500000)
    qty_high_atr = calc_position_size(50000, 2000.0, 500000)
    assert qty_high_atr <= qty_low_atr
