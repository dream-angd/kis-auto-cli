import json
import pytest
from datetime import date, datetime

from src.scheduler import _check_circuit_breaker, _load_state, _save_state


# --- 헬퍼: datetime 패치용 서브클래스 ---

class _FakeDatetime(datetime):
    _fake_now: datetime = datetime(2026, 4, 28, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._fake_now


# --- is_market_open ---

def test_is_market_open_during_hours(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 4, 28, 10, 0, 0)  # 화요일 10:00
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is True


def test_is_market_open_before_market(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 4, 28, 8, 30, 0)  # 화요일 08:30
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is False


def test_is_market_open_after_market(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 4, 28, 16, 0, 0)  # 화요일 16:00
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is False


def test_is_market_open_weekend(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 5, 2, 10, 0, 0)  # 토요일
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is False


def test_is_market_open_boundary_start(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 4, 28, 9, 10, 0)  # 화요일 09:10 정각
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is True


def test_is_market_open_boundary_end(monkeypatch):
    from src import scheduler
    _FakeDatetime._fake_now = datetime(2026, 4, 28, 15, 30, 0)  # 화요일 15:30 정각
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)
    assert scheduler.is_market_open() is True


# --- _check_circuit_breaker ---

def test_check_circuit_breaker_daily_loss_triggered(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    state = {"daily_loss": -150000, "consecutive_losses": 1}
    assert _check_circuit_breaker(state) is True


def test_check_circuit_breaker_consecutive_triggered(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    state = {"daily_loss": -10000, "consecutive_losses": 3}
    assert _check_circuit_breaker(state) is True


def test_check_circuit_breaker_not_triggered(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    state = {"daily_loss": -50000, "consecutive_losses": 2}
    assert _check_circuit_breaker(state) is False


def test_check_circuit_breaker_zero_state(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    state = {"daily_loss": 0, "consecutive_losses": 0}
    assert _check_circuit_breaker(state) is False


def test_check_circuit_breaker_small_profit_no_trigger(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "100000")
    monkeypatch.setenv("MAX_CONSECUTIVE_LOSSES", "3")
    # abs(50000) = 50000 < 100000 → 트리거 안 됨
    state = {"daily_loss": 50000, "consecutive_losses": 0}
    assert _check_circuit_breaker(state) is False


# --- _load_state / _save_state ---

def test_load_state_no_file(tmp_path, monkeypatch):
    from src import config
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    state = _load_state()
    assert state["daily_loss"] == 0
    assert state["consecutive_losses"] == 0
    assert state["date"] == date.today().isoformat()


def test_load_state_corrupted_file(tmp_path, monkeypatch):
    from src import config
    state_file = tmp_path / "state.json"
    state_file.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    state = _load_state()
    assert state["daily_loss"] == 0


def test_load_state_stale_date(tmp_path, monkeypatch):
    from src import config
    state_file = tmp_path / "state.json"
    old_state = {"date": "2020-01-01", "daily_loss": -99999, "consecutive_losses": 5}
    state_file.write_text(json.dumps(old_state), encoding="utf-8")
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    state = _load_state()
    # 날짜 불일치 → 초기화
    assert state["daily_loss"] == 0
    assert state["date"] == date.today().isoformat()


def test_save_load_state_roundtrip(tmp_path, monkeypatch):
    from src import config
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    original = {
        "date": date.today().isoformat(),
        "daily_loss": -30000,
        "consecutive_losses": 2,
    }
    _save_state(original)
    loaded = _load_state()
    assert loaded["daily_loss"] == -30000
    assert loaded["consecutive_losses"] == 2


def test_save_state_creates_parent_dir(tmp_path, monkeypatch):
    from src import config
    state_file = tmp_path / "subdir" / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    state = {"date": date.today().isoformat(), "daily_loss": 0, "consecutive_losses": 0}
    _save_state(state)
    assert state_file.exists()
