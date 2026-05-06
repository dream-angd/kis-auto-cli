"""SIGTERM/SIGBREAK 시그널 핸들러 등록 테스트.

분석가 권고: 현재 SIGINT만 등록되어 있어 작업 스케줄러나 컨테이너 환경에서
SIGTERM이 오면 graceful shutdown 없이 강제 종료된다. Windows의 Ctrl+Break
역시 처리되지 않는다.

설계: install_shutdown_handlers(callback) 헬퍼를 만들고 모든 run_loop에서
재사용한다. 이전 핸들러를 반환해 finally에서 복원한다.
"""
import signal
from unittest.mock import patch

import pytest


def test_install_shutdown_handlers_registers_sigint_and_sigterm():
    """SIGINT과 SIGTERM 둘 다 같은 콜백으로 등록된다."""
    from src.signals import install_shutdown_handlers, restore_handlers

    captured = {}

    def fake_signal(sig, handler):
        captured[sig] = handler
        return signal.SIG_DFL

    callback = lambda sig, frame: None
    with patch("signal.signal", side_effect=fake_signal):
        prev = install_shutdown_handlers(callback)

    assert signal.SIGINT in captured
    assert signal.SIGTERM in captured
    assert captured[signal.SIGINT] is callback
    assert captured[signal.SIGTERM] is callback
    # 복원용 prev dict가 반환됨
    assert isinstance(prev, dict)
    assert signal.SIGINT in prev
    assert signal.SIGTERM in prev


def test_install_shutdown_handlers_registers_sigbreak_when_available():
    """Windows에서 SIGBREAK가 있으면 등록되고, 없으면 조용히 skip된다."""
    from src.signals import install_shutdown_handlers

    captured = {}

    def fake_signal(sig, handler):
        captured[sig] = handler
        return signal.SIG_DFL

    callback = lambda sig, frame: None
    with patch("signal.signal", side_effect=fake_signal):
        install_shutdown_handlers(callback)

    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        assert sigbreak in captured, "Windows에서 SIGBREAK 등록 누락"
        assert captured[sigbreak] is callback
    # POSIX에서는 SIGBREAK 자체가 없으므로 검증 항목 없음 (skip)


def test_install_shutdown_handlers_skips_unsupported_signal():
    """등록 시도가 ValueError(unsupported on this platform)를 던지면 조용히 무시한다."""
    from src.signals import install_shutdown_handlers

    def picky_signal(sig, handler):
        if sig == signal.SIGTERM:
            raise ValueError("unsupported")
        return signal.SIG_DFL

    callback = lambda sig, frame: None
    with patch("signal.signal", side_effect=picky_signal):
        # ValueError를 잡지 못하면 이 호출이 그대로 raise됨
        prev = install_shutdown_handlers(callback)

    # SIGINT는 정상 등록됐어야 한다
    assert signal.SIGINT in prev
    # SIGTERM은 등록 실패했으므로 prev에 없어야 한다
    assert signal.SIGTERM not in prev


def test_restore_handlers_calls_signal_with_prev_handlers():
    """restore_handlers가 prev dict의 모든 시그널을 원래 핸들러로 복원한다."""
    from src.signals import restore_handlers

    fake_handler_int = object()
    fake_handler_term = object()
    prev = {
        signal.SIGINT: fake_handler_int,
        signal.SIGTERM: fake_handler_term,
    }

    captured = {}

    def fake_signal(sig, handler):
        captured[sig] = handler
        return None

    with patch("signal.signal", side_effect=fake_signal):
        restore_handlers(prev)

    assert captured[signal.SIGINT] is fake_handler_int
    assert captured[signal.SIGTERM] is fake_handler_term
