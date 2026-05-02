# Feature Design: Daily Trading Report Logs

## 1. Feature Goal

Market-close time에 자동으로 역할별 일별 리포트 파일 4종을 `logs/` 디렉토리에 생성하여, 사용자가 귀가 후 오늘 자동매매 결과를 한눈에 확인할 수 있게 한다.

---

## 2. Completion Criteria (EARS format)

- When `run_loop` exits the main `while` loop after 15:30 detection (normal market-close), the system shall generate all 4 report files under `logs/` for today's date before the process terminates.
- When the user sends SIGINT (Ctrl-C) after 15:30, the system shall generate all 4 report files as part of the graceful shutdown sequence.
- When the user sends SIGINT before 15:30 (mid-session interrupt), the system shall skip report generation and log a single `log_info` message indicating the run was interrupted before market close.
- When `kis-trader report` is invoked on the CLI, the system shall (re)generate all 4 report files for today and print the path of each generated file.
- When `kis-trader report --date YYYYMMDD` is invoked, the system shall (re)generate all 4 report files for the specified date using the existing `trades_YYYYMMDD.csv` and `signals_YYYYMMDD.log` sidecar files, without requiring a live process.
- When report generation raises an exception, the system shall catch the exception, write the traceback via `log_error`, and continue the shutdown sequence without crashing the process.
- When `trades_YYYYMMDD.csv` does not exist for a given date, the system shall still generate `summary_YYYYMMDD.log` with a "거래 없음" section and empty values for all trade-derived fields.
- When the current date is a weekend or public holiday and `run_loop` is never entered, the system shall not generate any report files.
- When a report file already exists for the target date, the system shall overwrite it atomically (write to `.tmp`, rename).
- When report generation completes, each of the 4 output files shall be a complete, valid plain-text file with no partial writes.

---

## 3. Impact Scope

### Modified Files

| File | Change Type | Description |
|------|-------------|-------------|
| `src/logger.py` | Modified | `log_signal` 및 `log_error` 함수가 각각 `signals_YYYYMMDD.log`, `errors_YYYYMMDD.log` 사이드카 파일에도 동시 기록하도록 확장 |
| `src/scheduler.py` | Modified | `run_loop` finally 블록 및 graceful shutdown 분기에 `generate_daily_report` 호출 추가; 루프 진입 전 `_snapshot_holdings_at_open` 호출 추가 |
| `src/config.py` | Modified | `get_logs_dir()` 헬퍼 함수 추가 (현재 `logger.py`에 인라인으로 정의된 `LOGS_DIR`을 config로 승격) |
| `main.py` | Modified | `report` 서브커맨드 및 `cmd_report` 핸들러 추가 |
| `src/reporter.py` | New | 리포트 생성 전담 모듈. 4개 파일 생성 로직 전체 포함 |
| `tests/test_reporter.py` | New | `reporter.py` 순수 함수 단위 테스트 |

### Dependencies

- External libraries: 추가 없음 (stdlib `csv`, `pathlib`, `os`, `re`, `datetime` 사용)
- Internal modules: `src.config`, `src.logger` (단방향 의존; reporter는 scheduler/trader를 import하지 않음)

---

## 4. Data Collection Strategy

### 핵심 결정: 사이드카 파일 방식 채택

신호 및 에러 데이터를 수집하는 방법으로 아래 세 가지를 검토했다.

| 방식 | 장점 | 단점 |
|------|------|------|
| 인메모리 버퍼 (scheduler에 list 추가) | 추가 I/O 없음 | 프로세스 크래시 시 데이터 유실; scheduler 오염 |
| app.log 사후 파싱 | 추가 코드 최소 | 로그 포맷 변경에 취약; 정규식 파싱 오류 가능성 |
| **사이드카 파일** (`signals_YYYYMMDD.log`, `errors_YYYYMMDD.log`) | 크래시 내성; 독립 파싱; 기존 CSV 패턴과 일치 | logger.py에 파일 핸들러 2개 추가 |

사이드카 파일 방식을 선택한다. 기존 `trades_YYYYMMDD.csv`가 이미 같은 패턴이고, 크래시 후에도 당일 데이터가 보존된다.

### 파일별 데이터 소스

| 리포트 파일 | 데이터 소스 | 수집 시점 |
|------------|------------|----------|
| `summary_YYYYMMDD.log` | `trades_YYYYMMDD.csv` (집계), `state.json` (최종 daily_loss/consecutive_losses), `start_snapshot_YYYYMMDD.json` (보유 종목 시작 시점), `balance_YYYYMMDD.log` (마감 잔고) | 사후 집계 |
| `signals_YYYYMMDD.log` | `signals_YYYYMMDD.log` 사이드카 (실행 중 기록) | 실행 중 실시간 |
| `errors_YYYYMMDD.log` | `errors_YYYYMMDD.log` 사이드카 (실행 중 기록) | 실행 중 실시간 |
| `balance_YYYYMMDD.log` | `get_account_info()` API 호출 (마감 직전 1회) | 마감 시점 라이브 |

### 사이드카 파일 포맷 (logger.py가 기록, reporter.py가 읽기)

`signals_YYYYMMDD.log` 한 줄 포맷 (탭 구분):
```
2026-05-02 09:15:32\t005930\tBUY \t71500\t골든크로스 + MACD 상향 (RSI: 45.2)
```

`errors_YYYYMMDD.log` 한 줄 포맷 (탭 구분):
```
2026-05-02 10:22:11\tERROR\t매도 주문 실패 [005930]: RuntimeError: 주문 실패: ...
```

`start_snapshot_YYYYMMDD.json` 포맷 (run_loop 진입 직후 1회 기록):
```json
{
  "timestamp": "2026-05-02T09:08:55",
  "holdings": [
    {"stock_code": "005930", "stock_name": "삼성전자", "quantity": 5, "avg_price": 70000}
  ],
  "balance": {"total_eval": 5350000, "cash": 2350000, "profit_loss": -150000}
}
```

---

## 5. Interface Definition

### `src/config.py` 추가 함수

```python
def get_logs_dir() -> Path:
    """logs/ 디렉토리 절대 경로. 현재 logger.py의 LOGS_DIR과 동일 경로."""
    return Path(__file__).resolve().parent.parent / "logs"
```

### `src/logger.py` 변경

`log_signal` 함수 시그니처 변경 없음. 내부적으로 사이드카 파일에 추가 기록:

```python
def log_signal(stock_code: str, signal: str, price: int, reason: str = "") -> None:
    # 기존 app.log 기록 유지
    # 추가: logs/signals_YYYYMMDD.log 에 탭 구분 한 줄 append
```

`log_error` 함수 시그니처 변경 없음. 내부적으로 사이드카 파일에 추가 기록:

```python
def log_error(msg: str) -> None:
    # 기존 app.log + error.log 기록 유지
    # 추가: logs/errors_YYYYMMDD.log 에 탭 구분 한 줄 append
```

사이드카 파일 기록 시 `_csv_lock`과 동일하게 `threading.Lock`을 공유 사용한다 (기존 `_csv_lock`을 `_log_lock`으로 범용화하여 재사용).

### `src/reporter.py` 공개 함수

```python
def generate_daily_report(
    date_str: str,                        # "YYYYMMDD" 형식
    balance_snapshot: dict | None = None, # get_account_info() 결과 중 balance; None이면 balance 파일 생략
    holdings_snapshot: list | None = None # get_account_info() 결과 중 holdings; None이면 balance 파일 생략
) -> list[Path]:
    """
    지정 날짜의 4개 리포트 파일을 생성하고 생성된 Path 리스트를 반환한다.
    balance_snapshot/holdings_snapshot이 None이면 balance_YYYYMMDD.log는 생성하지 않는다.
    예외 발생 시 호출자에게 전파한다 (호출자가 log_error로 처리).
    """
```

내부 순수 함수 (단위 테스트 대상):

```python
def _parse_trades_csv(csv_path: Path) -> list[dict]:
    """CSV를 읽어 행 목록 반환. 파일 없으면 []."""

def _calc_pnl_stats(trades: list[dict]) -> dict:
    """
    SELL 행만 필터링하여 집계.
    반환: {
        "total_buy_count": int,
        "total_sell_count": int,
        "realized_pnl": float,   # SELL rows의 pnl 합산
        "win_count": int,        # pnl > 0인 SELL 건수
        "loss_count": int,       # pnl <= 0인 SELL 건수
        "win_rate": float,       # win_count / total_sell_count * 100; sell=0이면 0.0
    }
    P&L 계산: trades CSV에는 amount(=price*qty)가 있으나 avg_price가 없다.
    SELL의 실현손익은 state.json의 daily_loss로부터 읽는다 (아래 별도 설명).
    """

def _parse_signals_log(log_path: Path) -> list[dict]:
    """signals_YYYYMMDD.log 파싱. 파일 없으면 []."""

def _parse_errors_log(log_path: Path) -> list[dict]:
    """errors_YYYYMMDD.log 파싱. 파일 없으면 []."""

def _load_start_snapshot(date_str: str) -> dict | None:
    """start_snapshot_YYYYMMDD.json 로드. 없으면 None."""

def _format_summary(date_str, mode, run_meta, pnl_stats, circuit_breaker_info, start_snap, final_state) -> str:
    """summary 파일 텍스트 반환. 순수 함수."""

def _format_signals(date_str, signals: list[dict]) -> str:
    """signals 파일 텍스트 반환. 순수 함수."""

def _format_errors(date_str, errors: list[dict]) -> str:
    """errors 파일 텍스트 반환. 순수 함수."""

def _format_balance(date_str, balance: dict, holdings: list[dict]) -> str:
    """balance 파일 텍스트 반환. 순수 함수."""

def _atomic_write(path: Path, content: str) -> None:
    """content를 path.tmp에 쓰고 path로 rename. UTF-8."""
```

### `src/scheduler.py` 변경 사항

`run_loop` 내 두 곳에서 `generate_daily_report`를 호출한다:

```python
# 1. run_loop 진입 직후 — 시작 스냅샷 저장
def _snapshot_holdings_at_open() -> None:
    """
    get_account_info() 호출 후 start_snapshot_YYYYMMDD.json 저장.
    API 오류 시 log_error 후 무시 (리포트 미생성이 트레이딩을 막으면 안 됨).
    """

# 2. run_loop의 finally 블록 내 — 리포트 생성
# 기존:
#   finally:
#       _clear_status()
#       signal.signal(signal.SIGINT, prev_handler)
#
# 변경 후:
#   finally:
#       _clear_status()
#       _maybe_generate_report(started_at)   # 추가
#       signal.signal(signal.SIGINT, prev_handler)
```

```python
def _maybe_generate_report(started_at: datetime) -> None:
    """
    장 마감 이후(15:30)에 종료된 경우에만 리포트 생성.
    15:30 이전 종료(조기 중단)이면 log_info 메시지만 남기고 반환.
    generate_daily_report 예외는 log_error로 처리하고 전파하지 않는다.
    """
    now = datetime.now()
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        log_info("장 마감 전 종료: 일별 리포트를 생성하지 않습니다.")
        return
    today = now.strftime("%Y%m%d")
    try:
        balance, holdings = get_account_info()
    except Exception as e:
        log_error(f"마감 잔고 조회 실패 (리포트에 balance 제외): {e}")
        balance, holdings = None, None
    try:
        from src.reporter import generate_daily_report
        paths = generate_daily_report(today, balance_snapshot=balance, holdings_snapshot=holdings)
        for p in paths:
            log_info(f"리포트 생성 완료: {p}")
    except Exception as e:
        log_error(f"일별 리포트 생성 실패: {e}")
```

`_maybe_generate_report`는 `started_at` 파라미터를 받아 `run_meta` (시작 시각)를 summary에 포함시킨다. `started_at`은 `_write_status()` 직후 `datetime.now()`로 캡처한다.

### `main.py` 추가

```python
def cmd_report(args):
    from datetime import datetime
    from src.reporter import generate_daily_report

    date_str = args.date if args.date else datetime.now().strftime("%Y%m%d")
    paths = generate_daily_report(date_str)   # live balance 없이 재생성
    for p in paths:
        print(f"  생성: {p}")
```

argparse 등록:
```python
p_report = sub.add_parser("report", help="일별 리포트 (재)생성")
p_report.add_argument("--date", default=None, metavar="YYYYMMDD", help="대상 날짜 (기본: 오늘)")
p_report.set_defaults(func=cmd_report)
```

---

## 6. Realized P&L 및 Win Rate 계산 방법

`trades_YYYYMMDD.csv`에는 매도 당시의 `price`(현재가)와 `quantity`는 있으나 `avg_price`(매입가)가 없다. `scheduler._check_holdings`에서 pnl은 `(current_price - avg_price) * qty`로 계산되어 `state["daily_loss"]`에 누적된다.

따라서 실현손익은 `state.json`의 `daily_loss` 필드를 정답 소스로 사용한다. 이는 기존 로직과 일관성을 유지하는 유일한 방법이다.

Win rate 계산을 위한 "건별 손익 부호"는 trades CSV에서 파생할 수 없다. 대신 `errors_YYYYMMDD.log`에 기록된 서킷 브레이커 발동 여부와 `state.json`의 `consecutive_losses`로 패배 구간을 추정하되, win_count/loss_count의 정확한 값은 다음 방법으로 보완한다.

**구체적 방법**: `log_trade` 호출 시점에 pnl 부호를 추가로 기록하는 것이 가장 정확하다. 이를 위해 `log_trade` 시그니처에 선택적 `pnl` 파라미터를 추가한다:

```python
# src/logger.py
def log_trade(
    stock_code: str,
    action: str,
    price: int,
    quantity: int,
    amount: int,
    reason: str = "",
    pnl: float | None = None,   # 추가: SELL 시에만 scheduler가 전달
) -> None:
    # CSV에 pnl 컬럼 추가 기록 (BUY는 None → 빈 문자열)
```

```python
# trades_YYYYMMDD.csv 헤더 변경
# datetime, stock_code, action, price, quantity, amount, reason, pnl
```

`scheduler._check_holdings`의 `log_trade` 호출:
```python
log_trade(
    h["stock_code"], "SELL", result["current_price"],
    h["quantity"], result["current_price"] * h["quantity"],
    result["reason"],
    pnl=pnl,    # 추가
)
```

이로써 `_calc_pnl_stats`는 CSV의 `pnl` 컬럼만으로 win_count / loss_count / realized_pnl을 정확히 집계할 수 있다. `state.json`의 `daily_loss`는 검증용 크로스체크에만 사용한다.

> **기존 CSV와의 하위 호환**: pnl 컬럼이 없는 구버전 CSV를 읽을 경우 `_parse_trades_csv`가 해당 컬럼을 `None`으로 처리하여 win_rate를 "N/A"로 표시한다.

---

## 7. 파일 포맷 (인간 판독 레이아웃)

### 7-1. `summary_YYYYMMDD.log`

```
================================================================
  KIS 자동매매 일별 요약 — 2026-05-02
================================================================
  모드          : mock
  시작 시각     : 2026-05-02 09:08:55
  종료 시각     : 2026-05-02 15:30:12
  감시 종목     : 005930, 000660, 035720

[ 매매 실적 ]
  총 매수 건수  :    3 건
  총 매도 건수  :    2 건
  실현 손익     :  +12,500 원
  승률          :  50.0 %  (1승 / 1패)

[ 서킷 브레이커 ]
  발동 여부     : 아니오

[ 일별 위험 상태 (최종) ]
  누적 일손실   :  +12,500 원
  연속 손실     :    0 회

[ 보유 종목 변화 ]
  -- 시작 시점 --
  005930  삼성전자       5주  @70,000원
  -- 종료 시점 --
  005930  삼성전자       3주  @70,000원
  000660  SK하이닉스     2주  @185,000원

================================================================
```

### 7-2. `signals_YYYYMMDD.log`

```
================================================================
  KIS 신호 이력 — 2026-05-02
================================================================
  총 신호 건수 : 14 건  (BUY: 3 / SELL: 2 / HOLD: 9)

[ 005930 삼성전자 ]
  09:15:32  BUY   71,500  골든크로스 + MACD 상향 (RSI: 45.2)
  10:45:01  HOLD  71,200  대기 (RSI: 52.1, MACD: 12.3)
  13:22:18  SELL  72,100  익절 도달 (2.3%)

[ 000660 SK하이닉스 ]
  09:15:34  HOLD  183,500  대기 (RSI: 61.0, MACD: -5.2)
  10:45:03  BUY   184,200  볼린저 하단 돌파 + RSI 과매도 (28.5)

================================================================
```

### 7-3. `errors_YYYYMMDD.log`

```
================================================================
  KIS 오류/이상 이벤트 — 2026-05-02
================================================================
  총 오류 건수 : 2 건

  10:22:11  매도 주문 실패 [005930]: RuntimeError: 주문 실패: 잔고 부족
  12:05:44  루프 실행 중 오류: requests.exceptions.ConnectionError: ...

================================================================
```

오류 없는 날:
```
================================================================
  KIS 오류/이상 이벤트 — 2026-05-02
================================================================
  오류 없음

================================================================
```

### 7-4. `balance_YYYYMMDD.log`

```
================================================================
  KIS 마감 잔고 스냅샷 — 2026-05-02 15:30:08
================================================================
  총 평가금액   :   8,420,000 원
  예수금        :   5,870,000 원
  평가 손익     :    -180,000 원

[ 보유 종목 ]
  종목코드  종목명           수량    평균가      현재가      수익률      손익
  -------  ---------------  ------  ----------  ----------  --------  ----------
  005930   삼성전자             3주     70,000원    72,100원    +3.0%    +6,300원
  000660   SK하이닉스           2주    185,000원   183,500원    -0.8%   -3,000원

================================================================
```

---

## 8. Atomic Write 전략

모든 리포트 파일은 `_atomic_write(path, content)` 를 통해 쓴다:

```
1. path.parent.mkdir(parents=True, exist_ok=True)
2. tmp_path = path.with_suffix(path.suffix + ".tmp")
3. tmp_path.write_text(content, encoding="utf-8")
4. tmp_path.replace(path)   # os.replace()와 동일 — 원자적 rename
```

Windows에서 `Path.replace()`는 대상 파일이 이미 존재해도 덮어쓴다 (Python 3.3+). 쓰기 도중 프로세스가 종료되면 `.tmp` 파일만 남고 기존 완성 파일은 보존된다.

---

## 9. 사이드카 파일 기록 위치 및 잠금

`src/logger.py`의 `_csv_lock`을 `_file_lock`으로 이름을 바꾸고 CSV 쓰기, signals 사이드카 쓰기, errors 사이드카 쓰기 모두에 재사용한다. 세 파일은 서로 다른 경로이므로 잠금 경합이 최소화된다. 스레드 안전성이 필요한 이유는 scheduler의 메인 루프가 단일 스레드이므로 실제 경합은 없지만, 미래 확장(병렬 종목 처리)을 대비한다.

---

## 10. 시작 스냅샷 저장 위치

`start_snapshot_YYYYMMDD.json`은 `logs/` 디렉토리에 저장한다. reporter가 읽는 모든 소스 파일이 `logs/`에 있으므로 일관성을 유지한다. `.gitignore`에 이미 `logs/` 가 포함되어 있으리라 가정한다.

`config.py`에 경로 함수를 추가하지 않는다. `reporter.py`가 `config.get_logs_dir() / f"start_snapshot_{date_str}.json"` 으로 직접 구성한다.

---

## 11. Edge Cases 및 처리 방법

| 케이스 | 처리 방법 |
|--------|----------|
| 주말 / 공휴일 — `run_loop` 미실행 | `_maybe_generate_report`가 호출되지 않으므로 파일 미생성. 정상 동작. |
| 장 마감 전 SIGINT (조기 종료) | `_maybe_generate_report`에서 15:30 미만임을 감지, `log_info` 후 반환. 파일 미생성. |
| 서킷 브레이커로 조기 종료 | `_check_circuit_breaker`가 `True`를 반환하고 `break`로 루프 이탈. `finally` 블록은 항상 실행되므로 `_maybe_generate_report` 호출됨. 15:30 이후이면 정상 생성, 이전이면 미생성. |
| 거래 없는 날 (CSV 없음) | `_parse_trades_csv`가 `[]` 반환. `summary`에 "거래 없음" 출력. `signals`, `errors`, `balance` 파일은 정상 생성. |
| `signals_YYYYMMDD.log` 사이드카 없음 | `_parse_signals_log`가 `[]` 반환. `signals_YYYYMMDD.log` 리포트 파일은 "신호 없음" 출력. |
| 마감 잔고 API 호출 실패 | `_maybe_generate_report` 내에서 catch, `log_error`. `balance=None`으로 `generate_daily_report` 호출. `balance_YYYYMMDD.log` 미생성. 나머지 3개는 정상 생성. |
| `--date` 로 과거 날짜 재생성 | `generate_daily_report`에 `balance_snapshot=None`으로 호출. `balance_YYYYMMDD.log` 미생성. 사이드카 파일이 있으면 정상 재생성. |
| `state.json`이 오늘 날짜가 아닌 경우 | `generate_daily_report`는 `state.json`을 읽을 때 날짜를 검증하여 불일치이면 `daily_loss=0, consecutive_losses=0`으로 처리. |
| 두 번 이상 리포트 생성 (재실행) | atomic write로 덮어씀. 기존 파일 소실 없음. |

---

## 12. 구현 태스크 (파일별 순서)

| 순서 | 태스크 | 파일 | 예상 복잡도 |
|------|--------|------|-------------|
| 1 | `get_logs_dir()` 함수 추가 | `src/config.py` | Low |
| 2 | `log_trade`에 `pnl` 파라미터 추가 + CSV 헤더 변경 | `src/logger.py` | Low |
| 3 | `log_signal`에 사이드카 파일 기록 추가 | `src/logger.py` | Low |
| 4 | `log_error`에 사이드카 파일 기록 추가 | `src/logger.py` | Low |
| 5 | `reporter.py` 생성 — `_atomic_write`, `_parse_*`, `_calc_pnl_stats` 구현 | `src/reporter.py` | Mid |
| 6 | `reporter.py` — `_format_*` 함수 4개 구현 | `src/reporter.py` | Mid |
| 7 | `reporter.py` — `generate_daily_report` 조립 함수 구현 | `src/reporter.py` | Low |
| 8 | `scheduler.py` — `_snapshot_holdings_at_open` 추가 | `src/scheduler.py` | Low |
| 9 | `scheduler.py` — `_maybe_generate_report` 추가 + `run_loop` 연결 | `src/scheduler.py` | Mid |
| 10 | `scheduler.py` — `started_at` 캡처 및 전달 | `src/scheduler.py` | Low |
| 11 | `main.py` — `report` 서브커맨드 추가 | `main.py` | Low |
| 12 | `test_reporter.py` — 단위 테스트 작성 | `tests/test_reporter.py` | Mid |
| 13 | `scheduler.py` — `log_trade` 호출 시 `pnl=pnl` 전달 | `src/scheduler.py` | Low |

---

## 13. 테스트 전략

### 단위 테스트 대상 (`tests/test_reporter.py`)

모든 아래 함수는 파일 I/O와 외부 API에 독립적이므로 순수하게 테스트 가능하다.

| 함수 | 테스트 케이스 |
|------|-------------|
| `_parse_trades_csv` | 정상 CSV, 빈 CSV, 파일 없음, 구버전(pnl 컬럼 없음) |
| `_calc_pnl_stats` | trades=[]: 모든 카운터 0, win_rate 0.0 / SELL 1건 이익 / SELL 2건(1승1패) / BUY 전용(SELL 없음) |
| `_parse_signals_log` | 정상 파일, 빈 파일, 파일 없음, 형식 불일치 행(스킵) |
| `_parse_errors_log` | 정상 파일, 파일 없음 |
| `_format_summary` | 거래 없음 케이스, 서킷 브레이커 발동 케이스, 정상 케이스 — 출력 문자열에 필수 필드 포함 여부 |
| `_format_signals` | 신호 없음, 다종목 신호 — 종목별 그룹핑 확인 |
| `_format_balance` | 보유 종목 없음, 다종목 정렬 |
| `_atomic_write` | 정상 쓰기 후 파일 존재 확인, `.tmp` 파일 잔재 없음 확인 (tmp_path 사용) |

### 수동 검증 항목

- `kis-trader run` 실행 후 15:30 이후 Ctrl-C: 4개 파일 생성 확인
- `kis-trader run` 실행 후 15:30 이전 Ctrl-C: 파일 미생성 + log_info 메시지 확인
- `kis-trader report --date YYYYMMDD`: 사이드카 파일 기반 재생성 확인
- 마감 잔고 API 모킹 실패 시 3개 파일만 생성 확인
- CSV `pnl` 컬럼 없는 구버전 파일 읽기 시 "N/A" 처리 확인

---

## 14. Assumptions (불확실 항목)

- `logs/` 디렉토리는 `.gitignore`에 이미 포함되어 있다고 가정한다. 포함되지 않았다면 `.gitignore`에 `logs/` 추가가 필요하다.
- `start_snapshot_YYYYMMDD.json`은 리포트 생성 후에도 삭제하지 않는다. 사용자가 직접 정리하거나 향후 별도 cleanup 태스크에서 처리한다.
- `balance_YYYYMMDD.log`의 "현재가"는 마감 직후 API 조회 시점의 가격이며 정확히 15:30 종가는 아닐 수 있다. 이는 설계 범위 내에서 허용한다.
- `signals_YYYYMMDD.log` 사이드카의 "종목명" 필드는 `log_signal`이 종목명을 받지 않으므로 포함하지 않는다. signals 리포트 파일의 그룹 헤더에도 종목명 대신 종목코드만 사용한다.
