"""tests/test_reporter.py — src/reporter.py 단위 테스트."""
import csv
import json
from pathlib import Path

import pytest

from src.reporter import (
    _atomic_write,
    _calc_pnl_stats,
    _format_balance,
    _format_errors,
    _format_signals,
    _format_summary,
    _parse_errors_log,
    _parse_signals_log,
    _parse_trades_csv,
)


# ---------------------------------------------------------------------------
# _parse_trades_csv
# ---------------------------------------------------------------------------

def test_parse_trades_csv_missing_file(tmp_path):
    result = _parse_trades_csv(tmp_path / "trades_99990101.csv")
    assert result == []


def test_parse_trades_csv_normal(tmp_path):
    csv_path = tmp_path / "trades_20260502.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
        writer.writerow(["2026-05-02 09:15:00", "005930", "BUY", "71500", "3", "214500", "골든크로스", ""])
        writer.writerow(["2026-05-02 13:22:00", "005930", "SELL", "72100", "3", "216300", "익절", "1800.0"])
    rows = _parse_trades_csv(csv_path)
    assert len(rows) == 2
    assert rows[0]["action"] == "BUY"
    assert rows[0]["pnl"] is None          # BUY는 pnl 빈 문자열 → None
    assert rows[1]["pnl"] == pytest.approx(1800.0)


def test_parse_trades_csv_legacy_no_pnl_column(tmp_path):
    """구버전 CSV (pnl 컬럼 없음) — pnl 키가 None으로 처리된다."""
    csv_path = tmp_path / "trades_20260101.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason"])
        writer.writerow(["2026-01-01 10:00:00", "000660", "SELL", "185000", "2", "370000", "익절"])
    rows = _parse_trades_csv(csv_path)
    assert len(rows) == 1
    assert rows[0]["pnl"] is None


def test_parse_trades_csv_empty_file(tmp_path):
    """헤더만 있고 데이터 행이 없는 CSV."""
    csv_path = tmp_path / "trades_20260502.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
    rows = _parse_trades_csv(csv_path)
    assert rows == []


# ---------------------------------------------------------------------------
# _calc_pnl_stats
# ---------------------------------------------------------------------------

def test_calc_pnl_stats_empty():
    stats = _calc_pnl_stats([])
    assert stats["total_buy_count"] == 0
    assert stats["total_sell_count"] == 0
    assert stats["realized_pnl"] == pytest.approx(0.0)
    assert stats["win_count"] == 0
    assert stats["loss_count"] == 0
    assert stats["win_rate"] == pytest.approx(0.0)
    assert stats["pnl_available"] is False


def test_calc_pnl_stats_buy_only():
    """SELL 없이 BUY만 있는 경우."""
    trades = [
        {"action": "BUY", "pnl": None},
        {"action": "BUY", "pnl": None},
    ]
    stats = _calc_pnl_stats(trades)
    assert stats["total_buy_count"] == 2
    assert stats["total_sell_count"] == 0
    assert stats["win_rate"] == pytest.approx(0.0)
    assert stats["pnl_available"] is False


def test_calc_pnl_stats_single_win():
    trades = [
        {"action": "BUY", "pnl": None},
        {"action": "SELL", "pnl": 3000.0},
    ]
    stats = _calc_pnl_stats(trades)
    assert stats["total_buy_count"] == 1
    assert stats["total_sell_count"] == 1
    assert stats["realized_pnl"] == pytest.approx(3000.0)
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 0
    assert stats["win_rate"] == pytest.approx(100.0)
    assert stats["pnl_available"] is True


def test_calc_pnl_stats_win_and_loss():
    trades = [
        {"action": "SELL", "pnl": 5000.0},
        {"action": "SELL", "pnl": -2000.0},
    ]
    stats = _calc_pnl_stats(trades)
    assert stats["total_sell_count"] == 2
    assert stats["realized_pnl"] == pytest.approx(3000.0)
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 1
    assert stats["win_rate"] == pytest.approx(50.0)


def test_calc_pnl_stats_legacy_no_pnl():
    """구버전 CSV — pnl=None인 SELL이 있으면 pnl_available=False, win_rate=0."""
    trades = [
        {"action": "SELL", "pnl": None},
        {"action": "SELL", "pnl": None},
    ]
    stats = _calc_pnl_stats(trades)
    assert stats["total_sell_count"] == 2
    assert stats["pnl_available"] is False
    assert stats["realized_pnl"] == pytest.approx(0.0)
    assert stats["win_rate"] == pytest.approx(0.0)


def test_calc_pnl_stats_mixed_pnl_none():
    """pnl=None 혼합 케이스: 승률 분모는 pnl이 있는 행만 카운트해야 한다.

    SELL 3건 중 1건은 pnl=None (구버전 행).
    pnl 있는 행은 2건(500 win, -200 loss) → win_rate = 1/2 * 100 = 50.0.
    total_sell_count=3으로 나누면 ~33.3%가 되는데, 이를 방지한다.
    """
    trades = [
        {"action": "SELL", "pnl": 500.0},
        {"action": "SELL", "pnl": -200.0},
        {"action": "SELL", "pnl": None},
    ]
    stats = _calc_pnl_stats(trades)
    assert stats["total_sell_count"] == 3
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 1
    assert stats["pnl_available"] is True
    assert stats["win_rate"] == pytest.approx(50.0), (
        f"win_rate must be 50.0 (1/2), not {stats['win_rate']:.2f} (1/3)"
    )


# ---------------------------------------------------------------------------
# _parse_signals_log
# ---------------------------------------------------------------------------

def test_parse_signals_log_missing(tmp_path):
    assert _parse_signals_log(tmp_path / "signals_99990101.log") == []


def test_parse_signals_log_normal(tmp_path):
    log_path = tmp_path / "signals_20260502.log"
    log_path.write_text(
        "2026-05-02 09:15:32\t005930\tBUY \t71500\t골든크로스 + MACD 상향\n"
        "2026-05-02 10:45:01\t005930\tHOLD\t71200\t대기 (RSI: 52.1)\n",
        encoding="utf-8",
    )
    records = _parse_signals_log(log_path)
    assert len(records) == 2
    assert records[0]["stock_code"] == "005930"
    assert records[0]["signal"] == "BUY"
    assert records[0]["price"] == 71500
    assert records[1]["signal"] == "HOLD"


def test_parse_signals_log_malformed_line_skipped(tmp_path):
    log_path = tmp_path / "signals_20260502.log"
    log_path.write_text(
        "이것은 잘못된 형식의 줄입니다\n"
        "2026-05-02 09:15:32\t005930\tBUY \t71500\t이유\n",
        encoding="utf-8",
    )
    records = _parse_signals_log(log_path)
    assert len(records) == 1  # 정상 줄만 파싱


# ---------------------------------------------------------------------------
# _parse_errors_log
# ---------------------------------------------------------------------------

def test_parse_errors_log_missing(tmp_path):
    assert _parse_errors_log(tmp_path / "errors_99990101.log") == []


def test_parse_errors_log_normal(tmp_path):
    log_path = tmp_path / "errors_20260502.log"
    log_path.write_text(
        "2026-05-02 10:22:11\tERROR\t매도 주문 실패 [005930]: RuntimeError\n"
        "2026-05-02 12:05:44\tERROR\t루프 실행 중 오류: ConnectionError\n",
        encoding="utf-8",
    )
    records = _parse_errors_log(log_path)
    assert len(records) == 2
    assert records[0]["timestamp"] == "2026-05-02 10:22:11"
    assert "매도 주문 실패" in records[0]["message"]


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------

def _make_empty_pnl_stats():
    return {
        "total_buy_count": 0,
        "total_sell_count": 0,
        "realized_pnl": 0.0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": 0.0,
        "pnl_available": False,
    }


def _make_pnl_stats(buy=1, sell=1, pnl=3000.0, win=1, loss=0):
    return {
        "total_buy_count": buy,
        "total_sell_count": sell,
        "realized_pnl": pnl,
        "win_count": win,
        "loss_count": loss,
        "win_rate": (win / sell * 100.0) if sell > 0 else 0.0,
        "pnl_available": True,
    }


def test_format_summary_no_trades():
    text = _format_summary(
        date_str="20260502",
        mode="mock",
        started_at="2026-05-02 09:08:55",
        ended_at="2026-05-02 15:30:12",
        target_stocks=["005930"],
        pnl_stats=_make_empty_pnl_stats(),
        circuit_breaker_triggered=False,
        final_state={"daily_loss": 0, "consecutive_losses": 0},
        start_snap=None,
        end_holdings=None,
    )
    assert "KIS 자동매매 일별 요약" in text
    assert "거래 없음" in text
    assert "아니오" in text  # 서킷 브레이커 미발동


def test_format_summary_with_trades():
    text = _format_summary(
        date_str="20260502",
        mode="mock",
        started_at="2026-05-02 09:08:55",
        ended_at="2026-05-02 15:30:12",
        target_stocks=["005930", "000660"],
        pnl_stats=_make_pnl_stats(buy=3, sell=2, pnl=12500.0, win=1, loss=1),
        circuit_breaker_triggered=False,
        final_state={"daily_loss": 12500, "consecutive_losses": 0},
        start_snap=None,
        end_holdings=[],
    )
    assert "총 매수 건수" in text
    assert "3" in text
    assert "+12,500" in text
    assert "50.0 %" in text


def test_format_summary_circuit_breaker():
    text = _format_summary(
        date_str="20260502",
        mode="mock",
        started_at="2026-05-02 09:08:55",
        ended_at="2026-05-02 11:00:00",
        target_stocks=["005930"],
        pnl_stats=_make_empty_pnl_stats(),
        circuit_breaker_triggered=True,
        final_state={"daily_loss": -150000, "consecutive_losses": 3},
        start_snap=None,
        end_holdings=None,
    )
    assert "예" in text  # 서킷 브레이커 발동


# ---------------------------------------------------------------------------
# _format_signals
# ---------------------------------------------------------------------------

def test_format_signals_empty():
    text = _format_signals("20260502", [])
    assert "KIS 신호 이력" in text
    assert "신호 없음" in text


def test_format_signals_grouping():
    signals = [
        {"timestamp": "2026-05-02 09:15:32", "stock_code": "005930", "signal": "BUY", "price": 71500, "reason": "골든크로스"},
        {"timestamp": "2026-05-02 09:15:34", "stock_code": "000660", "signal": "HOLD", "price": 183500, "reason": "대기"},
        {"timestamp": "2026-05-02 13:22:18", "stock_code": "005930", "signal": "SELL", "price": 72100, "reason": "익절"},
    ]
    text = _format_signals("20260502", signals)
    assert "[ 005930 ]" in text
    assert "[ 000660 ]" in text
    # 005930 그룹이 000660 그룹보다 먼저 나와야 함
    assert text.index("[ 005930 ]") < text.index("[ 000660 ]")
    assert "총 신호 건수 : 3 건" in text


# ---------------------------------------------------------------------------
# _format_errors
# ---------------------------------------------------------------------------

def test_format_errors_no_errors():
    text = _format_errors("20260502", [])
    assert "KIS 오류/이상 이벤트" in text
    assert "오류 없음" in text


def test_format_errors_with_errors():
    errors = [
        {"timestamp": "2026-05-02 10:22:11", "message": "매도 주문 실패 [005930]"},
        {"timestamp": "2026-05-02 12:05:44", "message": "루프 오류: ConnectionError"},
    ]
    text = _format_errors("20260502", errors)
    assert "총 오류 건수 : 2 건" in text
    assert "매도 주문 실패" in text


# ---------------------------------------------------------------------------
# _format_balance
# ---------------------------------------------------------------------------

def test_format_balance_no_holdings():
    text = _format_balance(
        date_str="20260502",
        snapshot_ts="2026-05-02 15:30:08",
        balance={"total_eval": 5870000, "cash": 5870000, "profit_loss": 0},
        holdings=[],
    )
    assert "KIS 마감 잔고 스냅샷" in text
    assert "5,870,000" in text
    assert "보유 종목 없음" in text


def test_format_balance_with_holdings():
    holdings = [
        {
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "quantity": 3,
            "avg_price": 70000,
            "current_price": 72100,
            "profit_rate": 3.0,
            "profit_loss": 6300,
        }
    ]
    text = _format_balance(
        date_str="20260502",
        snapshot_ts="2026-05-02 15:30:08",
        balance={"total_eval": 8420000, "cash": 5870000, "profit_loss": -180000},
        holdings=holdings,
    )
    assert "005930" in text
    assert "삼성전자" in text
    assert "+3.0%" in text
    assert "+6,300원" in text
    assert "-180,000" in text


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------

def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "report.log"
    _atomic_write(target, "테스트 내용\n")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "테스트 내용\n"


def test_atomic_write_no_tmp_residue(tmp_path):
    target = tmp_path / "report.log"
    _atomic_write(target, "내용")
    tmp_file = target.with_suffix(target.suffix + ".tmp")
    assert not tmp_file.exists()  # .tmp 파일은 rename 후 사라져야 함


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "report.log"
    target.write_text("기존 내용", encoding="utf-8")
    _atomic_write(target, "새 내용")
    assert target.read_text(encoding="utf-8") == "새 내용"


# ---------------------------------------------------------------------------
# generate_daily_report — integration-level gap tests
# (filesystem-isolated via monkeypatching get_logs_dir / get_state_path)
# ---------------------------------------------------------------------------

from src.reporter import generate_daily_report


def _patch_reporter_dirs(monkeypatch, tmp_path):
    """Redirect get_logs_dir() and get_state_path() to tmp_path."""
    import src.reporter as reporter_mod
    import src.config as config_mod

    monkeypatch.setattr(reporter_mod, "get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(config_mod, "get_logs_dir", lambda: tmp_path)

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(reporter_mod, "get_state_path", lambda: state_file)
    monkeypatch.setattr(config_mod, "get_state_path", lambda: state_file)


# --- Re-generation idempotency (Critical bug regression) ---

def test_generate_daily_report_idempotent(monkeypatch, tmp_path):
    """Calling generate_daily_report twice must produce identical file content.

    Design doc edge case: "두 번 이상 리포트 생성 (재실행) — atomic write로 덮어씀."
    This is listed as a Critical bug regression test.
    """
    import csv as csv_mod

    _patch_reporter_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("TARGET_STOCKS", "005930")
    monkeypatch.setenv("MODE", "mock")

    date_str = "20260502"
    csv_path = tmp_path / f"trades_{date_str}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
        writer.writerow(["2026-05-02 09:15:00", "005930", "BUY", "71500", "3", "214500", "골든크로스", ""])
        writer.writerow(["2026-05-02 13:22:00", "005930", "SELL", "72100", "3", "216300", "익절", "1800.0"])

    paths_first = generate_daily_report(date_str)
    contents_first = {p.name: p.read_text(encoding="utf-8") for p in paths_first}

    paths_second = generate_daily_report(date_str)
    contents_second = {p.name: p.read_text(encoding="utf-8") for p in paths_second}

    assert set(contents_first.keys()) == set(contents_second.keys()), (
        "Second call produced different file set"
    )
    for name in contents_first:
        # Strip the dynamic "ended_at" timestamp line before comparing
        lines_a = [l for l in contents_first[name].splitlines() if "종료 시각" not in l]
        lines_b = [l for l in contents_second[name].splitlines() if "종료 시각" not in l]
        assert lines_a == lines_b, f"File {name} differs between first and second generation"


# --- Atomic write: .tmp files do not leak after successful generate_daily_report ---

def test_generate_daily_report_no_tmp_residue(monkeypatch, tmp_path):
    """After a successful generate_daily_report call, no .tmp files should remain.

    Design doc: 'write to .tmp, rename' — tmp files must disappear on success.
    """
    _patch_reporter_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("TARGET_STOCKS", "")
    monkeypatch.setenv("MODE", "mock")

    generate_daily_report("20260502")

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Leftover .tmp files found: {tmp_files}"


# --- No-trades day: summary contains "거래 없음", other files still created ---

def test_generate_daily_report_no_trades_day(monkeypatch, tmp_path):
    """When trades CSV is absent, summary must contain '거래 없음' and 3 files are generated.

    Design doc completion criterion: "When trades_YYYYMMDD.csv does not exist ...
    the system shall still generate summary_YYYYMMDD.log with a '거래 없음' section."
    """
    _patch_reporter_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("TARGET_STOCKS", "005930")
    monkeypatch.setenv("MODE", "mock")

    date_str = "20260502"
    # Deliberately do NOT create trades_20260502.csv

    paths = generate_daily_report(date_str)

    # Exactly 3 files (no balance snapshot passed)
    assert len(paths) == 3

    summary_path = tmp_path / f"summary_{date_str}.log"
    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "거래 없음" in summary_text


# --- Missing sidecar: raw_signals_YYYYMMDD.log absent → no crash, signals report still written ---

def test_generate_daily_report_missing_raw_signals_sidecar(monkeypatch, tmp_path):
    """When raw_signals_YYYYMMDD.log does not exist, reporter must not crash.

    Design doc edge case: "signals_YYYYMMDD.log 사이드카 없음 →
    _parse_signals_log가 [] 반환. signals 리포트 파일은 '신호 없음' 출력."
    """
    _patch_reporter_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("TARGET_STOCKS", "")
    monkeypatch.setenv("MODE", "mock")

    date_str = "20260502"
    # raw_signals and raw_errors sideckar files are absent — should not crash

    paths = generate_daily_report(date_str)

    signals_path = tmp_path / f"signals_{date_str}.log"
    assert signals_path.exists()
    signals_text = signals_path.read_text(encoding="utf-8")
    assert "신호 없음" in signals_text


# --- Malformed CSV row: corrupt row is skipped, not crash ---

def test_generate_daily_report_malformed_csv_row_skipped(monkeypatch, tmp_path):
    """A corrupt row in trades CSV must be skipped; reporter must not crash.

    Design doc resilience requirement: '_parse_trades_csv' must handle bad rows gracefully.
    """
    import csv as csv_mod

    _patch_reporter_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("TARGET_STOCKS", "005930")
    monkeypatch.setenv("MODE", "mock")

    date_str = "20260502"
    csv_path = tmp_path / f"trades_{date_str}.csv"

    # Write a valid header + one good BUY row + one row with bad pnl value
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
        writer.writerow(["2026-05-02 09:15:00", "005930", "BUY", "71500", "3", "214500", "골든크로스", ""])
        writer.writerow(["2026-05-02 13:22:00", "005930", "SELL", "72100", "3", "216300", "익절", "NOT_A_NUMBER"])

    # Must not raise
    paths = generate_daily_report(date_str)

    assert len(paths) == 3
    summary_path = tmp_path / f"summary_{date_str}.log"
    assert summary_path.exists()
    # The corrupt pnl row maps to None — pnl_available depends on whether any valid pnl exists
    # BUY row has pnl=None, SELL row has pnl=None (bad value coerced to None)
    # → pnl_available=False → summary shows N/A, not "거래 없음" (1 BUY exists)
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "총 매수 건수" in summary_text  # BUY row was parsed correctly
