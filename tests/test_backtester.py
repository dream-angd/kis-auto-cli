"""백테스터 단위 테스트."""
from __future__ import annotations

import csv
import io
import math
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.backtester import (
    TradeRecord,
    _generate_signals,
    calc_metrics,
    load_ohlcv_from_csv,
    simulate,
)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n_rows: int = 60, start_price: int = 10000) -> pd.DataFrame:
    """테스트용 OHLCV DataFrame을 생성한다."""
    dates = pd.date_range("2024-01-02", periods=n_rows, freq="B")
    prices = [start_price + i * 10 for i in range(n_rows)]
    rows = []
    for d, p in zip(dates, prices):
        rows.append({
            "date": d,
            "open": p,
            "high": p + 50,
            "low": p - 50,
            "close": p,
            "volume": 100000,
        })
    return pd.DataFrame(rows)


def _make_csv_file(df: pd.DataFrame) -> str:
    """DataFrame을 임시 CSV 파일로 저장하고 경로를 반환한다."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    writer = csv.DictWriter(tmp, fieldnames=["date", "open", "high", "low", "close", "volume"])
    writer.writeheader()
    for _, row in df.iterrows():
        writer.writerow({
            "date": row["date"].strftime("%Y-%m-%d"),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        })
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# load_ohlcv_from_csv
# ---------------------------------------------------------------------------

class TestLoadOhlcvFromCsv:
    def test_normal_load(self):
        df = _make_ohlcv(30)
        path = _make_csv_file(df)
        result = load_ohlcv_from_csv(path, "2024-01-01", "2024-12-31")
        assert len(result) == 30
        assert list(result.columns[:6]) == ["date", "open", "high", "low", "close", "volume"]

    def test_date_filter(self):
        df = _make_ohlcv(30)
        path = _make_csv_file(df)
        # 첫 10영업일만 포함
        result = load_ohlcv_from_csv(path, "2024-01-01", "2024-01-12")
        assert len(result) <= 10
        assert len(result) > 0

    def test_empty_range(self):
        df = _make_ohlcv(10)
        path = _make_csv_file(df)
        result = load_ohlcv_from_csv(path, "2025-01-01", "2025-12-31")
        assert result.empty

    def test_missing_date_column_raises(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        writer = csv.DictWriter(tmp, fieldnames=["open", "close"])
        writer.writeheader()
        writer.writerow({"open": 100, "close": 110})
        tmp.close()
        with pytest.raises(ValueError, match="date"):
            load_ohlcv_from_csv(tmp.name, "2024-01-01", "2024-12-31")


# ---------------------------------------------------------------------------
# _generate_signals
# ---------------------------------------------------------------------------

class TestGenerateSignals:
    def test_insufficient_data_returns_hold(self):
        df = _make_ohlcv(10)
        result = _generate_signals(df)
        assert (result["signal"] == "HOLD").all()
        assert (result["signal_reason"] == "데이터 부족").all()

    def test_sufficient_data_has_signal_column(self):
        df = _make_ohlcv(60)
        result = _generate_signals(df)
        assert "signal" in result.columns
        assert "signal_reason" in result.columns
        assert set(result["signal"].unique()).issubset({"BUY", "SELL", "HOLD"})

    def test_first_row_is_hold(self):
        df = _make_ohlcv(60)
        result = _generate_signals(df)
        # 첫 행은 전일 데이터 없으므로 HOLD
        assert result.iloc[0]["signal"] == "HOLD"

    def test_nan_rows_become_hold(self):
        """지표가 NaN인 초기 행들은 HOLD가 되어야 한다."""
        df = _make_ohlcv(60)
        result = _generate_signals(df)
        # MA5는 5행부터, MACD slow는 26행부터 유효 — 그 전은 HOLD
        early_rows = result.iloc[1:5]
        assert (early_rows["signal"] == "HOLD").all()


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

class TestSimulate:
    def test_no_trades_when_only_hold(self):
        """모든 신호가 HOLD면 거래가 없어야 한다."""
        df = _make_ohlcv(30)
        df["signal"] = "HOLD"
        df["signal_reason"] = "test"
        trades, equity = simulate("005930", df, 10_000_000)
        # 마지막 날 강제 청산도 포지션이 없으면 발생하지 않음
        buy_trades = [t for t in trades if t.action == "BUY"]
        assert len(buy_trades) == 0
        assert len(equity) == len(df)

    def test_buy_then_sell_cycle(self):
        """매수 후 매도 1회 사이클에서 P&L이 계산되어야 한다."""
        df = _make_ohlcv(10)
        df["signal"] = "HOLD"
        df["signal_reason"] = "test"
        # 3일째 BUY, 7일째 SELL
        df.loc[2, "signal"] = "BUY"
        df.loc[2, "signal_reason"] = "test buy"
        df.loc[6, "signal"] = "SELL"
        df.loc[6, "signal_reason"] = "test sell"

        trades, equity = simulate("005930", df, 10_000_000)
        buy_t = [t for t in trades if t.action == "BUY"]
        sell_t = [t for t in trades if t.action == "SELL"]
        assert len(buy_t) == 1
        assert len(sell_t) == 1
        # 가격이 상승 추세이므로 이익이어야 함
        assert sell_t[0].pnl > 0

    def test_fee_deducted_from_pnl(self):
        """수수료/거래세가 P&L에서 차감되어야 한다."""
        df = _make_ohlcv(5)
        df["signal"] = "HOLD"
        df["signal_reason"] = "test"
        df.loc[0, "signal"] = "BUY"
        df.loc[4, "signal"] = "SELL"

        trades, _ = simulate("005930", df, 10_000_000)
        sell_t = [t for t in trades if t.action == "SELL"][0]
        # fee > 0 이어야 함
        assert sell_t.fee > 0

    def test_equity_curve_length(self):
        df = _make_ohlcv(20)
        df["signal"] = "HOLD"
        df["signal_reason"] = "test"
        _, equity = simulate("005930", df, 10_000_000)
        assert len(equity) == len(df)

    def test_forced_liquidation_on_last_day(self):
        """마지막 날에 포지션이 있으면 강제 청산해야 한다."""
        df = _make_ohlcv(5)
        df["signal"] = "HOLD"
        df["signal_reason"] = "test"
        df.loc[0, "signal"] = "BUY"
        # 명시적 SELL 없음

        trades, _ = simulate("005930", df, 10_000_000)
        sell_t = [t for t in trades if t.action == "SELL"]
        assert len(sell_t) == 1
        assert "강제 청산" in sell_t[0].reason


# ---------------------------------------------------------------------------
# calc_metrics
# ---------------------------------------------------------------------------

class TestCalcMetrics:
    def _make_sell_trade(self, pnl: float) -> TradeRecord:
        return TradeRecord(
            date="2024-06-01",
            action="SELL",
            price=10000,
            qty=10,
            amount=100000,
            fee=195,
            pnl=pnl,
            reason="test",
        )

    def test_total_return(self):
        equity = [10_000_000, 10_500_000, 11_000_000]
        trades = [self._make_sell_trade(1_000_000)]
        m = calc_metrics(trades, equity, 10_000_000)
        assert m["total_return_pct"] == pytest.approx(10.0, abs=0.01)

    def test_max_drawdown(self):
        equity = [10_000_000, 9_000_000, 8_000_000, 9_500_000]
        trades = []
        m = calc_metrics(trades, equity, 10_000_000)
        # 10M → 8M: 20% drawdown
        assert m["max_drawdown_pct"] == pytest.approx(20.0, abs=0.01)

    def test_win_rate(self):
        trades = [
            self._make_sell_trade(1000),
            self._make_sell_trade(2000),
            self._make_sell_trade(-500),
        ]
        equity = [10_000_000] * 10
        m = calc_metrics(trades, equity, 10_000_000)
        assert m["win_rate"] == pytest.approx(66.67, abs=0.1)
        assert m["win_count"] == 2
        assert m["loss_count"] == 1

    def test_no_trades(self):
        equity = [10_000_000] * 5
        m = calc_metrics([], equity, 10_000_000)
        assert m["total_trades"] == 0
        assert m["win_rate"] == 0.0

    def test_sharpe_positive_trend(self):
        """우상향 equity curve는 양수 샤프 비율이어야 한다."""
        equity = [10_000_000 + i * 100_000 for i in range(50)]
        trades = [self._make_sell_trade(5_000_000)]
        m = calc_metrics(trades, equity, 10_000_000)
        assert m["sharpe_ratio"] > 0
