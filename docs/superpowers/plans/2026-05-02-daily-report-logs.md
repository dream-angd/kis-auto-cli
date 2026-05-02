# Daily Report Logs Implementation Plan

**Goal:** 장 마감 시점에 역할별 일별 리포트 파일 4종(`summary`, `signals`, `errors`, `balance`)을 `logs/` 디렉토리에 자동 생성하고, `kis-trader report` CLI 서브커맨드로 수동 (재)생성을 지원한다.

**Architecture:** `src/logger.py`에 사이드카 파일(`signals_YYYYMMDD.log`, `errors_YYYYMMDD.log`) 기록 기능을 추가하고, 신규 `src/reporter.py`가 순수 집계 함수로 4개 파일을 원자적으로 생성한다. `src/scheduler.py`의 `run_loop` finally 블록에서 `_maybe_generate_report()`를 호출하여 15:30 이후 종료 시에만 리포트를 생성하며, `main.py`의 `report` 서브커맨드로 언제든 재생성할 수 있다.

**Tech Stack:** Python 3.11, stdlib(`csv`, `pathlib`, `json`, `threading`, `datetime`, `re`), pytest

---

## 파일 구조

| 작업 | 파일 | 역할 |
|------|------|------|
| Modify | `src/config.py` | `get_logs_dir()` 헬퍼 함수 추가 |
| Modify | `src/logger.py` | `_csv_lock` → `_file_lock` 이름 변경; `log_trade`에 `pnl` 파라미터 추가 및 CSV 헤더 변경; `log_signal` / `log_error`에 사이드카 파일 기록 추가 |
| Create | `src/reporter.py` | 리포트 집계/포맷/출력 전담 모듈 |
| Modify | `src/scheduler.py` | `_snapshot_holdings_at_open`, `_maybe_generate_report` 추가; `run_loop`에 `started_at` 캡처 및 `_maybe_generate_report` 호출; `log_trade` SELL 호출에 `pnl=pnl` 전달 |
| Modify | `main.py` | `cmd_report` 함수 및 `report` 서브커맨드 argparse 등록 추가 |
| Create | `tests/test_reporter.py` | `reporter.py` 순수 함수 단위 테스트 |

---

## Task 1: `src/config.py` — `get_logs_dir()` 추가

**Files:**
- Modify: `src/config.py` (파일 끝에 추가)

- [ ] **Step 1: `get_logs_dir()` 함수를 `src/config.py` 하단에 추가한다**

  `src/config.py`의 마지막 함수 `get_atr_risk_pct()` 아래, 파일 끝에 다음 블록을 추가한다.

  ```python
  # --- 로그 디렉토리 ---
  def get_logs_dir() -> Path:
      """logs/ 디렉토리 절대 경로. logger.py의 LOGS_DIR과 동일 경로."""
      return Path(__file__).resolve().parent.parent / "logs"
  ```

  Expected: `from src.config import get_logs_dir; get_logs_dir()` 호출 시 프로젝트 루트 아래 `logs/` 경로를 반환한다.

- [ ] **Step 2: 기존 `test_config.py`가 통과하는지 확인한다**

  ```bash
  python -m pytest tests/test_config.py -v
  ```

  Expected: 모든 기존 테스트가 PASSED. `get_logs_dir`에 대한 테스트는 아직 없으므로 새 실패 없음.

---

## Task 2: `src/logger.py` — `_file_lock` 이름 변경 + `log_trade` pnl 컬럼 추가

**Files:**
- Modify: `src/logger.py`

- [ ] **Step 1: 모듈 수준 `_csv_lock`을 `_file_lock`으로 이름 변경한다**

  `src/logger.py` 12번째 줄의 `_csv_lock = threading.Lock()` 을 아래로 교체한다.

  ```python
  _file_lock = threading.Lock()
  ```

  Expected: 파일 내 `_csv_lock` 참조가 0개가 된다.

- [ ] **Step 2: `log_trade` 함수 시그니처에 `pnl` 파라미터를 추가하고 CSV 헤더와 행을 수정한다**

  `src/logger.py`의 `log_trade` 함수(48~68번째 줄)를 아래 전체로 교체한다.

  ```python
  def log_trade(
      stock_code: str,
      action: str,
      price: int,
      quantity: int,
      amount: int,
      reason: str = "",
      pnl: float | None = None,
  ) -> None:
      log_info(f"{stock_code} | 신호: {action} | 가격: {price:,} | 수량: {quantity} | 금액: {amount:,} | {reason}")

      today = datetime.now().strftime("%Y%m%d")
      csv_path = LOGS_DIR / f"trades_{today}.csv"

      with _file_lock:
          write_header = not csv_path.exists()
          with open(csv_path, "a", newline="", encoding="utf-8") as f:
              writer = csv.writer(f)
              if write_header:
                  writer.writerow(["datetime", "stock_code", "action", "price", "quantity", "amount", "reason", "pnl"])
              writer.writerow([
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  stock_code,
                  action,
                  price,
                  quantity,
                  amount,
                  reason,
                  "" if pnl is None else pnl,
              ])
  ```

  Expected: CSV 헤더가 8개 컬럼으로 늘어난다. BUY 호출 시 `pnl` 칼럼은 빈 문자열, SELL 호출 시 숫자가 기록된다.

- [ ] **Step 3: `log_signal` 함수를 사이드카 파일 기록 포함 버전으로 교체한다**

  `src/logger.py`의 `log_signal` 함수(71~73번째 줄)를 아래 전체로 교체한다.

  ```python
  def log_signal(stock_code: str, signal: str, price: int, reason: str = "") -> None:
      action_str = {"BUY": "BUY ", "SELL": "SELL", "HOLD": "HOLD"}
      log_info(f"{stock_code} | 신호: {action_str.get(signal, signal)} | 가격: {price:,} | 결과: {reason}")

      today = datetime.now().strftime("%Y%m%d")
      sidecar_path = LOGS_DIR / f"signals_{today}.log"
      ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      line = f"{ts}\t{stock_code}\t{action_str.get(signal, signal)}\t{price}\t{reason}\n"

      with _file_lock:
          with open(sidecar_path, "a", encoding="utf-8") as f:
              f.write(line)
  ```

  Expected: `log_signal` 호출 시마다 `logs/signals_YYYYMMDD.log`에 탭 구분 행이 append된다.

- [ ] **Step 4: `log_error` 함수를 사이드카 파일 기록 포함 버전으로 교체한다**

  `src/logger.py`의 `log_error` 함수(44~45번째 줄)를 아래 전체로 교체한다.

  ```python
  def log_error(msg: str) -> None:
      _logger.error(msg)

      today = datetime.now().strftime("%Y%m%d")
      sidecar_path = LOGS_DIR / f"errors_{today}.log"
      ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      line = f"{ts}\tERROR\t{msg}\n"

      with _file_lock:
          with open(sidecar_path, "a", encoding="utf-8") as f:
              f.write(line)
  ```

  Expected: `log_error` 호출 시마다 `logs/errors_YYYYMMDD.log`에 탭 구분 행이 append된다.

- [ ] **Step 5: 완성된 `src/logger.py` 전체를 검토하여 `_csv_lock` 잔재가 없는지 확인한다**

  ```bash
  python -c "from src.logger import log_info, log_error, log_trade, log_signal; print('import ok')"
  ```

  Expected: `import ok` 출력. 오류 없음.

---

## Task 3: `src/reporter.py` — 파싱 및 집계 순수 함수

**Files:**
- Create: `src/reporter.py`

이 Task에서는 파일 파싱과 P&L 집계를 담당하는 순수 함수들을 구현한다. 포맷/출력 함수는 Task 4에서 추가한다.

- [ ] **Step 1: `src/reporter.py` 파일을 생성하고 import 및 `_atomic_write`를 작성한다**

  ```python
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


  def _atomic_write(path: Path, content: str) -> None:
      """content를 path.tmp에 쓰고 path로 rename한다. UTF-8. 원자적 덮어쓰기."""
      path.parent.mkdir(parents=True, exist_ok=True)
      tmp_path = path.with_suffix(path.suffix + ".tmp")
      tmp_path.write_text(content, encoding="utf-8")
      tmp_path.replace(path)
  ```

  Expected: 파일이 생성된다. `python -c "from src.reporter import _atomic_write"` 오류 없음.

- [ ] **Step 2: `_parse_trades_csv` 함수를 추가한다**

  `_atomic_write` 아래에 추가한다.

  ```python
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
  ```

  Expected: 존재하지 않는 경로를 넘기면 `[]` 반환. 정상 CSV는 `list[dict]` 반환.

- [ ] **Step 3: `_calc_pnl_stats` 함수를 추가한다**

  `_parse_trades_csv` 아래에 추가한다.

  ```python
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
      win_rate = (win_count / total_sell_count * 100.0) if total_sell_count > 0 else 0.0

      return {
          "total_buy_count": total_buy_count,
          "total_sell_count": total_sell_count,
          "realized_pnl": realized_pnl,
          "win_count": win_count,
          "loss_count": loss_count,
          "win_rate": win_rate,
          "pnl_available": pnl_available,
      }
  ```

  Expected: 빈 리스트 입력 시 모든 카운터 0, `win_rate=0.0`, `pnl_available=False`.

- [ ] **Step 4: `_parse_signals_log` 함수를 추가한다**

  `_calc_pnl_stats` 아래에 추가한다.

  ```python
  _SIGNAL_LINE_RE = re.compile(
      r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\t(\S+)\t(\S+)\t(\d+)\t(.*)$"
  )


  def _parse_signals_log(log_path: Path) -> list[dict]:
      """signals_YYYYMMDD.log 사이드카 파일을 파싱한다.

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
  ```

  Expected: 빈 파일이면 `[]`. 형식 불일치 행은 조용히 스킵.

- [ ] **Step 5: `_parse_errors_log` 함수를 추가한다**

  `_parse_signals_log` 아래에 추가한다.

  ```python
  _ERROR_LINE_RE = re.compile(
      r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\tERROR\t(.+)$"
  )


  def _parse_errors_log(log_path: Path) -> list[dict]:
      """errors_YYYYMMDD.log 사이드카 파일을 파싱한다.

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
  ```

  Expected: 파일 없으면 `[]`. 정상 파일은 `[{"timestamp": ..., "message": ...}, ...]`.

- [ ] **Step 6: `_load_start_snapshot` 함수를 추가한다**

  `_parse_errors_log` 아래에 추가한다.

  ```python
  def _load_start_snapshot(date_str: str) -> dict | None:
      """start_snapshot_YYYYMMDD.json을 로드한다. 없거나 파싱 실패 시 None 반환."""
      path = get_logs_dir() / f"start_snapshot_{date_str}.json"
      if not path.exists():
          return None
      try:
          return json.loads(path.read_text(encoding="utf-8"))
      except Exception:
          return None
  ```

  Expected: 파일 없으면 `None`. 정상 JSON이면 dict 반환.

- [ ] **Step 7: `_load_final_state` 함수를 추가한다**

  `_load_start_snapshot` 아래에 추가한다.

  ```python
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
      except Exception:
          return default
  ```

  Expected: `date_str="20260502"` 입력 시 `state.json`의 `"date"` 필드가 `"2026-05-02"`와 일치하면 해당 값 반환. 불일치이면 `{"daily_loss": 0, "consecutive_losses": 0}`.

---

## Task 4: `src/reporter.py` — 포맷 함수 4개

**Files:**
- Modify: `src/reporter.py` (Task 3에서 생성된 파일의 끝에 추가)

- [ ] **Step 1: `_format_summary` 함수를 추가한다**

  `_load_final_state` 아래에 추가한다.

  ```python
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
              lines.append(f"  실현 손익     : {sign}{pnl:>10,.0f} 원")
              win = pnl_stats["win_count"]
              loss = pnl_stats["loss_count"]
              rate = pnl_stats["win_rate"]
              lines.append(f"  승률          : {rate:>5.1f} %  ({win}승 / {loss}패)")
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
      lines.append(f"  누적 일손실   : {sign}{dl:>10,.0f} 원")
      lines.append(f"  연속 손실     :  {final_state['consecutive_losses']:>3} 회")
      lines.append("")

      lines.append("[ 보유 종목 변화 ]")
      if start_snap and start_snap.get("holdings"):
          lines.append("  -- 시작 시점 --")
          for h in start_snap["holdings"]:
              lines.append(
                  f"  {h['stock_code']}  {h.get('stock_name', ''):<10}  "
                  f"{h.get('quantity', 0)}주  @{h.get('avg_price', 0):,.0f}원"
              )
      else:
          lines.append("  -- 시작 시점 -- 정보 없음")

      if end_holdings is not None:
          lines.append("  -- 종료 시점 --")
          if end_holdings:
              for h in end_holdings:
                  lines.append(
                      f"  {h['stock_code']}  {h.get('stock_name', ''):<10}  "
                      f"{h.get('quantity', 0)}주  @{h.get('avg_price', 0):,.0f}원"
                  )
          else:
              lines.append("  (보유 종목 없음)")
      else:
          lines.append("  -- 종료 시점 -- 정보 없음")

      lines.append("")
      lines.append(sep)
      return "\n".join(lines) + "\n"
  ```

  Expected: 반환값은 문자열. "거래 없음" 케이스에서 `"거래 없음"` 문자열 포함.

- [ ] **Step 2: `_format_signals` 함수를 추가한다**

  `_format_summary` 아래에 추가한다.

  ```python
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
  ```

  Expected: 신호 없을 때 `"신호 없음"` 포함. 다종목 입력 시 종목별 그룹 헤더 포함.

- [ ] **Step 3: `_format_errors` 함수를 추가한다**

  `_format_signals` 아래에 추가한다.

  ```python
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
  ```

  Expected: 오류 없을 때 `"오류 없음"` 포함.

- [ ] **Step 4: `_format_balance` 함수를 추가한다**

  `_format_errors` 아래에 추가한다.

  ```python
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
          f"  예수금        : {balance.get('cash', 0):>12,} 원",
      ]
      pl = balance.get("profit_loss", 0)
      pl_sign = "+" if pl >= 0 else ""
      lines.append(f"  평가 손익     : {pl_sign}{pl:>11,} 원")
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
                  f"{pr_sign}{pr:>6.1f}%  {hl_sign}{hl:>8,}원"
              )

      lines.append("")
      lines.append(sep)
      return "\n".join(lines) + "\n"
  ```

  Expected: 보유 종목 없을 때 `"보유 종목 없음"` 포함. 수익률/손익에 부호 표시.

---

## Task 5: `src/reporter.py` — `generate_daily_report` 조립 함수

**Files:**
- Modify: `src/reporter.py` (Task 4에서 작성된 파일 끝에 추가)

- [ ] **Step 1: `generate_daily_report` 함수를 추가한다**

  `_format_balance` 아래에 추가한다.

  ```python
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
      from src.config import get_target_stocks, get_mode

      logs_dir = get_logs_dir()
      generated: list[Path] = []
      now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

      # --- 데이터 수집 ---
      trades = _parse_trades_csv(logs_dir / f"trades_{date_str}.csv")
      pnl_stats = _calc_pnl_stats(trades)

      signals = _parse_signals_log(logs_dir / f"signals_{date_str}.log")
      errors = _parse_errors_log(logs_dir / f"errors_{date_str}.log")
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

      target_stocks = get_target_stocks()
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
  ```

  Expected: 반환값은 생성된 `Path` 객체 리스트. `balance_snapshot=None` 이면 리스트 길이 3. 둘 다 지정 시 길이 4.

- [ ] **Step 2: import가 올바른지 확인한다**

  ```bash
  python -c "from src.reporter import generate_daily_report; print('reporter import ok')"
  ```

  Expected: `reporter import ok` 출력.

---

## Task 6: `src/scheduler.py` — `_snapshot_holdings_at_open` 추가

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: `_snapshot_holdings_at_open` 함수를 `_clear_status` 함수 아래에 추가한다**

  `src/scheduler.py`의 `_clear_status` 함수(134~137번째 줄) 바로 아래에 추가한다.

  ```python
  def _snapshot_holdings_at_open() -> None:
      """장 시작 후 최초 보유 종목과 잔고를 start_snapshot_YYYYMMDD.json에 저장한다.

      API 오류 시 log_error 후 무시한다 (스냅샷 실패가 트레이딩을 막으면 안 됨).
      """
      from src.config import get_logs_dir
      today = datetime.now().strftime("%Y%m%d")
      snap_path = get_logs_dir() / f"start_snapshot_{today}.json"
      if snap_path.exists():
          return  # 이미 저장됨 (재시작 등 중복 방지)
      try:
          balance, holdings = get_account_info()
          data = {
              "timestamp": datetime.now().isoformat(timespec="seconds"),
              "holdings": [
                  {
                      "stock_code": h["stock_code"],
                      "stock_name": h.get("stock_name", ""),
                      "quantity": h["quantity"],
                      "avg_price": h["avg_price"],
                  }
                  for h in holdings
              ],
              "balance": {
                  "total_eval": balance.get("total_eval", 0),
                  "cash": balance.get("cash", 0),
                  "profit_loss": balance.get("profit_loss", 0),
              },
          }
          snap_path.parent.mkdir(parents=True, exist_ok=True)
          snap_path.write_text(
              json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
          )
          log_info(f"시작 스냅샷 저장: {snap_path}")
      except Exception as e:
          log_error(f"시작 스냅샷 저장 실패 (무시): {e}")
  ```

  Expected: 함수 정의 후 `from src.scheduler import _snapshot_holdings_at_open` import 성공.

---

## Task 7: `src/scheduler.py` — `_maybe_generate_report` 추가 + `run_loop` 연결

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: `_maybe_generate_report` 함수를 `_snapshot_holdings_at_open` 아래에 추가한다**

  ```python
  def _maybe_generate_report(started_at: datetime) -> None:
      """장 마감 이후(15:30) 종료된 경우에만 리포트를 생성한다.

      15:30 이전 종료(조기 중단)이면 log_info 메시지만 남기고 반환한다.
      generate_daily_report 예외는 log_error로 처리하고 전파하지 않는다.
      """
      now = datetime.now()
      if now.hour < 15 or (now.hour == 15 and now.minute < 30):
          log_info("장 마감 전 종료: 일별 리포트를 생성하지 않습니다.")
          return
      today = now.strftime("%Y%m%d")
      balance: dict | None = None
      holdings: list | None = None
      try:
          balance, holdings = get_account_info()
      except Exception as e:
          log_error(f"마감 잔고 조회 실패 (리포트에 balance 제외): {e}")
      try:
          from src.reporter import generate_daily_report
          paths = generate_daily_report(today, balance_snapshot=balance, holdings_snapshot=holdings)
          for p in paths:
              log_info(f"리포트 생성 완료: {p}")
      except Exception as e:
          log_error(f"일별 리포트 생성 실패: {e}")
  ```

  Expected: 함수 정의 후 `from src.scheduler import _maybe_generate_report` import 성공.

- [ ] **Step 2: `run_loop`에 `started_at` 캡처를 추가한다**

  `src/scheduler.py`의 `run_loop` 함수 내 `_write_status()` 호출(149번째 줄) 바로 아래에 다음 한 줄을 삽입한다.

  ```python
      started_at: datetime = datetime.now()
  ```

  삽입 후 해당 블록의 모양:
  ```python
      prev_handler = signal.signal(signal.SIGINT, signal_handler)
      _write_status()
      started_at: datetime = datetime.now()   # 추가
      state = _load_state()
  ```

  Expected: `run_loop` 내에서 `started_at` 변수가 루프 시작 시각을 보유한다.

- [ ] **Step 3: `run_loop`의 `finally` 블록에 `_maybe_generate_report(started_at)` 호출을 추가한다**

  현재 `finally` 블록(186~188번째 줄):
  ```python
      finally:
          _clear_status()
          signal.signal(signal.SIGINT, prev_handler)
  ```

  을 아래로 교체한다:
  ```python
      finally:
          _clear_status()
          _maybe_generate_report(started_at)
          signal.signal(signal.SIGINT, prev_handler)
  ```

  Expected: `run_loop` 종료 시 항상 `_maybe_generate_report`가 호출된다.

- [ ] **Step 4: `run_loop`에 `_snapshot_holdings_at_open()` 호출을 추가한다**

  `run_loop`의 `while running:` 루프 첫 진입 시 시장이 열린 상태임을 확인한 직후에 스냅샷을 저장한다. `is_market_open()` 체크 이후, `_check_circuit_breaker` 호출 이전에 삽입한다.

  현재 루프 내 해당 부분:
  ```python
              if _check_circuit_breaker(state):
                  log_info("서킷 브레이커 발동으로 거래 중단.")
                  break
  ```

  을 아래로 교체한다:
  ```python
              _snapshot_holdings_at_open()

              if _check_circuit_breaker(state):
                  log_info("서킷 브레이커 발동으로 거래 중단.")
                  break
  ```

  Expected: 시장이 열려 있는 첫 번째 루프 틱에 스냅샷이 저장되며, 이미 저장된 경우는 `snap_path.exists()` 체크로 무시된다.

---

## Task 8: `src/scheduler.py` — `log_trade` SELL 호출에 `pnl=pnl` 전달

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: `_check_holdings`의 `log_trade` SELL 호출에 `pnl` 키워드 인자를 추가한다**

  `src/scheduler.py`의 `_check_holdings` 함수 내 `log_trade` 호출(64~68번째 줄):

  ```python
                  log_trade(
                      h["stock_code"], "SELL", result["current_price"],
                      h["quantity"], result["current_price"] * h["quantity"],
                      result["reason"],
                  )
  ```

  을 아래로 교체한다:

  ```python
                  log_trade(
                      h["stock_code"], "SELL", result["current_price"],
                      h["quantity"], result["current_price"] * h["quantity"],
                      result["reason"],
                      pnl=pnl,
                  )
  ```

  Expected: SELL 거래 기록 시 CSV의 `pnl` 컬럼에 실현손익이 기록된다.

---

## Task 9: `main.py` — `report` 서브커맨드 추가

**Files:**
- Modify: `main.py`

- [ ] **Step 1: `cmd_report` 함수를 `cmd_analyze` 함수 아래에 추가한다**

  `src/main.py`의 `cmd_analyze` 함수(66~88번째 줄) 아래에 다음 함수를 추가한다.

  ```python
  def cmd_report(args):
      from datetime import datetime
      from src.reporter import generate_daily_report

      date_str = args.date if args.date else datetime.now().strftime("%Y%m%d")
      display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
      print(f"\n=== 리포트 생성 ({display_date}) ===")
      try:
          paths = generate_daily_report(date_str)
          for p in paths:
              print(f"  생성: {p}")
      except Exception as e:
          print(f"  오류: {e}", file=__import__('sys').stderr)
      print()
  ```

  Expected: 함수 정의 후 `python main.py report --help` 실행 성공 (서브커맨드 등록 후 확인).

- [ ] **Step 2: `main()` 함수 내 argparse에 `report` 서브커맨드를 등록한다**

  `main()` 함수 내 `p_analyze` 블록(109~111번째 줄) 아래에 다음 블록을 추가한다.

  ```python
      p_report = sub.add_parser("report", help="일별 리포트 (재)생성")
      p_report.add_argument("--date", default=None, metavar="YYYYMMDD", help="대상 날짜 (기본: 오늘)")
      p_report.set_defaults(func=cmd_report)
  ```

  Expected: `python main.py report --help` 실행 시 `--date YYYYMMDD` 옵션이 표시된다.

---

## Task 10: `tests/test_reporter.py` — 단위 테스트

**Files:**
- Create: `tests/test_reporter.py`

- [ ] **Step 1: 파일을 생성하고 fixture 및 `_parse_trades_csv` 테스트를 작성한다**

  ```python
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
  ```

  Expected: `pytest tests/test_reporter.py::test_parse_trades_csv_missing_file -v` → PASSED.

- [ ] **Step 2: `_calc_pnl_stats` 테스트를 추가한다**

  Step 1 파일 끝에 추가한다.

  ```python
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
  ```

  Expected: 5개 테스트 모두 PASSED.

- [ ] **Step 3: `_parse_signals_log` 및 `_parse_errors_log` 테스트를 추가한다**

  ```python
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
  ```

  Expected: 5개 테스트 모두 PASSED.

- [ ] **Step 4: `_format_summary`, `_format_signals`, `_format_errors` 스냅샷 테스트를 추가한다**

  ```python
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
  ```

  Expected: 10개 테스트 모두 PASSED.

- [ ] **Step 5: `_format_balance` 및 `_atomic_write` 테스트를 추가한다**

  ```python
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
  ```

  Expected: 3개 테스트 모두 PASSED.

- [ ] **Step 6: 전체 테스트 스위트를 실행하여 통과 확인한다**

  ```bash
  python -m pytest tests/test_reporter.py -v
  ```

  Expected: 전체 테스트 PASSED (실패 없음).

  ```bash
  python -m pytest tests/test_config.py tests/test_scheduler.py tests/test_analyzer.py -v
  ```

  Expected: 기존 테스트 전부 PASSED. 새 변경으로 인한 회귀 없음.

---

## Self-Review Checklist

**Spec Coverage 확인:**

| 요구사항 (design.md) | 구현 태스크 |
|---|---|
| 4종 리포트 파일 생성 | Task 5 (`generate_daily_report`) |
| 15:30 이후에만 자동 생성 | Task 7 (`_maybe_generate_report` 조건) |
| SIGINT graceful shutdown 연동 | Task 7 (`finally` 블록) |
| 15:30 이전 종료 시 log_info만 | Task 7 (`_maybe_generate_report` 조건분기) |
| `kis-trader report [--date]` CLI | Task 9 |
| 예외 발생 시 log_error 후 계속 | Task 7 (try/except) |
| CSV 없는 날 "거래 없음" | Task 3 (`_parse_trades_csv` 빈 리스트), Task 4 (`_format_summary` 거래 없음 분기) |
| 리포트 파일 원자적 쓰기 | Task 3 (`_atomic_write`) |
| `pnl` CSV 컬럼 추가 | Task 2 (`log_trade`) |
| SELL 시 `pnl=pnl` 전달 | Task 8 |
| 사이드카 파일 기록 (signals, errors) | Task 2 |
| `start_snapshot_YYYYMMDD.json` 저장 | Task 6 (`_snapshot_holdings_at_open`) |
| `_file_lock` 통합 잠금 | Task 2 |
| `get_logs_dir()` config 헬퍼 | Task 1 |
| 단위 테스트 6종 함수 커버 | Task 10 |
| 구버전 CSV 하위 호환 | Task 3 Step 2, Task 10 Step 1 |

**Placeholder 스캔:** "TBD", "TODO", "handle edge cases", "similar to Task", "add appropriate" — 없음.

**Type Consistency 확인:**
- `_file_lock`: Task 2 전체에서 일관 사용.
- `generate_daily_report(date_str, balance_snapshot, holdings_snapshot)`: Task 5와 Task 7, Task 9에서 동일 시그니처.
- `_format_summary` 파라미터: Task 4 Step 1 정의와 Task 5 Step 1 호출 일치.
- `_atomic_write(path: Path, content: str)`: Task 3 Step 1 정의와 Task 5 내 호출 일치.
