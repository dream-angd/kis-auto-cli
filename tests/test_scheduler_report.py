"""tests/test_scheduler_report.py — scheduler._maybe_generate_report 단위 테스트.

_maybe_generate_report는 generate_daily_report가 예외를 raise해도
그 예외를 전파하지 않고 log_error로만 처리한다. (design.md 완료 기준:
"When report generation raises an exception, the system shall catch the exception,
write the traceback via log_error, and continue the shutdown sequence without
crashing the process.")
"""
from datetime import datetime

import pytest


# --- 헬퍼: datetime 패치용 서브클래스 ---

class _FakeDatetime(datetime):
    _fake_now: datetime = datetime(2026, 5, 2, 15, 35, 0)  # 장 마감 후

    @classmethod
    def now(cls, tz=None):
        return cls._fake_now


class _FakeDatetimeBeforeClose(datetime):
    _fake_now: datetime = datetime(2026, 5, 2, 11, 0, 0)  # 장 마감 전

    @classmethod
    def now(cls, tz=None):
        return cls._fake_now


# ---------------------------------------------------------------------------
# Error isolation: generate_daily_report raises → _maybe_generate_report
# swallows via log_error and returns None without propagating.
# ---------------------------------------------------------------------------

def test_maybe_generate_report_swallows_exception(monkeypatch):
    """If generate_daily_report raises, _maybe_generate_report must NOT propagate it.

    Design doc: "When report generation raises an exception, the system shall catch
    the exception, write the traceback via log_error, and continue the shutdown
    sequence without crashing the process."
    """
    from src import scheduler

    # Patch datetime so we are after 15:30 (report generation path is taken)
    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)

    # Patch get_account_info to raise so balance fetch fails gracefully
    monkeypatch.setattr(scheduler, "get_account_info", lambda: (_ for _ in ()).throw(RuntimeError("API down")))

    # Patch generate_daily_report (imported inside _maybe_generate_report) to raise
    import src.reporter as reporter_mod
    monkeypatch.setattr(reporter_mod, "generate_daily_report", lambda *a, **kw: (_ for _ in ()).throw(ValueError("report broken")))

    errors_logged = []
    monkeypatch.setattr(scheduler, "log_error", lambda msg: errors_logged.append(msg))
    monkeypatch.setattr(scheduler, "log_info", lambda msg: None)

    # Must not raise — the exception must be swallowed
    result = scheduler._maybe_generate_report()

    assert result is None, "_maybe_generate_report should return None"
    assert any("report broken" in e for e in errors_logged), (
        f"Expected 'report broken' in logged errors, got: {errors_logged}"
    )


def test_maybe_generate_report_before_close_skips(monkeypatch):
    """Before 15:30, _maybe_generate_report logs a skip message and returns without generating.

    Design doc: "When the user sends SIGINT before 15:30 (mid-session interrupt),
    the system shall skip report generation and log a single log_info message."
    """
    from src import scheduler

    monkeypatch.setattr(scheduler, "datetime", _FakeDatetimeBeforeClose)

    infos_logged = []
    monkeypatch.setattr(scheduler, "log_info", lambda msg: infos_logged.append(msg))

    # generate_daily_report must NOT be called — wire it to fail if it is
    import src.reporter as reporter_mod
    monkeypatch.setattr(reporter_mod, "generate_daily_report", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")))

    result = scheduler._maybe_generate_report()

    assert result is None
    assert any("장 마감 전 종료" in m for m in infos_logged), (
        f"Expected skip log_info message, got: {infos_logged}"
    )


def test_maybe_generate_report_after_close_calls_generate(monkeypatch):
    """After 15:30, _maybe_generate_report calls generate_daily_report successfully.

    Design doc: "When run_loop exits after 15:30 detection, the system shall generate
    all 4 report files."
    """
    from src import scheduler

    monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)

    # Fake account info success
    fake_balance = {"total_eval": 1000000, "cash": 500000, "profit_loss": 0}
    fake_holdings: list = []
    monkeypatch.setattr(scheduler, "get_account_info", lambda: (fake_balance, fake_holdings))

    called_with: list = []

    import src.reporter as reporter_mod
    monkeypatch.setattr(
        reporter_mod,
        "generate_daily_report",
        lambda date_str, balance_snapshot=None, holdings_snapshot=None: (
            called_with.append((date_str, balance_snapshot, holdings_snapshot)) or []
        ),
    )

    monkeypatch.setattr(scheduler, "log_info", lambda msg: None)
    monkeypatch.setattr(scheduler, "log_error", lambda msg: None)

    scheduler._maybe_generate_report()

    assert len(called_with) == 1, "generate_daily_report should be called exactly once"
    date_str, bal, hld = called_with[0]
    assert date_str == "20260502"
    assert bal == fake_balance
    assert hld == fake_holdings
