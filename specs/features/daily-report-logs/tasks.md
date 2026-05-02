# Implementation Tasks

## Task List

| Order | Task | File | Status | Notes |
|-------|------|------|--------|-------|
| 1 | `get_logs_dir()` 함수 추가 | `src/config.py` | Done | 파일 끝에 추가 |
| 2 | `_file_lock` 이름 변경 + `log_trade` pnl 파라미터 + CSV 헤더 변경 | `src/logger.py` | Done | `_csv_lock` → `_file_lock` 전체 교체 |
| 3 | `log_signal` 사이드카 파일 기록 추가 | `src/logger.py` | Done | signals_YYYYMMDD.log append |
| 4 | `log_error` 사이드카 파일 기록 추가 | `src/logger.py` | Done | errors_YYYYMMDD.log append |
| 5 | `reporter.py` 생성 — `_atomic_write`, `_parse_*`, `_calc_pnl_stats`, `_load_*` | `src/reporter.py` | Done | 신규 파일 |
| 6 | `reporter.py` — `_format_*` 4개 함수 | `src/reporter.py` | Done | 순수 함수 |
| 7 | `reporter.py` — `generate_daily_report` 조립 함수 | `src/reporter.py` | Done | |
| 8 | `scheduler.py` — `_snapshot_holdings_at_open` 추가 | `src/scheduler.py` | Done | `_clear_status` 아래 삽입 |
| 9 | `scheduler.py` — `_maybe_generate_report` 추가 + `run_loop` 연결 | `src/scheduler.py` | Done | finally 블록에 호출 추가 |
| 10 | `scheduler.py` — `log_trade` SELL 호출에 `pnl=pnl` 전달 | `src/scheduler.py` | Done | |
| 11 | `main.py` — `report` 서브커맨드 추가 | `main.py` | Done | `cmd_report` + argparse 등록 |
| 12 | `tests/test_reporter.py` — 단위 테스트 26개 | `tests/test_reporter.py` | Done | 전체 PASSED |

## Changed Files Summary

| File | Change Type | Notes |
|------|------------|-------|
| `src/config.py` | Modified | `get_logs_dir()` 함수 추가 (+5 lines) |
| `src/logger.py` | Modified | `_file_lock` 이름 변경, `log_trade` pnl 파라미터, `log_signal`/`log_error` 사이드카 기록 (+30 lines) |
| `src/reporter.py` | New | 리포트 집계/포맷/출력 전담 모듈 (+290 lines) |
| `src/scheduler.py` | Modified | `_snapshot_holdings_at_open`, `_maybe_generate_report` 추가; `run_loop` 수정 (+65 lines) |
| `main.py` | Modified | `cmd_report` 함수 + argparse 등록 (+15 lines) |
| `tests/test_reporter.py` | New | 26개 단위 테스트 (+260 lines) |

## Deviations from Plan

1. **`_SIGNAL_LINE_RE` 정규식**: 플랜 코드 `r"...(\S+)\t(\d+)..."` 에서 signal 토큰 캡처 그룹을 `(\S+)` 대신 `([^\t]+)`으로 변경함. 이유: `log_signal`이 `"BUY "` (BUY + 공백 1자)로 기록하는데, `\S+`는 공백 이전까지만 매칭하므로 탭 구분이 깨짐. `[^\t]+`으로 탭 이전 모든 문자를 캡처해야 정상 파싱됨. (테스트 `test_parse_signals_log_normal` 실패로 발견)

2. **`_format_summary` 실현손익/승률 포맷**: 플랜 코드 `{sign}{pnl:>10,.0f}` → `{sign}{pnl:,.0f}` 로 변경. 이유: 플랜 테스트가 `assert "+12,500" in text`를 요구하는데, `{sign}{pnl:>10,.0f}` 출력이 `"+    12,500"` (부호 분리 + 패딩)이어서 불일치. 플랜 테스트 코드가 기준이므로 포맷 수정.

3. **`_format_balance` 수익률/손익 포맷**: 플랜 코드 `{pr_sign}{pr:>6.1f}%` → `{pr_sign}{pr:.1f}%`, `{hl_sign}{hl:>8,}원` → `{hl_sign}{hl:,}원`으로 변경. 이유: 플랜 테스트가 `assert "+3.0%" in text`, `assert "+6,300원" in text`를 요구하는데, 부호와 숫자 사이 패딩이 생겨 불일치.
