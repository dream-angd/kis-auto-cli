"""부팅 시 잔고 조회 1회 공유 통합 테스트.

문제: scalp 종목 N개일 때 _build_monitors가 ScalpMonitor를 N개 생성하면서
각자 get_holdings()를 호출 → KIS API에 N번 직렬 요청 → 부팅 3~6초 지연.

해결: _build_monitors에서 get_holdings를 1회만 호출하고 결과를
ScalpMonitor.__init__에 holdings 인자로 주입한다. ScalpMonitor는
주입된 holdings가 있으면 _reconcile_with_holdings에서 fetch 생략.
"""
from unittest.mock import patch

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
    yield
    risk._reset_for_test()


def test_scalp_monitor_uses_prefetched_holdings(isolated_state):
    """ScalpMonitor(code, holdings=[...])에 holdings를 주입하면 get_holdings 호출 안 함."""
    from src.scalper import ScalpMonitor

    holdings_calls = {"n": 0}

    def counting_get_holdings():
        holdings_calls["n"] += 1
        return []

    prefetched = [
        {"stock_code": "005930", "quantity": 0, "avg_price": 0},
    ]
    with patch("src.scalper.get_holdings", side_effect=counting_get_holdings):
        m = ScalpMonitor("005930", holdings=prefetched)

    assert holdings_calls["n"] == 0, (
        f"prefetched holdings 주입 시 get_holdings 호출 0회여야 함 "
        f"(실제 {holdings_calls['n']}회)"
    )
    assert m.stock_code == "005930"


def test_scalp_monitor_falls_back_when_no_prefetch(isolated_state):
    """holdings 미주입 시 기존 동작대로 get_holdings를 호출한다 (하위 호환)."""
    from src.scalper import ScalpMonitor

    holdings_calls = {"n": 0}

    def counting_get_holdings():
        holdings_calls["n"] += 1
        return []

    with patch("src.scalper.get_holdings", side_effect=counting_get_holdings):
        ScalpMonitor("005930")

    assert holdings_calls["n"] == 1, "holdings 미주입 시 기존대로 1회 호출"


def test_build_monitors_prefetches_holdings_once_for_n_codes(monkeypatch, isolated_state):
    """_build_monitors가 N개 종목을 만들어도 get_holdings를 1회만 호출한다."""
    from src import combined

    monkeypatch.setenv("SCALP_STOCKS", "005930,000660,035720,005380,247540,042660")

    holdings_calls = {"n": 0}

    def counting_get_holdings():
        holdings_calls["n"] += 1
        return []

    with patch("src.scalper.get_holdings", side_effect=counting_get_holdings):
        with patch("src.combined.get_holdings", side_effect=counting_get_holdings):
            monitors = combined._build_monitors(None)

    assert len(monitors) == 6
    assert holdings_calls["n"] == 1, (
        f"_build_monitors는 get_holdings를 1회만 호출해야 함 "
        f"(6 종목, 실제 {holdings_calls['n']}회)"
    )


def test_build_monitors_tolerates_holdings_fetch_failure(monkeypatch, isolated_state):
    """_build_monitors의 prefetch 실패 시 ScalpMonitor 생성은 계속되어야 한다.

    개별 monitor가 자기 reconcile에서 다시 시도하거나 빈 state로 진행.
    부팅 자체가 막히면 안 됨.
    """
    from src import combined

    monkeypatch.setenv("SCALP_STOCKS", "005930,000660")

    def fail_once():
        raise RuntimeError("network blip")

    # combined의 prefetch는 실패하지만 monitor 자체는 fallback fetch (또는 빈 holdings)로 동작
    with patch("src.combined.get_holdings", side_effect=fail_once):
        with patch("src.scalper.get_holdings", return_value=[]):
            monitors = combined._build_monitors(None)

    assert len(monitors) == 2
