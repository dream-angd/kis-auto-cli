"""Graceful shutdown 시그널 핸들러 등록 헬퍼.

기존에는 run_loop마다 signal.SIGINT만 등록되어 있어
- 작업 스케줄러/컨테이너 SIGTERM
- Windows Ctrl+Break (SIGBREAK)
가 오면 graceful shutdown 없이 강제 종료됐다.

install_shutdown_handlers(callback)는 SIGINT/SIGTERM/(SIGBREAK if Windows)에
같은 콜백을 등록하고 이전 핸들러 dict를 반환한다.
restore_handlers(prev)는 finally에서 원복한다.
"""
import signal


_TARGETS = ["SIGINT", "SIGTERM", "SIGBREAK"]


def install_shutdown_handlers(callback):
    """SIGINT/SIGTERM/SIGBREAK에 callback을 등록하고 이전 핸들러 dict 반환.

    플랫폼이 지원하지 않거나 등록 실패한 시그널은 조용히 skip한다.
    SIGBREAK는 Windows에만 존재하고, SIGTERM은 일부 임베디드 환경에서
    raise ValueError가 날 수 있다.
    """
    prev = {}
    for name in _TARGETS:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            prev[sig] = signal.signal(sig, callback)
        except (ValueError, OSError):
            # 메인 스레드 외부 호출이나 미지원 플랫폼 — 조용히 skip
            continue
    return prev


def restore_handlers(prev):
    """install_shutdown_handlers가 반환한 dict로 핸들러를 원복."""
    for sig, handler in prev.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            continue
