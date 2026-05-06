"""1차 안전장치 테스트:
- MAX_TOTAL_EXPOSURE: swing/scalp 매수 전 노출 한도 검증
- real 모드 체결 추정 fallback 차단 (mock은 유지)
"""
from unittest.mock import patch

import pytest


# ───────────────────── MAX_TOTAL_EXPOSURE ─────────────────────


def test_max_total_exposure_default_zero(monkeypatch):
    """기본값 0이면 cap 비활성."""
    monkeypatch.delenv("MAX_TOTAL_EXPOSURE", raising=False)
    from src import config
    assert config.get_max_total_exposure() == 0


def test_max_total_exposure_env(monkeypatch):
    """env 값 정상 파싱."""
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE", "15000000")
    from src import config
    assert config.get_max_total_exposure() == 15000000


def test_scalp_buy_blocked_when_exposure_exceeded(tmp_path, monkeypatch):
    """현재 보유 평가 + 신규 주문 > MAX_TOTAL_EXPOSURE면 _enter_position 호출 X."""
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()

    scalp_state_dir = tmp_path / "scalp_states"
    scalp_state_dir.mkdir()
    monkeypatch.setattr(
        config, "get_scalp_state_path",
        lambda code="": scalp_state_dir / f"scalp_state_{code or 'default'}.json"
    )
    monkeypatch.setenv("SCALP_STOCKS", "005930")
    monkeypatch.setenv("SCALP_MAX_BUY_AMOUNT", "2000000")
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE", "10000000")

    # 이미 9백만 보유 → 신규 200만 = 11M으로 한도 초과
    fake_holdings = [
        {"stock_code": "035720", "current_price": 50000, "quantity": 180}  # 9,000,000
    ]

    with patch("src.scalper.get_holdings", return_value=fake_holdings):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")

        # KIS API mock
        with patch.object(m, "_buy_signal", return_value=(True, "test")):
            with patch("src.scalper.buy") as mock_buy:
                m.run_once = m.run_once  # 보장
                # 직접 _enter_position 호출
                with patch("src.scalper.get_current_price", return_value={"price": 50000}):
                    m._enter_position(50000, "test")
                # buy()가 호출되지 않아야 함
                assert mock_buy.call_count == 0


def test_scalp_buy_allowed_when_exposure_within_cap(tmp_path, monkeypatch):
    """노출 한도 내면 정상 진입."""
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()

    scalp_state_dir = tmp_path / "scalp_states"
    scalp_state_dir.mkdir()
    monkeypatch.setattr(
        config, "get_scalp_state_path",
        lambda code="": scalp_state_dir / f"scalp_state_{code or 'default'}.json"
    )
    monkeypatch.setenv("SCALP_STOCKS", "005930")
    monkeypatch.setenv("SCALP_MAX_BUY_AMOUNT", "2000000")
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE", "20000000")
    monkeypatch.setenv("SCALP_TRADE_ENABLED", "false")  # paper 모드로

    # 이미 5백만 보유 → 신규 200만 = 7M, 한도 20M 안에 OK
    fake_holdings = [
        {"stock_code": "035720", "current_price": 50000, "quantity": 100}  # 5,000,000
    ]

    with patch("src.scalper.get_holdings", return_value=fake_holdings):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")
        m._enter_position(50000, "test entry within cap")

    # state 갱신 확인 (paper 모드라 state만 변경)
    assert m.state["position_qty"] > 0


def test_max_total_exposure_zero_disables_check(tmp_path, monkeypatch):
    """MAX_TOTAL_EXPOSURE=0이면 cap 검증 자체 안 함."""
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()

    scalp_state_dir = tmp_path / "scalp_states"
    scalp_state_dir.mkdir()
    monkeypatch.setattr(
        config, "get_scalp_state_path",
        lambda code="": scalp_state_dir / f"scalp_state_{code or 'default'}.json"
    )
    monkeypatch.setenv("SCALP_STOCKS", "005930")
    monkeypatch.setenv("SCALP_MAX_BUY_AMOUNT", "2000000")
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE", "0")
    monkeypatch.setenv("SCALP_TRADE_ENABLED", "false")

    # 거대한 보유 — cap이 활성이었다면 차단될 것
    fake_holdings = [
        {"stock_code": "035720", "current_price": 100000, "quantity": 10000}  # 10억
    ]
    with patch("src.scalper.get_holdings", return_value=fake_holdings):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")
        m._enter_position(50000, "test entry no cap")

    # cap 비활성이라 진입됨 (paper 모드 state)
    assert m.state["position_qty"] > 0


# ───────────────────── real 모드 체결 추정 차단 ─────────────────────


def test_buy_real_mode_unknown_fill_no_estimate(monkeypatch):
    """real 모드에서 체결조회 실패 시 estimated=True가 아니라 unknown_fill=True."""
    monkeypatch.setenv("MODE", "real")
    monkeypatch.setenv("KIS_APP_KEY", "x")
    monkeypatch.setenv("KIS_APP_SECRET", "x")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")

    from src import trader

    # 주문 성공, 체결조회 실패 시뮬
    monkeypatch.setattr(
        trader,
        "_order_request",
        lambda *a, **k: {"output": {"ODNO": "12345"}, "rt_cd": "0"},
    )
    monkeypatch.setattr(trader, "_try_fetch_fill", lambda odno, code: None)

    result = trader.buy("005930", 1000000, current_price=50000)
    assert result["estimated"] is False, "real 모드에선 estimated 추정 금지"
    assert result["filled_qty"] == 0, "체결 미확정 = filled_qty 0"
    assert result["unknown_fill"] is True
    assert result["fully_filled"] is False


def test_sell_real_mode_unknown_fill_no_estimate(monkeypatch):
    """real 모드에서 sell도 동일 — estimated 아닌 unknown_fill."""
    monkeypatch.setenv("MODE", "real")
    monkeypatch.setenv("KIS_APP_KEY", "x")
    monkeypatch.setenv("KIS_APP_SECRET", "x")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")

    from src import trader

    monkeypatch.setattr(
        trader,
        "_order_request",
        lambda *a, **k: {"output": {"ODNO": "12345"}, "rt_cd": "0"},
    )
    monkeypatch.setattr(trader, "_try_fetch_fill", lambda odno, code: None)

    result = trader.sell("005930", 10, current_price=50000)
    assert result["estimated"] is False
    assert result["filled_qty"] == 0
    assert result["unknown_fill"] is True


def test_buy_mock_mode_keeps_estimate_fallback(monkeypatch):
    """mock 모드는 기존처럼 estimated=True fallback 유지 (운영 편의)."""
    monkeypatch.setenv("MODE", "mock")
    monkeypatch.setenv("KIS_MOCK_APP_KEY", "x")
    monkeypatch.setenv("KIS_MOCK_APP_SECRET", "x")
    monkeypatch.setenv("KIS_MOCK_ACCOUNT_NO", "12345678-01")

    from src import trader

    monkeypatch.setattr(
        trader,
        "_order_request",
        lambda *a, **k: {"output": {"ODNO": "12345"}, "rt_cd": "0"},
    )
    monkeypatch.setattr(trader, "_try_fetch_fill", lambda odno, code: None)

    result = trader.buy("005930", 1000000, current_price=50000)
    assert result["estimated"] is True, "mock 모드는 fallback 유지"
    assert result["filled_qty"] > 0
    assert result.get("unknown_fill") is None or result.get("unknown_fill") is not True


# ───────────────────── SELL_TAX_RATE 변경 검증 ─────────────────────


def test_sell_tax_rate_default_is_0020(monkeypatch):
    """SELL_TAX_RATE 기본값이 0.0020 (2026년 기준)."""
    monkeypatch.delenv("SELL_TAX_RATE", raising=False)
    from src import config
    assert config.get_sell_tax_rate() == 0.0020


def test_sell_tax_rate_env_override(monkeypatch):
    """env로 다른 값 지정 가능."""
    monkeypatch.setenv("SELL_TAX_RATE", "0.0015")
    from src import config
    assert config.get_sell_tax_rate() == 0.0015
