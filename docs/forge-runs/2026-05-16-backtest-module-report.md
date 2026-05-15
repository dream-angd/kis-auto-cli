# Forge Run Report — Backtest Module

Date: 2026-05-16
Branch: feature/backtest-module
Task: 백테스트 모듈 구현

## S1 · Classify
TASK_DESC: 백테스트 모듈 신규 구현 (데이터 로더, 신호 재현, 거래 시뮬레이터, 성과 지표, CLI 통합)

## S2-3 · Design
설계 문서: `specs/features/backtest-module/design.md`

핵심 설계 결정:
- `analyzer.add_indicators()`만 재사용, `analyze()`는 API 호출 포함이라 미사용
- 신호 조건을 analyzer.py와 동일하게 백테스터 내부에서 재구현
- 외부 프레임워크 없이 순수 pandas + 표준 라이브러리로 구현
- scalp 전략은 일봉 데이터 불가로 제외, CLI 인터페이스에만 파라미터 보존

## S4 · Plan
계획 문서: `docs/superpowers/plans/2026-05-16-backtest-module.md`

## S5 · Language
Python → developer-backend-python / python-code-reviewer

## S6 · Branch
`feature/backtest-module` 생성 완료

## S7 · Tasks

### Task 1: src/backtester.py
- `load_ohlcv_from_csv()` — CSV 로드 + 기간 필터
- `load_ohlcv_from_api()` — KIS API 청크 호출
- `_generate_signals()` — add_indicators() 기반 신호 생성
- `simulate()` — 포지션/현금/수수료/손절익절 시뮬레이션
- `calc_metrics()` — 총수익률, MDD, 샤프비율, 승률, Profit Factor
- `run_backtest()` — 통합 진입점

### Task 2: src/backtest_reporter.py
- `print_summary()` — 콘솔 출력 (60자 구분선 포맷)
- `save_csv()` — 거래 내역 CSV
- `save_json()` — 성과 지표 JSON
- `generate_report()` — 통합 호출

### Task 3: main.py
- `cmd_backtest()` 함수 추가
- `backtest` 서브파서 (stock, --start, --end, --csv, --capital)

### Task 4: tests/test_backtester.py
- 18개 단위 테스트 (4개 클래스)
- `infer_datetime_format` pandas 2.0 호환성 버그 수정 후 전체 통과

## S8 · Final Review
- `analyzer.py` 수정 없음 확인
- 수수료 계산: buy_fee + sell_fee + sell_tax 모두 반영
- 마지막 날 강제 청산 구현 확인
- 보유 중 손절/익절 신호 우선 처리 확인

## S9 · Test Results

```
tests/test_backtester.py: 18 passed
tests/ (전체): 105 passed, 0 failed, 0 skipped
```

## Changed Files

| 파일 | 상태 |
|------|------|
| `src/backtester.py` | new |
| `src/backtest_reporter.py` | new |
| `main.py` | modified |
| `tests/test_backtester.py` | new |
| `specs/features/backtest-module/design.md` | new |
| `docs/superpowers/plans/2026-05-16-backtest-module.md` | new |

## Blockers
없음
