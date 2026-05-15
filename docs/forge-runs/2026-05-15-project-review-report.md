# KIS 자동매매 CLI — 프로젝트 검토 리포트

검토 일자: 2026-05-15
검토 대상: `F:/90_project/01_kis_auto_cli` (전체)
이전 점검: 2026-05-04 (README 기재)

---

## 개요

KIS Developers API 기반 자동매매 CLI. 스윙 전략(5분 간격, 일봉 기반)과 초단타 전략(2초 간격, 현재가 틱 기반)을 병렬 실행한다.
총 9개 소스 파일, 5개 테스트 파일. pyproject.toml + requirements.txt 이중 관리.

**모듈 의존 방향**

```
main.py
 ├── combined.py  → scheduler + scalper
 ├── scheduler.py → analyzer + trader + logger + reporter
 ├── scalper.py   → fetcher + trader + logger
 ├── analyzer.py  → fetcher + config
 ├── trader.py    → fetcher._rate_limit + auth + config
 ├── fetcher.py   → auth + config
 ├── auth.py      → config
 ├── reporter.py  → config + logger (단방향)
 └── config.py    (leaf)
```

---

## Critical — 즉시 수정 필요

### C-1. 상태 파일 비원자적 쓰기 (데이터 손상 위험)

**파일**: `src/scheduler.py:33`, `src/scalper.py:52`

```python
# scheduler.py
path.write_text(json.dumps(state, ...), encoding="utf-8")

# scalper.py
path.write_text(json.dumps(self.state, ...), encoding="utf-8")
```

`reporter.py`에는 `_atomic_write`(tmp → replace)가 구현되어 있으나, `state.json`과 `scalp_state.json`은 여전히 `path.write_text`를 직접 사용한다.
프로세스 강제 종료나 전원 차단 시 파일이 빈 상태 또는 절반만 쓰인 상태로 남는다.
재시작 시 잔고·손실 상태가 올바르게 복구되지 않아 서킷 브레이커가 오작동한다.

**권장 수정**: `reporter._atomic_write`를 `config` 또는 별도 유틸 모듈로 이동하고, `_save_state`와 `ScalpMonitor._save_state` 모두에서 사용한다.

---

### C-2. 일봉 데이터로 5분 간격 스윙 분석 (전략-빈도 불일치)

**파일**: `src/scheduler.py` (run_loop), `src/analyzer.py:112`

스케줄러는 5분마다 `analyze()`를 호출하지만, `analyze()`는 `get_daily_ohlcv(days=60)`를 내부에서 호출한다. 일봉 데이터는 장 중 같은 날에는 변하지 않으므로 동일 신호가 5분마다 반복 생성된다.
골든크로스/데드크로스 조건(전날 vs 오늘 종가)은 하루에 최대 1회만 의미있는 변화가 발생한다.

결과적으로:
- 같은 BUY 신호가 반복 발생하더라도 `holdings_codes` 체크로 중복 매수는 차단된다.
- 그러나 API 호출(현재가 + 일봉 OHLCV)이 매 사이클 불필요하게 발생해 429 리스크가 증가한다.
- 실제로 유효한 분석 빈도는 의도(5분)와 달리 하루 1회 수준이다.

**권장 수정**: 일봉 기반 신호는 하루 1회(장 시작 직후)에만 산출하고 캐싱한다. 5분 간격은 손절/익절 체크(현재가만 필요)에만 사용하도록 구조를 분리한다.

---

### C-3. 백테스트 모듈 부재 (실전 전환 전 필수)

전략(MA5/MA20 골든크로스 + RSI + MACD + 볼린저 밴드)의 파라미터가 검증된 적 없다.
`MODE=real` 전환 전 1년치 일봉 기반 백테스트가 필수이나 관련 코드가 없다.
슬리피지·수수료는 `config.py`에 설정값이 있으나 백테스트에서 사용되지 않는다.

---

## High — 기능 안정성

### H-1. scalp 모멘텀 전략의 휩쏘 위험

**파일**: `src/scalper.py:57-73`

```python
breakout = price >= max(previous)
rising = series[-1] > series[-2] > series[-3]
```

- 현재가 틱 6개(기본값)의 단순 상승 패턴만 확인한다.
- 거래량, 호가 잔량, 체결강도를 전혀 고려하지 않는다.
- 수수료(0.015%) + 거래세(0.18%) 합계 약 0.195%인데 익절 기준이 0.5%로 매우 좁다.
- 취소 조건인 손절(-0.3%) 기준도 수수료 포함 시 사실상 -0.1% 수준의 체결이 필요하다.

실제 시장에서는 호가 스프레드와 체결 지연으로 인해 신호 발생 → 체결 사이에 가격이 이미 반전될 수 있다.

---

### H-2. Windows에서 graceful shutdown 미보장

**파일**: `src/scheduler.py:314`, `src/combined.py:34`

```python
signal.signal(signal.SIGINT, signal_handler)
```

`SIGINT`(Ctrl+C)만 처리한다. Windows에서 작업 스케줄러가 프로세스를 종료하거나 콘솔 창을 닫을 때 발생하는 `SIGBREAK`(signal 21)와 `SIGTERM`을 처리하지 않는다.
이 경우 `finally` 블록의 `_clear_status()`, `_maybe_generate_report()`, `_save_state()` 등이 실행되지 않는다.

---

### H-3. 잔고 페이지네이션 미구현

**파일**: `src/trader.py:198-225`

`_inquire_balance_raw()`에서 `CTX_AREA_NK100`을 항상 빈 문자열로 고정해 첫 번째 페이지만 조회한다.
응답의 `CTX_AREA_NK100`을 확인해 다음 페이지가 있으면 재조회하는 루프가 없다.
보유 종목이 100개를 초과할 경우 일부가 누락된다(개인 투자자 기준 실제 발생 가능성은 낮지만 코드 정확성 문제).

---

### H-4. 에러 후 silent continue + 외부 알림 부재

**파일**: `src/scheduler.py:289-291`

```python
except Exception as e:
    log_error(f"Swing cycle failed: {e}")
return True
```

API 오류, 네트워크 오류 등이 발생하면 `log_error`만 기록하고 다음 사이클을 계속 진행한다.
같은 오류가 반복 발생해도 텔레그램/이메일/슬랙 등 외부 알림이 없어 운영자가 인지하지 못할 수 있다.

---

## Medium — 개선 권장

### M-1. ATR 사이징 vs 고정 % 손절 불일치

**파일**: `src/analyzer.py:67-99`, `src/config.py:87-91`

포지션 크기는 `ATR × 2` 손절 거리 기준으로 산정(`calc_position_size`)하지만, 실제 손절 청산은 `STOP_LOSS_PCT=-3.0%` 고정값으로 판단한다.
ATR이 크면 작은 수량을 사고(리스크 조절), ATR이 작으면 많은 수량을 사는 의도인데, 청산 기준이 ATR과 무관하면 사이징의 목적이 달성되지 않는다.

---

### M-2. 로그 파일 무한 누적

**파일**: `src/logger.py`

`app.log`와 `error.log`는 `TimedRotatingFileHandler(backupCount=30)`으로 30일 자동 순환되나, 아래 파일들은 정리 정책이 없다:

- `trades_YYYYMMDD.csv` — 무한 누적
- `raw_signals_YYYYMMDD.log` — 무한 누적
- `raw_errors_YYYYMMDD.log` — 무한 누적
- `start_snapshot_YYYYMMDD.json` — 무한 누적
- `summary_YYYYMMDD.log`, `signals_YYYYMMDD.log`, `errors_YYYYMMDD.log`, `balance_YYYYMMDD.log` — 무한 누적

---

### M-3. KR_HOLIDAYS 런타임 고정 (임시휴장 미반영)

**파일**: `src/scheduler.py:14`

```python
KR_HOLIDAYS = holidays.KR()
```

모듈 import 시 1회 평가되어 이후 갱신되지 않는다. 더 중요한 문제는 `holidays` 라이브러리가 법정 공휴일만 포함하며, 증권사가 별도 공지하는 임시 휴장일(반일 장 포함)은 반영되지 않는다.
KIS API의 영업일 조회 API를 사용하는 것이 더 정확하다.

---

### M-4. combined.py에서 run_loop의 리포트/스냅샷 기능 미사용

**파일**: `src/combined.py:26-75`

`run_all_loop`는 `run_swing_cycle`을 직접 호출하지만, `run_loop`에서 제공하는:
- `_snapshot_holdings_at_open()` — 장 시작 스냅샷
- `_write_status()` / `_clear_status()` — PID 상태 파일
- `_maybe_generate_report()` — 일별 리포트 자동 생성

이 세 가지 기능이 `run_all_loop`와 `run_scalp_loop`에서 빠져 있다.
`combined` 모드로 실행하면 일별 리포트가 생성되지 않고 상태 파일도 남지 않는다.

---

### M-5. `_calc_pnl_stats`의 action 필드 하드코딩 (BUY_PARTIAL 등 누락)

**파일**: `src/reporter.py:59-61`

```python
buy_rows  = [t for t in trades if t.get("action", "").strip() == "BUY"]
sell_rows = [t for t in trades if t.get("action", "").strip() == "SELL"]
```

실제 거래 로그에는 `BUY_PARTIAL`, `SELL_PARTIAL`, `SCALP_BUY`, `SCALP_SELL`, `SCALP_BUY_PARTIAL`, `SCALP_SELL_PARTIAL` 등 6가지 action이 기록될 수 있다.
현재 코드는 `BUY`와 `SELL` 정확히 일치하는 것만 집계하므로, 초단타·부분체결 거래가 리포트 통계에서 제외된다.

---

### M-6. 언어 혼용 (한/영)

소스 코드 전체에서 한국어와 영어 로그 메시지가 혼용된다.

- 영어: `"Swing strategy started"`, `"Market closed"`, `"Shutdown signal received"`
- 한국어: `"매수 가능 현금 부족"`, `"시작 스냅샷 저장"`
- `scheduler.py`의 스윙 로직은 영어, `scalper.py`의 로그는 일부 한국어

운영 환경에서 로그를 grep하거나 알림을 필터링할 때 일관성이 없으면 탐지 규칙 작성이 어렵다.

---

## Low — 장기 개선

### L-1. 보안: 토큰 파일 Windows에서 권한 미제한

**파일**: `src/auth.py:18-24`

```python
def _restrict_permissions(path):
    if os.name == "posix":
        os.chmod(path, 0o600)
```

Windows(현재 운영 환경)에서는 `os.name == "nt"`이므로 권한 제한이 적용되지 않는다.
`.kis/token_cache.json`에 access_token이 평문으로 저장되며 다른 사용자가 읽을 수 있다.
Windows 자격증명 관리자(`keyring` 라이브러리)를 사용하는 것이 권장된다.

---

### L-2. 테스트 커버리지 공백

현재 테스트가 없는 모듈:
- `src/auth.py` — 토큰 캐시 만료/재발급 흐름
- `src/fetcher.py` — API 응답 파싱, 429 retry
- `src/trader.py` — 매수/매도 주문, 체결 조회
- `src/scalper.py` — ScalpMonitor 상태 전환, 신호 로직
- `src/combined.py` — 전체 루프 동작

특히 `scalper.py`의 `_buy_signal`과 `_sell_signal` 로직은 파라미터 조합이 복잡해 단위 테스트가 유용하다.

---

### L-3. requirements.txt와 pyproject.toml 이중 관리

`requirements.txt`와 `pyproject.toml`이 동일한 의존성을 중복 관리한다. `uv.lock`이 있으므로 `pyproject.toml`을 단일 진입점으로 사용하고 `requirements.txt`를 제거하거나 `uv pip compile`로 자동 생성하는 방식이 일관적이다.

---

### L-4. `fetcher.py`가 private 함수 노출

**파일**: `src/trader.py:8`

```python
from src.fetcher import _rate_limit
```

`_rate_limit`은 fetcher 내부 함수(`_` 접두사)인데 trader에서 직접 import해 사용한다. rate limit 기능을 public API로 만들거나(`rate_limit`), 또는 auth/config처럼 공유 유틸로 분리하는 것이 더 명확하다.

---

### L-5. `main.py`에서 datetime 중복 import

**파일**: `main.py:4, 103`

```python
from datetime import datetime      # 모듈 상단
...
from datetime import datetime      # cmd_report 함수 내부
```

함수 내 중복 import는 제거해도 무방하다(기능에는 영향 없음).

---

## 긍정적으로 잘 구현된 부분

1. **config.py 단일 진입점**: 모든 환경변수 접근이 `src/config.py`를 통해 이루어져 설정 관리가 깔끔하다. 타입 변환과 기본값도 한 곳에서 처리한다.

2. **reporter.py 단방향 의존**: reporter는 scheduler/trader를 import하지 않아 순환 의존 없이 독립적으로 테스트 가능하다. `_atomic_write` 구현도 올바르다.

3. **수수료/거래세 반영**: `_calc_realized_pnl`에서 매수 수수료, 매도 수수료, 거래세를 모두 차감해 실현손익을 계산한다.

4. **체결 조회 fallback**: mock 환경 등에서 체결 조회가 실패해도 추정값으로 처리하고 `estimated: True` 플래그를 명시한다.

5. **테스트 품질**: 작성된 테스트들(analyzer, config, scheduler, reporter)은 edge case를 잘 커버하고, monkeypatch를 올바르게 사용한다.

6. **ScalpMonitor 상태 관리**: 날짜/모드/종목코드 불일치 시 상태를 초기화하는 방어 로직이 구현되어 있다.

---

## 우선순위 요약

| 순위 | ID | 내용 | 예상 작업량 |
|------|----|------|-------------|
| 1 | C-1 | 상태 파일 원자적 쓰기 | 소 (5줄 미만) |
| 2 | C-2 | 일봉 신호 캐싱 분리 | 중 |
| 3 | H-4 | 에러 반복 시 외부 알림 | 중 |
| 4 | M-4 | combined 모드 리포트/스냅샷 추가 | 소 |
| 5 | M-5 | `_calc_pnl_stats` action 매칭 수정 | 소 |
| 6 | H-2 | SIGTERM/SIGBREAK 처리 | 소 |
| 7 | M-1 | ATR 손절 기준 통일 | 중 |
| 8 | M-2 | 로그 파일 정리 정책 | 소 |
| 9 | L-2 | 테스트 커버리지 확대 | 대 |
| 10 | C-3 | 백테스트 모듈 구현 | 대 |

---

*검토 완료: 2026-05-15*
