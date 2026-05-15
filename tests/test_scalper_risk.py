"""scalper × risk.py 통합 테스트.

시나리오:
- scalp 청산 시 risk.record_realized_pnl 호출되어 daily_loss에 누적
- daily_loss 한도 초과 상태에서 buy 신호여도 _enter_position 호출 안 됨
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def isolated_risk_state(tmp_path, monkeypatch):
    """각 테스트마다 risk state 격리."""
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()

    # scalp_state도 격리
    scalp_state_dir = tmp_path / "scalp_states"
    scalp_state_dir.mkdir()
    monkeypatch.setattr(
        config,
        "get_scalp_state_path",
        lambda code="": scalp_state_dir / f"scalp_state_{code or 'default'}.json",
    )

    monkeypatch.setenv("SCALP_STOCKS", "005930")
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    yield
    risk._reset_for_test()


def _build_monitor_with_position(stock_code="005930", entry_price=50000, qty=10):
    """포지션 있는 ScalpMonitor 인스턴스를 mock 사용해 생성."""
    with patch("src.scalper.get_holdings", return_value=[]):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor(stock_code)
    m.state = {
        "date": "2026-05-06",
        "mode": "mock",
        "stock_code": stock_code,
        "position_qty": qty,
        "entry_price": entry_price,
        "high_price": entry_price,
        "entry_time": 0,
    }
    return m


def test_scalp_exit_records_pnl_to_daily_loss(isolated_risk_state, monkeypatch):
    """scalp 손실 청산 시 risk.daily_loss에 음수 누적."""
    from src import risk
    from src.scalper import ScalpMonitor

    monkeypatch.setattr("src.scalper.config.is_scalp_trade_enabled", lambda: False)  # paper 모드

    m = _build_monitor_with_position(entry_price=50000, qty=10)
    # 청산가 49,500 = -1.0% 손실
    # 매수비용 50000*10*0.00015 = 75
    # 매도비용 49500*10*(0.00015 + 0.0018) = 96.5...
    # gross = -5000, pnl 약 -5000 - 75 - 96 = ~-5171
    m._exit_position(49500, "test exit (loss)")

    state = risk.load_state()
    assert state["daily_loss"] < 0
    assert state["losses"] == 1
    assert state["wins"] == 0


def test_scalp_exit_records_win(isolated_risk_state, monkeypatch):
    """scalp 익절 청산 시 wins +1 + daily_loss 양수."""
    from src import risk

    monkeypatch.setattr("src.scalper.config.is_scalp_trade_enabled", lambda: False)

    m = _build_monitor_with_position(entry_price=50000, qty=10)
    # 청산가 51,000 = +2.0%
    m._exit_position(51000, "test exit (win)")

    state = risk.load_state()
    assert state["daily_loss"] > 0
    assert state["wins"] == 1
    assert state["losses"] == 0


def test_buy_blocked_when_daily_loss_limit_hit(isolated_risk_state, monkeypatch):
    """daily_loss 한도 초과 상태에서 buy_signal True여도 _enter_position 호출 안 됨."""
    from src import risk

    # 시간 의존성 제거 — 마감 임박 차단(SCALP_NO_NEW_BUY_BEFORE_CLOSE_MIN)이 발동하지 않게
    # 0으로 비활성화. 이 테스트는 daily_loss 한도 동작만 검증.
    monkeypatch.setenv("SCALP_NO_NEW_BUY_BEFORE_CLOSE_MIN", "0")
    monkeypatch.setenv("SCALP_FORCE_CLOSE_BEFORE_CLOSE_MIN", "0")

    # 한도 초과 만들기
    risk.record_realized_pnl("scalp", -150000)  # MAX_DAILY_LOSS=100000
    assert risk.is_daily_loss_limit_hit() is True

    # 가격 조회/포지션 mock
    with patch("src.scalper.get_holdings", return_value=[]):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")

    # _enter_position이 호출되는지 추적
    enter_called = []
    monkeypatch.setattr(m, "_enter_position", lambda *a, **k: enter_called.append(True))
    # _buy_signal은 항상 True 반환하도록 조작
    monkeypatch.setattr(m, "_buy_signal", lambda price: (True, "forced buy signal"))
    # get_current_price mock
    monkeypatch.setattr(
        "src.scalper.get_current_price",
        lambda code: {"price": 50000},
    )

    m.run_once()
    assert enter_called == [], "한도 초과 상태에선 _enter_position이 호출되지 않아야 함"


def test_buy_allowed_when_daily_loss_below_limit(isolated_risk_state, monkeypatch):
    """daily_loss 한도 미만이면 평소처럼 buy 가능."""
    from src import risk

    # 시간 의존성 제거 — 마감 임박 차단이 발동하지 않게 비활성화
    monkeypatch.setenv("SCALP_NO_NEW_BUY_BEFORE_CLOSE_MIN", "0")
    monkeypatch.setenv("SCALP_FORCE_CLOSE_BEFORE_CLOSE_MIN", "0")

    risk.record_realized_pnl("scalp", -50000)  # 한도 100000의 절반
    assert risk.is_daily_loss_limit_hit() is False

    with patch("src.scalper.get_holdings", return_value=[]):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")

    enter_called = []
    monkeypatch.setattr(m, "_enter_position", lambda *a, **k: enter_called.append(True))
    monkeypatch.setattr(m, "_buy_signal", lambda price: (True, "forced buy signal"))
    monkeypatch.setattr(
        "src.scalper.get_current_price",
        lambda code: {"price": 50000},
    )

    # 가격 윈도우 채우기 (warming up 통과 — 사실 _buy_signal mock이라 무관)
    m.run_once()
    assert enter_called == [True], "한도 미만이면 매수 신호에 따라 진입해야 함"


def test_heartbeat_shows_realized_pnl_and_wl(isolated_risk_state, monkeypatch):
    """heartbeat에 오늘 실현손익 / Daily Loss 사용 / W-L가 표시된다."""
    from src import risk
    from src.combined import _format_heartbeat

    # 거래 시뮬: 2승 3패, 누적 -7,500원
    risk.record_realized_pnl("scalp", 5000)
    risk.record_realized_pnl("scalp", -3000)
    risk.record_realized_pnl("scalp", -4000)
    risk.record_realized_pnl("scalp", 2000)
    risk.record_realized_pnl("scalp", -7500)

    # 가짜 monitors + balance
    with patch("src.scalper.get_holdings", return_value=[]):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")
    m.last_price = 50000
    fake_balance = {"cash": 50000000, "total_eval": 49992500, "profit_loss": 0}

    out = _format_heartbeat([m], balance=fake_balance, swing_holdings=None)
    # idle 컴팩트 모드: 미실현/오늘 자산변화는 노이즈로 생략, 핵심 지표만 1줄
    assert "실현" in out  # 자체 실현 손익 라인
    assert "-7,500" in out  # 자체 실현 손익 값
    assert "W/L 2/3" in out
    assert "총 5건" in out


def test_heartbeat_shows_limit_warning_when_exceeded(isolated_risk_state, monkeypatch):
    """daily_loss 한도 초과 시 heartbeat에 ⚠ 표시."""
    from src import risk
    from src.combined import _format_heartbeat

    risk.record_realized_pnl("scalp", -150000)  # 한도 100,000 초과
    assert risk.is_daily_loss_limit_hit() is True

    with patch("src.scalper.get_holdings", return_value=[]):
        from src.scalper import ScalpMonitor
        m = ScalpMonitor("005930")
    m.last_price = 50000
    fake_balance = {"cash": 50000000, "total_eval": 49850000, "profit_loss": 0}

    out = _format_heartbeat([m], balance=fake_balance, swing_holdings=None)
    assert "한도 초과" in out
