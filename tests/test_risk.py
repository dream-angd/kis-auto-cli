"""src/risk.py 단위 테스트 (TDD).

시나리오:
1. scalp 청산 PnL -13,000이 daily_loss에 누적된다.
2. scalp 청산 PnL +8,000이 승/패 카운트와 실현손익에 반영된다.
3. daily_loss <= -MAX_DAILY_LOSS면 is_daily_loss_limit_hit() True.
4. swing/scalp 양쪽 record_realized_pnl이 같은 state에 누적된다 (전략 합산).
5. record_realized_pnl이 thread-safe하다 (동시 호출 시 누락 없음).
"""
import json
import threading
from datetime import date

import pytest


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """각 테스트마다 독립적인 state 파일 사용."""
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    # lru_cache/모듈 변수 초기화
    risk._reset_for_test()
    yield state_file
    risk._reset_for_test()


def test_scalp_loss_accumulates_to_daily_loss(isolated_state, monkeypatch):
    """시나리오 1: scalp 청산 PnL -13,000이 state daily_loss에 누적."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", -13000)
    state = risk.load_state()
    assert state["daily_loss"] == -13000


def test_scalp_win_updates_counters(isolated_state, monkeypatch):
    """시나리오 2: 익절 PnL +8,000이 승/패 카운트와 실현손익에 반영."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", 8000)
    state = risk.load_state()
    assert state["daily_loss"] == 8000
    assert state["wins"] == 1
    assert state["losses"] == 0


def test_loss_loss_loss_then_win(isolated_state, monkeypatch):
    """연속 손실 + 1회 익절 시 wins/losses 정확히 카운트, daily_loss 누적."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", -5000)
    risk.record_realized_pnl("scalp", -3000)
    risk.record_realized_pnl("scalp", -2000)
    risk.record_realized_pnl("scalp", 8000)

    state = risk.load_state()
    assert state["daily_loss"] == -2000  # -5000 -3000 -2000 +8000
    assert state["wins"] == 1
    assert state["losses"] == 3


def test_daily_loss_limit_hit(isolated_state, monkeypatch):
    """시나리오 3: daily_loss <= -MAX_DAILY_LOSS면 is_daily_loss_limit_hit() True."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", -50000)
    assert risk.is_daily_loss_limit_hit() is False

    risk.record_realized_pnl("scalp", -60000)  # -110000
    assert risk.is_daily_loss_limit_hit() is True


def test_daily_loss_limit_not_hit_on_profit(isolated_state, monkeypatch):
    """수익이 한도(절대값)를 넘어도 한도 도달이 아니다 (이전 부호 버그 회귀 방지)."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", 200000)
    assert risk.is_daily_loss_limit_hit() is False


def test_strategy_aggregation(isolated_state, monkeypatch):
    """시나리오 4: swing과 scalp PnL이 같은 state.daily_loss에 합산."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", -5000)
    risk.record_realized_pnl("swing", -3000)
    risk.record_realized_pnl("scalp", 2000)

    state = risk.load_state()
    assert state["daily_loss"] == -6000


def test_record_pnl_is_thread_safe(isolated_state, monkeypatch):
    """시나리오 5: 100개 thread가 동시에 record_realized_pnl 호출 — 누락 없이 합산."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000000")
    from src import risk

    def worker():
        for _ in range(10):
            risk.record_realized_pnl("scalp", 1)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    state = risk.load_state()
    assert state["daily_loss"] == 1000  # 100 threads × 10 calls × 1
    assert state["wins"] == 1000


def test_state_persists_across_loads(isolated_state, monkeypatch):
    """save → load roundtrip."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import risk

    risk.record_realized_pnl("scalp", -7500)
    risk.record_realized_pnl("scalp", 3000)

    # 메모리 cache 클리어 후 재로드
    risk._reset_for_test(keep_disk=True)
    state = risk.load_state()
    assert state["daily_loss"] == -4500
    assert state["wins"] == 1
    assert state["losses"] == 1


def test_new_day_resets_state(isolated_state, monkeypatch):
    """다른 날짜의 state 파일은 무시되고 새로 시작."""
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    from src import config, risk

    # 어제 날짜 state 파일 작성
    yesterday = "2020-01-01"
    config.get_state_path().parent.mkdir(parents=True, exist_ok=True)
    config.get_state_path().write_text(
        json.dumps({"date": yesterday, "daily_loss": -99999, "wins": 5, "losses": 5}),
        encoding="utf-8",
    )

    risk._reset_for_test(keep_disk=True)
    state = risk.load_state()
    assert state["date"] == date.today().isoformat()
    assert state["daily_loss"] == 0
    assert state["wins"] == 0
    assert state["losses"] == 0
