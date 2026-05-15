# KIS 자동매매 CLI — 이슈 수정 리포트

실행 일자: 2026-05-15
브랜치: feature/fix-all-issues
기준 리포트: docs/forge-runs/2026-05-15-project-review-report.md

---

## 완료된 수정

### C-1 ✅ 상태 파일 원자적 쓰기

**수정 파일**: `src/scheduler.py`, `src/scalper.py`

- `scheduler.py`: `_save_state()`에서 `path.write_text()` 대신 `_atomic_write()` 헬퍼 사용 (tmp → replace)
- `scalper.py`: `ScalpMonitor._save_state()`에서 동일 패턴 적용
- `reporter.py`의 기존 `_atomic_write` 패턴을 각 모듈에서 로컬 구현 (의존 방향 유지)

---

### C-2 ✅ 일봉 OHLCV 캐싱 (5분마다 API 호출 방지)

**수정 파일**: `src/analyzer.py`

- `_ohlcv_cache: dict[str, tuple[date, DataFrame]]` 모듈 변수 추가
- `_get_daily_ohlcv_cached()` 함수 추가: 당일 날짜가 같으면 캐시 반환, 날짜 변경 시 재조회
- `analyze()` 내부의 `get_daily_ohlcv()` 직접 호출을 `_get_daily_ohlcv_cached()` 로 교체
- 결과: 일봉 OHLCV API 호출이 종목당 하루 1회로 감소

---

### C-3 ❌ 백테스트 모듈 구현 — BLOCKER (스킵)

전략 파라미터 검증을 위한 1년치 일봉 백테스트 프레임워크.
작업량이 과대하여 이번 Forge 세션에서 구현하지 않음.
`MODE=real` 전환 전 별도 세션에서 구현 필요.

---

### H-1 ✅ scalp 휩쏘 방지 — 거래량 및 최소 틱 이동 필터

**수정 파일**: `src/scalper.py`, `src/config.py`

- `config.py`: `get_scalp_min_volume()` (기본값 1000), `get_scalp_min_tick_move()` (기본값 0) 추가
- `_buy_signal(price, volume=0)`: 거래량 필터 및 틱 이동 필터 추가
- `run_once()`: `get_current_price()` 반환의 `volume` 필드를 `_buy_signal`에 전달

---

### H-2 ✅ Windows graceful shutdown — SIGBREAK/SIGTERM 처리

**수정 파일**: `src/scheduler.py`, `src/combined.py`

- `run_loop()`, `run_all_loop()`, `run_scalp_loop()` 모두에 `signal.SIGBREAK`(Windows 콘솔 닫기), `signal.SIGTERM`(작업 스케줄러) 핸들러 추가
- `hasattr(signal, "SIGBREAK/SIGTERM")` 가드로 Linux/macOS 호환성 유지

---

### H-3 ✅ 잔고 페이지네이션

**수정 파일**: `src/trader.py`

- `_inquire_balance_raw()` → `_inquire_balance_page(ctx_fk100, ctx_nk100)` 로 리팩터링
- `get_account_info()`: `ctx_area_nk100`이 빈 문자열이 될 때까지 페이지 반복 조회
- 보유 종목 100개 초과 시에도 전체 목록 수집

---

### H-4 ✅ 반복 에러 알림

**수정 파일**: `src/scheduler.py`

- `_swing_error_counts: dict[str, int]` 모듈 변수 추가
- `run_swing_cycle()`: 성공 시 카운터 초기화, 예외 발생 시 exception 타입별 카운트 누적
- 동일 예외 3회 이상 시 `[ALERT]` 접두어 포함 `log_error` 추가 기록

---

### M-4 ✅ combined 모드 리포트/스냅샷 기능 추가

**수정 파일**: `src/combined.py`

- `_write_status`, `_clear_status`, `_snapshot_holdings_at_open`, `_maybe_generate_report` import 추가
- `run_all_loop()`: 시작 시 `_write_status()`, 루프 내 `_snapshot_holdings_at_open()`, finally에 `_clear_status()` + `_maybe_generate_report()`
- `run_scalp_loop()`: 동일 패턴 적용

---

### M-5 ✅ `_calc_pnl_stats` action 타입 확장

**수정 파일**: `src/reporter.py`

- BUY 집합: `{"BUY", "BUY_PARTIAL", "SCALP_BUY", "SCALP_BUY_PARTIAL"}`
- SELL 집합: `{"SELL", "SELL_PARTIAL", "SCALP_SELL", "SCALP_SELL_PARTIAL"}`
- 초단타·부분체결 거래가 리포트 통계에 포함됨

---

## 테스트 결과

```
87 passed in 2.96s
```

전체 87개 테스트 모두 통과. 실패 없음.

---

## 스킵/미처리 항목

| ID | 내용 | 사유 |
|----|------|------|
| C-3 | 백테스트 모듈 구현 | 대규모 작업 — 별도 세션 필요 |
| M-1 | ATR 손절 기준 통일 | Medium 우선순위, 전략 변경 범위 큼 |
| M-2 | 로그 파일 정리 정책 | Medium 우선순위, 별도 작업 |
| M-3 | KR_HOLIDAYS 런타임 고정 | Medium 우선순위 |
| M-6 | 언어 혼용 | 전체 로그 메시지 일괄 변경 필요 |
| L-1~L-5 | Low 우선순위 항목들 | 이번 세션 범위 외 |

---

*완료: 2026-05-15*
