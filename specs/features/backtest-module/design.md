# Backtest Module Design

## Overview

KIS 자동매매 CLI에 백테스트 기능을 추가한다.
기존 `analyzer.py`의 신호 로직을 수정 없이 재사용하여 역사적 OHLCV 데이터에 적용한다.

## Architecture

```
main.py (backtest subcommand)
    └── src/backtester.py       # 핵심 엔진
    └── src/backtest_reporter.py # 결과 출력/파일 저장
```

## Data Flow

```
CSV 파일 or KIS API
    → load_ohlcv() → pd.DataFrame (date, open, high, low, close, volume)
    → analyzer.add_indicators() → 지표 추가
    → signal_replay() → 날짜별 BUY/SELL/HOLD 신호
    → simulate_trades() → 포지션/자산 추적
    → calc_metrics() → 성과 지표
    → backtest_reporter → 콘솔 출력 + CSV/JSON 파일
```

## Module: src/backtester.py

### 1. Data Loader

```python
def load_ohlcv_from_csv(filepath: str, start: str, end: str) -> pd.DataFrame
def load_ohlcv_from_api(stock_code: str, start: str, end: str) -> pd.DataFrame
```

- CSV 형식: `date,open,high,low,close,volume` (date는 YYYY-MM-DD 또는 YYYYMMDD)
- API 호출은 KIS `get_daily_ohlcv`를 기간별로 청크 분할 호출
- `start`/`end`는 `YYYY-MM-DD` 문자열, 포함 구간

### 2. Signal Engine

`analyzer.add_indicators(df)` 호출 후 날짜 순으로 순회하며 매일 신호를 생성한다.

신호 생성 로직은 `analyzer.py`의 내부 함수를 직접 import하여 재사용한다:
- `_calc_ma`, `_calc_rsi`, `_calc_macd`, `_calc_bollinger`, `_calc_atr`
- `add_indicators` (공개 함수)

실제 `analyze()` 함수는 API 호출을 포함하므로 **사용하지 않는다**.
대신 `add_indicators()` 결과에서 직접 신호 조건을 추출한다.

신호 판단 조건 (analyzer.py와 동일):
- **BUY**: 골든크로스(MA5 > MA20, 전일 MA5 <= MA20) + RSI < 70 + MACD > MACD_signal
- **BUY**: close <= bb_lower + RSI < 30
- **SELL**: 데드크로스(MA5 < MA20, 전일 MA5 >= MA20)
- **SELL**: close >= bb_upper + RSI > 70
- **SELL**: 보유 중 손절(stop_loss_pct) 또는 익절(take_profit_pct) 조건
- **HOLD**: 그 외

### 3. Trade Simulator

```python
@dataclass
class Position:
    stock_code: str
    qty: int
    avg_price: float
    entry_date: str

@dataclass
class TradeRecord:
    date: str
    action: str        # BUY | SELL
    price: float
    qty: int
    amount: float
    fee: float
    pnl: float         # SELL 시 실현손익 (세후)
    reason: str
```

거래 비용:
- 매수 수수료: `config.get_buy_fee_rate()` (기본 0.015%)
- 매도 수수료: `config.get_sell_fee_rate()` (기본 0.015%)
- 매도 거래세: `config.get_sell_tax_rate()` (기본 0.18%)

포지션 관리:
- 보유 중 BUY 신호 → 무시 (한 종목 1포지션)
- 보유 중 SELL 신호 → 전량 매도
- 수량: `max_buy_amount // close_price` (config.get_max_buy_amount() 사용)
- 마지막 날 포지션 강제 청산 (종가 기준)

### 4. Metrics Calculator

```python
def calc_metrics(trades: list[TradeRecord], equity_curve: list[float], initial_capital: float) -> dict
```

지표:
- `total_return_pct`: (최종자산 - 초기자산) / 초기자산 × 100
- `max_drawdown_pct`: 최대 낙폭 (equity curve 기준)
- `sharpe_ratio`: 일별 수익률 기준 (연율화, risk-free=0)
- `win_rate`: 수익 매도 / 전체 매도
- `profit_factor`: 총수익 / 총손실 절댓값
- `total_trades`: 전체 매도 건수
- `final_capital`: 최종 자산

## Module: src/backtest_reporter.py

```python
def print_summary(result: dict) -> None          # 콘솔 출력
def save_csv(trades: list[dict], path: Path) -> None   # 거래 내역 CSV
def save_json(result: dict, path: Path) -> None        # 성과 지표 JSON
```

출력 파일 위치: `logs/backtest_{stock_code}_{start}_{end}.{csv|json}`

## CLI Integration (main.py)

```
python main.py backtest --stock 005930 --start 2024-01-01 --end 2024-12-31
python main.py backtest --stock 005930 --start 2024-01-01 --end 2024-12-31 --csv data.csv
```

인수:
- `stock`: 종목 코드 (필수)
- `--start`: 시작일 YYYY-MM-DD (필수)
- `--end`: 종료일 YYYY-MM-DD (필수)
- `--csv`: 로컬 CSV 파일 경로 (미지정 시 KIS API 사용)
- `--capital`: 초기 자본금 (기본: 10,000,000)
- `--strategy`: auto (기본, scalp는 일봉 기반 불가로 제외)

## scalp 전략 제외 이유

scalp 전략은 분 단위 틱 데이터가 필요하나, KIS API의 일봉 데이터만으로는 재현 불가.
`--strategy` 인수는 확장을 위해 인터페이스에 남기되 `auto`만 지원한다.

## Constraints

- 외부 백테스트 프레임워크 사용 금지 (backtrader, zipline 등)
- `analyzer.py` 수정 금지
- 단일 종목만 지원 (다종목 확장은 미래 과제)
- 초기 자본금 전액을 현금으로 시작 (레버리지 없음)
