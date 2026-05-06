"""주기적 reconcile 통합 테스트.

분석가 권고: HTS에서 직접 매매하거나 KIS 측 desync 발생 시
다음 unknown_fill까지 발견 못함. heartbeat 또는 N분 간격 reconcile로 보강.

설계: combined.run_*_loop에 next_reconcile_at 시점을 두고
RECONCILE_INTERVAL_SEC(기본 300초)마다 모든 monitor의 state를
get_holdings 1회 호출 결과로 reconcile한다.
"""
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()
    scalp_dir = tmp_path / "scalp_states"
    scalp_dir.mkdir()
    monkeypatch.setattr(
        config, "get_scalp_state_path",
        lambda code="": scalp_dir / f"scalp_state_{code or 'default'}.json",
    )
    monkeypatch.setenv("SCALP_STOCKS", "005930,000660")
    yield
    risk._reset_for_test()


def test_reconcile_interval_default():
    """RECONCILE_INTERVAL_SEC 기본값은 300초."""
    from src import config
    # env 미설정 상태에서 300이 기본
    import os
    os.environ.pop("RECONCILE_INTERVAL_SEC", None)
    assert config.get_reconcile_interval_sec() == 300


def test_reconcile_interval_env_override(monkeypatch):
    """env override 가능."""
    monkeypatch.setenv("RECONCILE_INTERVAL_SEC", "60")
    from src import config
    assert config.get_reconcile_interval_sec() == 60


def test_reconcile_all_monitors_uses_single_holdings_call(isolated_state):
    """combined._reconcile_all_monitors는 get_holdings를 1회만 호출한다."""
    from src.combined import _reconcile_all_monitors
    from src.scalper import ScalpMonitor

    holdings_call_count = {"n": 0}

    def mock_holdings():
        holdings_call_count["n"] += 1
        return [
            {"stock_code": "005930", "quantity": 5, "avg_price": 70000, "current_price": 70000, "profit_rate": 0.0, "profit_loss": 0},
        ]

    with patch("src.scalper.get_holdings", side_effect=mock_holdings):
        m1 = ScalpMonitor("005930")
        m2 = ScalpMonitor("000660")

    holdings_call_count["n"] = 0  # init 호출은 카운트에서 제외

    with patch("src.trader.get_holdings", side_effect=mock_holdings):
        with patch("src.combined.get_holdings", side_effect=mock_holdings, create=True):
            _reconcile_all_monitors([m1, m2])

    assert holdings_call_count["n"] == 1, (
        f"_reconcile_all_monitors는 get_holdings를 1회만 호출해야 함 "
        f"(실제 {holdings_call_count['n']}회)"
    )


def test_reconcile_syncs_external_sell(isolated_state):
    """HTS에서 005930을 직접 매도해 actual=0이 되면 monitor state도 0으로 동기화."""
    from src.combined import _reconcile_all_monitors
    from src.scalper import ScalpMonitor

    with patch("src.scalper.get_holdings", return_value=[]):
        m = ScalpMonitor("005930")

    # 모의 매수 상태 강제 주입
    m.state["position_qty"] = 3
    m.state["entry_price"] = 70000

    # HTS에서 매도된 것처럼 holdings에 005930이 없는 상태로 reconcile
    with patch("src.combined.get_holdings", return_value=[], create=True):
        _reconcile_all_monitors([m])

    assert m.state["position_qty"] == 0, "외부 매도 후 state.position_qty=0이어야"
