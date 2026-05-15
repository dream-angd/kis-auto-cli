"""Swing/Scalp interval을 .env에서 읽는지 검증.

기존: kis-trader.bat이 사용자에게 매번 interval을 묻고 CLI 인자로 넘겼음.
변경: .bat은 인자 없이 호출하고 main.py도 default=None → run_loop/run_all_loop에서
config.get_swing_interval_sec() / get_scalp_interval_sec() fallback.
"""
import pytest


def test_swing_interval_env_default(monkeypatch):
    """SWING_INTERVAL_SEC env 미설정 시 기본 300초."""
    monkeypatch.delenv("SWING_INTERVAL_SEC", raising=False)
    from src import config
    assert config.get_swing_interval_sec() == 300


def test_swing_interval_env_override(monkeypatch):
    monkeypatch.setenv("SWING_INTERVAL_SEC", "180")
    from src import config
    assert config.get_swing_interval_sec() == 180


def test_swing_interval_env_minimum_clamped(monkeypatch):
    """5초 미만 입력은 5초로 clamp (heartbeat과 동일 정책)."""
    monkeypatch.setenv("SWING_INTERVAL_SEC", "1")
    from src import config
    assert config.get_swing_interval_sec() >= 5


def test_scalp_interval_env_already_supported(monkeypatch):
    """SCALP_INTERVAL_SEC은 기존부터 env 지원 — 회귀 검증."""
    monkeypatch.setenv("SCALP_INTERVAL_SEC", "2.0")
    from src import config
    assert config.get_scalp_interval_sec() == 2.0
