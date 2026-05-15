# Backtest Module Implementation Plan

Date: 2026-05-16
Design: specs/features/backtest-module/design.md

## Tasks

### Task 1: src/backtester.py — 핵심 백테스트 엔진

구현 항목:
1. `load_ohlcv_from_csv(filepath, start, end)` — CSV 로드 + 기간 필터
2. `load_ohlcv_from_api(stock_code, start, end)` — KIS API 청크 호출
3. `_generate_signals(df)` — add_indicators() 결과로 날짜별 BUY/SELL/HOLD 생성
4. `simulate(stock_code, df, initial_capital)` — 거래 시뮬레이션, TradeRecord 리스트 + equity curve 반환
5. `calc_metrics(trades, equity_curve, initial_capital)` — 성과 지표 계산
6. `run_backtest(stock_code, start, end, csv_path, initial_capital)` — 진입점

### Task 2: src/backtest_reporter.py — 결과 출력기

구현 항목:
1. `print_summary(result)` — 콘솔 포맷 출력
2. `save_csv(trades, path)` — 거래 내역 CSV 저장
3. `save_json(result, path)` — 성과 지표 JSON 저장
4. `generate_report(result, stock_code, start, end)` — 통합 호출

### Task 3: main.py — backtest 서브커맨드 추가

구현 항목:
1. `cmd_backtest(args)` 함수
2. `backtest` 서브파서 등록 (stock, --start, --end, --csv, --capital)

### Task 4: tests/test_backtester.py — 단위 테스트

테스트 항목:
1. `load_ohlcv_from_csv` — 정상 로드, 기간 필터, 빈 결과
2. `_generate_signals` — BUY/SELL/HOLD 신호 생성 (최소 26행 데이터 필요)
3. `simulate` — 매수→매도 1회 사이클 P&L 검증
4. `calc_metrics` — total_return, max_drawdown, win_rate 계산 검증

## Dependencies

- pandas (기존 사용)
- numpy (sharpe ratio 계산용, pandas의 std/mean 사용으로 대체 가능)
- 기존 src/analyzer.py, src/config.py

## File Outputs

- `src/backtester.py` (new)
- `src/backtest_reporter.py` (new)
- `main.py` (modified — backtest subcommand 추가)
- `tests/test_backtester.py` (new)
