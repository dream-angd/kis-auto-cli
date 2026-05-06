"""일별 리포트 파일 생성 전담 모듈.

reporter는 scheduler/trader를 import하지 않는다 (단방향 의존).
의존 방향: reporter → config, logger (log_info, log_error만)
"""
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from src.config import get_logs_dir, get_state_path
from src.logger import log_error


def _atomic_write(path: Path, content: str) -> None:
    """content를 path.tmp에 쓰고 path로 rename한다. UTF-8. 원자적 덮어쓰기."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _parse_trades_csv(csv_path: Path) -> list[dict]:
    """CSV를 읽어 행 목록을 반환한다. 파일 없으면 []를 반환한다.

    구버전 CSV(pnl 컬럼 없음)를 읽으면 각 행의 'pnl' 키를 None으로 설정한다.
    """
    if not csv_path.exists():
        return []
    rows: list[dict] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_pnl = row.get("pnl", None)
            if raw_pnl is None or raw_pnl == "":
                row["pnl"] = None
            else:
                try:
                    row["pnl"] = float(raw_pnl)
                except ValueError:
                    row["pnl"] = None
            rows.append(row)
    return rows


def _calc_pnl_stats(trades: list[dict]) -> dict:
    """SELL 행만 필터링하여 P&L 통계를 집계한다.

    반환 딕셔너리 키:
      total_buy_count  : int   — BUY 행 수
      total_sell_count : int   — SELL 행 수
      realized_pnl     : float — SELL 행 pnl 합산 (pnl 컬럼이 모두 None이면 0.0)
      win_count        : int   — pnl > 0인 SELL 건수
      loss_count       : int   — pnl <= 0인 SELL 건수
      win_rate         : float — win_count / total_sell_count * 100; sell=0이면 0.0
      pnl_available    : bool  — pnl 컬럼이 하나라도 있으면 True (구버전 CSV 감지)
    """
    buy_rows = [t for t in trades if t.get("action", "").strip() == "BUY"]
    sell_rows = [t for t in trades if t.get("action", "").strip() == "SELL"]

    total_buy_count = len(buy_rows)
    total_sell_count = len(sell_rows)

    pnl_values = [t["pnl"] for t in sell_rows if t["pnl"] is not None]
    pnl_available = len(pnl_values) > 0

    realized_pnl = sum(pnl_values) if pnl_values else 0.0
    win_count = sum(1 for v in pnl_values if v > 0)
    loss_count = sum(1 for v in pnl_values if v <= 0)
    win_rate = (win_count / len(pnl_values) * 100.0) if pnl_values else 0.0

    return {
        "total_buy_count": total_buy_count,
        "total_sell_count": total_sell_count,
        "realized_pnl": realized_pnl,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "pnl_available": pnl_available,
    }


_SIGNAL_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\t(\S+)\t([^\t]+)\t(\d+)\t(.*)$"
)


def _parse_signals_log(log_path: Path) -> list[dict]:
    """raw_signals_YYYYMMDD.log 사이드카 파일을 파싱한다.

    형식:  timestamp<TAB>stock_code<TAB>signal<TAB>price<TAB>reason
    파일 없거나 형식 불일치 행은 무시한다. 파일 없으면 [] 반환.
    """
    if not log_path.exists():
        return []
    records: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _SIGNAL_LINE_RE.match(line)
            if not m:
                continue
            ts, stock_code, signal, price_str, reason = m.groups()
            records.append({
                "timestamp": ts,
                "stock_code": stock_code,
                "signal": signal.strip(),
                "price": int(price_str),
                "reason": reason,
            })
    return records


_ERROR_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\tERROR\t(.+)$"
)


def _parse_errors_log(log_path: Path) -> list[dict]:
    """raw_errors_YYYYMMDD.log 사이드카 파일을 파싱한다.

    형식:  timestamp<TAB>ERROR<TAB>message
    파일 없으면 [] 반환. 형식 불일치 행은 무시한다.
    """
    if not log_path.exists():
        return []
    records: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _ERROR_LINE_RE.match(line)
            if not m:
                continue
            ts, message = m.groups()
            records.append({"timestamp": ts, "message": message})
    return records


def _load_start_snapshot(date_str: str) -> dict | None:
    """start_snapshot_YYYYMMDD.json을 로드한다. 없거나 파싱 실패 시 None 반환."""
    path = get_logs_dir() / f"start_snapshot_{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_error(f"시작 스냅샷 로드 실패 [{path}]: {e}")
        return None


def _load_final_state(date_str: str) -> dict:
    """state.json을 읽어 오늘 날짜와 일치하면 반환한다.

    날짜 불일치, 파일 없음, 파싱 오류 시 기본값 반환:
      {"daily_loss": 0, "consecutive_losses": 0}
    """
    path = get_state_path()
    default = {"daily_loss": 0, "consecutive_losses": 0}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expected_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        if data.get("date") != expected_date:
            return default
        return {
            "daily_loss": data.get("daily_loss", 0),
            "consecutive_losses": data.get("consecutive_losses", 0),
        }
    except Exception as e:
        log_error(f"최종 상태 로드 실패 [{path}]: {e}")
        return default


def _format_summary(
    date_str: str,
    mode: str,
    started_at: str,
    ended_at: str,
    target_stocks: list[str],
    pnl_stats: dict,
    circuit_breaker_triggered: bool,
    final_state: dict,
    start_snap: dict | None,
    end_holdings: list[dict] | None,
) -> str:
    """summary_YYYYMMDD.log 텍스트를 생성한다. 순수 함수.

    파라미터:
      date_str                  : "YYYYMMDD"
      mode                      : "mock" | "real"
      started_at                : "YYYY-MM-DD HH:MM:SS" 또는 빈 문자열
      ended_at                  : "YYYY-MM-DD HH:MM:SS" 또는 빈 문자열
      target_stocks             : ["005930", "000660", ...]
      pnl_stats                 : _calc_pnl_stats() 반환값
      circuit_breaker_triggered : 에러 로그에서 서킷 브레이커 발동 여부
      final_state               : _load_final_state() 반환값
      start_snap                : _load_start_snapshot() 반환값 또는 None
      end_holdings              : get_account_info() 의 holdings 또는 None
    """
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    sep = "=" * 64

    lines: list[str] = [
        sep,
        f"  KIS 자동매매 일별 요약 — {display_date}",
        sep,
        f"  모드          : {mode}",
        f"  시작 시각     : {started_at if started_at else '알 수 없음'}",
        f"  종료 시각     : {ended_at if ended_at else '알 수 없음'}",
        f"  감시 종목     : {', '.join(target_stocks) if target_stocks else '없음'}",
        "",
    ]

    lines.append("[ 매매 실적 ]")
    total_buy = pnl_stats["total_buy_count"]
    total_sell = pnl_stats["total_sell_count"]
    if total_buy == 0 and total_sell == 0:
        lines.append("  거래 없음")
    else:
        lines.append(f"  총 매수 건수  : {total_buy:>4} 건")
        lines.append(f"  총 매도 건수  : {total_sell:>4} 건")
        if pnl_stats["pnl_available"]:
            pnl = pnl_stats["realized_pnl"]
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  실현 손익     : {sign}{pnl:,.0f} 원")
            win = pnl_stats["win_count"]
            loss = pnl_stats["loss_count"]
            rate = pnl_stats["win_rate"]
            lines.append(f"  승률          : {rate:.1f} %  ({win}승 / {loss}패)")
        else:
            lines.append("  실현 손익     : N/A  (구버전 CSV — pnl 컬럼 없음)")
            lines.append("  승률          : N/A")
    lines.append("")

    lines.append("[ 서킷 브레이커 ]")
    lines.append(f"  발동 여부     : {'예' if circuit_breaker_triggered else '아니오'}")
    lines.append("")

    lines.append("[ 일별 위험 상태 (최종) ]")
    dl = final_state["daily_loss"]
    sign = "+" if dl >= 0 else ""
    lines.append(f"  누적 일손실   : {sign}{dl:,.0f} 원")
    lines.append(f"  연속 손실     :  {final_state['consecutive_losses']:>3} 회")
    lines.append("")

    lines.append("[ 보유 종목 변화 ]")
    if start_snap and start_snap.get("holdings"):
        lines.append("  -- 시작 시점 --")
        for h in start_snap["holdings"]:
            lines.append(
                f"  {h.get('stock_code', '')}  {h.get('stock_name', ''):<10}  "
                f"{h.get('quantity', 0)}주  @{h.get('avg_price', 0):,.0f}원"
            )
    else:
        lines.append("  -- 시작 시점 -- 정보 없음")

    if end_holdings is not None:
        lines.append("  -- 종료 시점 --")
        if end_holdings:
            for h in end_holdings:
                lines.append(
                    f"  {h.get('stock_code', '')}  {h.get('stock_name', ''):<10}  "
                    f"{h.get('quantity', 0)}주  @{h.get('avg_price', 0):,.0f}원"
                )
        else:
            lines.append("  (보유 종목 없음)")
    else:
        lines.append("  -- 종료 시점 -- 정보 없음")

    lines.append("")
    lines.append(sep)
    return "\n".join(lines) + "\n"


def _format_signals(date_str: str, signals: list[dict]) -> str:
    """signals_YYYYMMDD.log 리포트 텍스트를 생성한다. 순수 함수.

    signals 항목 키: timestamp, stock_code, signal, price, reason
    종목코드별로 그룹핑하여 출력한다 (최초 등장 순서 유지).
    """
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    sep = "=" * 64

    buy_cnt = sum(1 for s in signals if s["signal"].strip() == "BUY")
    sell_cnt = sum(1 for s in signals if s["signal"].strip() == "SELL")
    hold_cnt = sum(1 for s in signals if s["signal"].strip() == "HOLD")
    total = len(signals)

    lines: list[str] = [
        sep,
        f"  KIS 신호 이력 — {display_date}",
        sep,
        f"  총 신호 건수 : {total} 건  (BUY: {buy_cnt} / SELL: {sell_cnt} / HOLD: {hold_cnt})",
        "",
    ]

    if not signals:
        lines.append("  신호 없음")
        lines.append("")
        lines.append(sep)
        return "\n".join(lines) + "\n"

    # 종목 등장 순서 보존 그룹핑
    groups: dict[str, list[dict]] = {}
    for s in signals:
        code = s["stock_code"]
        groups.setdefault(code, []).append(s)

    for code, entries in groups.items():
        lines.append(f"[ {code} ]")
        for e in entries:
            ts_time = e["timestamp"].split(" ")[1] if " " in e["timestamp"] else e["timestamp"]
            lines.append(
                f"  {ts_time}  {e['signal']:<4}  {e['price']:>9,}  {e['reason']}"
            )
        lines.append("")

    lines.append(sep)
    return "\n".join(lines) + "\n"


def _format_errors(date_str: str, errors: list[dict]) -> str:
    """errors_YYYYMMDD.log 리포트 텍스트를 생성한다. 순수 함수.

    errors 항목 키: timestamp, message
    """
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    sep = "=" * 64

    lines: list[str] = [
        sep,
        f"  KIS 오류/이상 이벤트 — {display_date}",
        sep,
        f"  총 오류 건수 : {len(errors)} 건",
        "",
    ]

    if not errors:
        lines.append("  오류 없음")
    else:
        for e in errors:
            ts_time = e["timestamp"].split(" ")[1] if " " in e["timestamp"] else e["timestamp"]
            lines.append(f"  {ts_time}  {e['message']}")

    lines.append("")
    lines.append(sep)
    return "\n".join(lines) + "\n"


def _format_balance(
    date_str: str,
    snapshot_ts: str,
    balance: dict,
    holdings: list[dict],
) -> str:
    """balance_YYYYMMDD.log 텍스트를 생성한다. 순수 함수.

    파라미터:
      date_str    : "YYYYMMDD"
      snapshot_ts : "YYYY-MM-DD HH:MM:SS" (잔고 조회 시각)
      balance     : {"total_eval": int, "cash": int, "profit_loss": int}
      holdings    : [{"stock_code": str, "stock_name": str, "quantity": int,
                       "avg_price": int, "current_price": int,
                       "profit_rate": float, "profit_loss": int}, ...]
    """
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    sep = "=" * 64

    lines: list[str] = [
        sep,
        f"  KIS 마감 잔고 스냅샷 — {snapshot_ts}",
        sep,
        f"  총 평가금액   : {balance.get('total_eval', 0):>12,} 원",
        f"  가용 현금     : {balance.get('cash', 0):>12,} 원",
    ]
    cash_deposit = balance.get("cash_deposit", balance.get("cash", 0))
    if cash_deposit != balance.get("cash", 0):
        lines.append(f"  예수금 총액   : {cash_deposit:>12,} 원  (D+2 정산 미반영)")
    pl = balance.get("profit_loss", 0)
    pl_sign = "+" if pl >= 0 else ""
    lines.append(f"  평가 손익     : {pl_sign}{pl:>11,} 원")
    asset_change = balance.get("asset_change", 0)
    if asset_change:
        ac_sign = "+" if asset_change >= 0 else ""
        lines.append(f"  오늘 자산변화 : {ac_sign}{asset_change:>11,} 원")
    lines.append("")

    lines.append("[ 보유 종목 ]")
    if not holdings:
        lines.append("  보유 종목 없음")
    else:
        header = f"  {'종목코드':<8}  {'종목명':<16}  {'수량':>5}  {'평균가':>10}  {'현재가':>10}  {'수익률':>8}  {'손익':>10}"
        divider = "  " + "-" * 76
        lines.append(header)
        lines.append(divider)
        for h in holdings:
            pr = h.get("profit_rate", 0.0)
            pr_sign = "+" if pr >= 0 else ""
            hl = h.get("profit_loss", 0)
            hl_sign = "+" if hl >= 0 else ""
            lines.append(
                f"  {h.get('stock_code', ''):<8}  {h.get('stock_name', ''):<16}  "
                f"{h.get('quantity', 0):>5}주  {h.get('avg_price', 0):>9,}원  "
                f"{h.get('current_price', 0):>9,}원  "
                f"{pr_sign}{pr:.1f}%  {hl_sign}{hl:,}원"
            )

    lines.append("")
    lines.append(sep)
    return "\n".join(lines) + "\n"


def generate_daily_report(
    date_str: str,
    balance_snapshot: dict | None = None,
    holdings_snapshot: list[dict] | None = None,
) -> list[Path]:
    """지정 날짜의 리포트 파일을 생성하고 생성된 Path 리스트를 반환한다.

    파라미터:
      date_str           : "YYYYMMDD" 형식 날짜
      balance_snapshot   : get_account_info() 반환 balance dict 또는 None
      holdings_snapshot  : get_account_info() 반환 holdings list 또는 None
                           None이면 balance_YYYYMMDD.log를 생성하지 않는다.

    예외 발생 시 호출자에게 전파한다 (호출자가 log_error로 처리).
    """
    from src.config import get_swing_stocks, get_scalp_stocks, get_mode

    logs_dir = get_logs_dir()
    generated: list[Path] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- 데이터 수집 ---
    trades = _parse_trades_csv(logs_dir / f"trades_{date_str}.csv")
    pnl_stats = _calc_pnl_stats(trades)

    signals = _parse_signals_log(logs_dir / f"raw_signals_{date_str}.log")
    errors = _parse_errors_log(logs_dir / f"raw_errors_{date_str}.log")
    start_snap = _load_start_snapshot(date_str)
    final_state = _load_final_state(date_str)

    # 서킷 브레이커 발동 여부: errors 사이드카에서 "서킷 브레이커 발동" 문자열 탐지
    cb_triggered = any("서킷 브레이커 발동" in e["message"] for e in errors)

    # started_at: start_snapshot의 timestamp 사용, 없으면 빈 문자열
    started_at = ""
    if start_snap and start_snap.get("timestamp"):
        raw_ts = start_snap["timestamp"]
        # ISO 포맷(2026-05-02T09:08:55)을 공백 구분으로 변환
        started_at = raw_ts.replace("T", " ")

    # swing + scalp 종목 합집합 (감시 대상 전체)
    seen = []
    for code in [*get_swing_stocks(), *get_scalp_stocks()]:
        if code and code not in seen:
            seen.append(code)
    target_stocks = seen
    mode = get_mode()

    # --- summary ---
    summary_path = logs_dir / f"summary_{date_str}.log"
    summary_text = _format_summary(
        date_str=date_str,
        mode=mode,
        started_at=started_at,
        ended_at=now_str,
        target_stocks=target_stocks,
        pnl_stats=pnl_stats,
        circuit_breaker_triggered=cb_triggered,
        final_state=final_state,
        start_snap=start_snap,
        end_holdings=holdings_snapshot,
    )
    _atomic_write(summary_path, summary_text)
    generated.append(summary_path)

    # --- signals ---
    signals_path = logs_dir / f"signals_{date_str}.log"
    signals_text = _format_signals(date_str, signals)
    _atomic_write(signals_path, signals_text)
    generated.append(signals_path)

    # --- errors ---
    errors_path = logs_dir / f"errors_{date_str}.log"
    errors_text = _format_errors(date_str, errors)
    _atomic_write(errors_path, errors_text)
    generated.append(errors_path)

    # --- balance (라이브 스냅샷이 있을 때만) ---
    if balance_snapshot is not None and holdings_snapshot is not None:
        balance_path = logs_dir / f"balance_{date_str}.log"
        balance_text = _format_balance(
            date_str=date_str,
            snapshot_ts=now_str,
            balance=balance_snapshot,
            holdings=holdings_snapshot,
        )
        _atomic_write(balance_path, balance_text)
        generated.append(balance_path)

    return generated
