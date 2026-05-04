# 📈 KIS 자동매매 CLI

> 한국투자증권(KIS) Developers API 기반 자동매매 CLI 프로그램

두 사람이 함께 개발하는 자동매매 도구로, 모의투자 검증 후 실전 매매로 전환하는 것을 목표로 한다.

---

## 🎯 프로젝트 목표

- KIS Developers API를 이용해 자동매매 CLI를 구축한다.
- 모의투자로 **2주 이상** 검증 후 실전 전환한다.
- 손절/익절·서킷브레이커 등 안전장치를 갖춘 자동매매 시스템을 운영한다.

---

## 📁 프로젝트 구조

```
kis-auto-cli/
├── main.py                # Phase 8. CLI 진입점
├── requirements.txt
├── .env                   # API 키, 계좌번호 (git 커밋 금지)
├── .env.example
├── .gitignore
└── src/
    ├── __init__.py
    ├── auth.py            # Phase 2. 인증 모듈
    ├── fetcher.py         # Phase 3. 데이터 수집
    ├── analyzer.py        # Phase 4. 분석 모듈
    ├── trader.py          # Phase 5. 주문 모듈
    ├── scheduler.py       # Phase 6. 스케줄러
    └── logger.py          # Phase 7. 로깅
```

---

## 🚀 빠른 시작

### 1. 환경 준비

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 파일 생성
cp .env.example .env
# .env 편집해서 KIS API 키, 계좌번호 입력
```

### 2. 환경변수(.env) 설정

```bash
KIS_APP_KEY=                  # KIS Developers 앱 키
KIS_APP_SECRET=               # KIS Developers 앱 시크릿
KIS_ACCOUNT_NO=               # 계좌번호
KIS_ACCOUNT_TYPE=01           # 01: 현금, 02: 신용
MODE=mock                     # mock / real
TARGET_STOCKS=005930,000660   # 감시 종목 (쉼표 구분)
MAX_BUY_AMOUNT=500000         # 1회 최대 매수 금액 (원)
STOP_LOSS_PCT=-3.0            # 손절 기준 (%)
TAKE_PROFIT_PCT=5.0           # 익절 기준 (%)
```

> ⚠️ `.env`는 절대 git에 커밋하지 않는다. `.env.example`만 공유.

### 3. 실행

```bash
python main.py run              # 자동매매 시작 (스케줄러 루프 진입)
python main.py status           # 현재 잔고/보유 종목 출력
python main.py history          # 오늘 매매 이력 출력
python main.py analyze 005930   # 특정 종목 신호 확인
```

`run` 실행 시 현재 `MODE`(mock/real) 값이 출력된다.

---

## 🗺️ 개발 순서

```
Phase 1 (환경)
  → Phase 2 (인증)
  → Phase 3 (데이터 수집)
  → Phase 5 (주문)
  → Phase 4 (분석 전략)
  → Phase 6 (스케줄러)
  → Phase 7 (로깅)
  → Phase 8 (CLI)
  → Phase 9 (검증 후 실전)
```

---

## 📋 모듈별 명세

### Phase 1. 환경 준비 ✅

- KIS Developers 가입 및 앱 등록
- APP_KEY, APP_SECRET 발급
- 모의투자 계좌 개설
- 프로젝트 초기 구조, `.gitignore`, `.env.example`, `requirements.txt` 작성

### Phase 2. 인증 모듈 (`auth.py`) ✅

**핵심 함수**

```python
get_access_token()   # 캐시 확인 후 필요 시 재발급
get_base_url()       # MODE에 따라 도메인 반환
get_headers()        # Authorization 헤더 조합 반환
```

**도메인 분기**

| MODE | 기본 URL |
|------|----------|
| mock | https://openapivts.koreainvestment.com:29443 |
| real | https://openapi.koreainvestment.com:9443 |

- 토큰 유효 시간 24시간, 만료 시 자동 재발급
- 토큰은 로컬 파일(`token_cache.json`)에 캐싱

### Phase 3. 데이터 수집 (`fetcher.py`) ✅

**핵심 함수**

```python
get_current_price(stock_code)              # 현재가 조회
get_daily_ohlcv(stock_code, days=60)       # 일봉 OHLCV 조회
subscribe_realtime(stock_codes, callback)  # WebSocket 실시간 수신 (예정)
```

- 429 Too Many Requests 재시도 로직 포함
- 초당 20건 제한 → 호출 간격 제어
- 실시간 WebSocket 자동 재연결 로직은 **미구현(개선 항목)**

### Phase 4. 분석 모듈 (`analyzer.py`) ✅

**핵심 함수**

```python
analyze(stock_code)
# 반환: { "signal": "BUY" | "SELL" | "HOLD",
#         "reason": str,
#         "current_price": int }
```

**기술적 지표**: MA5, MA20, RSI(14), MACD, 볼린저 밴드

**매매 신호**

| 신호 | 조건 |
|------|------|
| BUY | MA5 > MA20 골든크로스 AND RSI < 70 |
| SELL | MA5 < MA20 데드크로스 OR 손절률 도달 OR 익절률 도달 |
| HOLD | 위 조건 외 |

> 백테스트(과거 데이터 검증)는 미구현 — 실전 투입 전 반드시 추가 필요.

### Phase 5. 주문 모듈 (`trader.py`) ✅

**핵심 함수**

```python
buy(stock_code, amount)     # 금액 기준 매수
sell(stock_code, quantity)  # 수량 기준 매도
get_balance()               # 잔고 딕셔너리 반환
get_holdings()              # 보유 종목 리스트 반환
```

- 매수 전 잔고 검증(보유 현금 < `MAX_BUY_AMOUNT` 체크)
- `MODE=mock` 시 모의투자 도메인 사용
- 실전 주문 전 로그 출력

### Phase 6. 스케줄러 (`scheduler.py`) ✅

**실행 흐름**

```
LOOP (5분 간격):
  ├── 장 시간 여부 확인 → 외 시간이면 skip
  ├── 보유 종목 손절/익절 체크 (trader → analyzer)
  ├── 감시 종목 신호 분석 (fetcher → analyzer)
  └── 신호에 따라 주문 실행 (trader)
```

- 장 운영 시간: **09:10 ~ 15:30, 평일** (09:00~09:10은 변동성 과도 구간으로 회피)
- 주말/공휴일 처리 (`holidays` 라이브러리)
- **서킷 브레이커**: 하루 최대 손실 한도 초과 시 거래 자동 중단
- 연속 손실 N회(예: 3회) 발생 시 자동 중단·알림
- `Ctrl+C` graceful shutdown 처리

### Phase 7. 로깅 (`logger.py`) ✅

**파일 구조**

```
logs/
  ├── trades_YYYYMMDD.csv   # 매수/매도 이력
  └── error_YYYYMMDD.log    # 에러 로그
```

**콘솔 출력 포맷**

```
[2026-04-16 09:05:00] 005930 | 신호: BUY  | 가격: 72,400  | 결과: 주문 완료
[2026-04-16 09:10:00] 000660 | 신호: HOLD | 가격: 185,000 | 결과: 없음
```

**`trades_YYYYMMDD.csv` 컬럼**

| 컬럼 | 설명 |
|------|------|
| datetime | 체결 시각 |
| stock_code | 종목 코드 |
| action | BUY / SELL |
| price | 체결가 |
| quantity | 수량 |
| amount | 금액 |
| reason | 신호 사유 |

### Phase 8. CLI (`main.py`) ✅

| 명령 | 설명 |
|------|------|
| `python main.py run` | 자동매매 시작 |
| `python main.py status` | 현재 잔고/보유 종목 출력 |
| `python main.py history` | 오늘 매매 이력 출력 |
| `python main.py analyze 005930` | 특정 종목 신호 확인 |

### Phase 9. 검증 & 배포 🔲

**모의투자 검증**

- 모의투자 2주 이상 실전 시뮬레이션
- 백테스트 수익 대비 실전 수익 비교 (목표: 백테스트의 50~70% 이상)
- 손절/익절 로직 케이스 테스트
- 429 에러 재시도 로직 테스트
- 비정상 종료 후 재시작 시 상태 복구 확인

**실전 전환**

- `MODE=real` 전환
- `MAX_BUY_AMOUNT` 소액(5~10만원)으로 시작
- 손절 로직 활성화 확인
- 첫 실전 주문 로그 확인

**자동 실행 (선택)**

- Windows 작업 스케줄러 등록 (장 시작 전 자동 실행)

---

## 🔍 개발 전 핵심 고려사항

### 안전장치

1. **서킷 브레이커**: 하루 최대 손실 한도 / 연속 손실 N회 발생 시 자동 거래 중단 — 단순 손절/익절보다 상위 안전장치.
2. **손절/익절 기준**은 반드시 설정.

### 검증

3. **백테스트**: 과거 데이터로 전략 검증 필수. 백테스트 수익의 **50~70%만 실전에서 나온다**고 가정. 슬리피지·수수료 포함 계산.
4. **과적합(Overfitting) 경고**: 상승장/하락장/횡보장 각 구간별로 검증.
5. **슬리피지 & 거래 수수료**: 시장가 주문 미체결 가능성, KIS 수수료 모두 신호 계산 시 반영.

### 운영

6. **API 호출 제한**: 초당 최대 20건. 종목당 API 2개(현재가 + 분봉) → **10종목이 한계**. 감시 종목 늘릴 시 설계 단계에서 고려.
7. **장 시작 직후 09:00~09:10 회피**: 기관/프로그램 매매로 변동성 극단 → 09:10부터 시작.
8. **WebSocket 재연결 처리**: 끊김 시 자동 재연결 + 구독 재등록 — 오래된 시세 매매 사고 방지.
9. **포지션 사이징**: 신호 강도에 따른 투자 금액 조절(현재는 `MAX_BUY_AMOUNT` 고정).
10. **지속 모니터링**: 자동이라도 매일 로그 확인 필수.
11. **단순하게 시작**: 하루 1회 매매 같은 단순 형태부터 → 숙달 후 실시간으로 확장.

---

## ⚠️ 주의사항

- ⚠️ **`.env` 파일 절대 git push 금지**
- ⚠️ **실전 전환 전 반드시 모의투자 2주 이상 운용**
- ⚠️ **`MAX_BUY_AMOUNT`는 소액(5~10만원)으로 시작**
- ⚠️ **손절 로직 없이 실전 절대 금지**

---

## ✅ 개선 할 일 목록

최종 갱신: 2026-05-04 (v0.1.0). 우선순위 순.

> **2026-05-04 반영 완료**:
> - `daily_loss` 부호 처리 버그, 시장가 체결가 미사용, 부분체결/미체결 처리, 수수료·거래세 반영 손익
> - state 파일 atomic write (`config.atomic_write_text`)
> - swing 종목별 분리 (SWING_STOCKS/MAX/PCT 신규), scalp 다종목 + KRX 자동 매핑(FinanceDataReader, 24h 캐시)
> - scalp 종목별 독립 thread (한 종목 지연이 다른 종목에 영향 없음)
> - scalp 호가 잔량 검증 (`SCALP_BID_ASK_RATIO_MIN`, 가짜 풀돌이 필터)
> - scalp 타임아웃 실수익 기준, 추적손절 0.3 → 0.5
> - heartbeat B 형식 + 잔고/swing 보유 자동 표시
> - swing 종목별 try/except 격리 (한 종목 분석 실패가 다른 종목 매매를 막지 않음)
> - 5xx/429 retry 3회 → 5회 (fetcher, trader 모두), 지수 백오프

### 🔴 Critical — 즉시 수정 필요

- **[검증] 백테스트 모듈 부재** — 전략(MA cross + RSI + BB + 모멘텀 + 호가)이 검증된 적 없는 파라미터. `MODE=real` 전환 전 1년치 일봉/분봉 기반 백테스트 필수. 그리드 서치로 모멘텀·익절·손절·호가 임계 조합 검증

### 🟠 High — 기능 안정성

- **[전략] swing 5분 사이클 vs 일봉 데이터 불일치** — swing이 5분마다 돌지만 `get_daily_ohlcv`는 일봉. 같은 일봉으로 동일 신호 반복. 분봉(15분/60분) 도입 또는 사이클 주기 1시간+로 조정 권장 (`src/scheduler.py` × `src/analyzer.py`)
- **[전략] swing MA5/MA20 단순 골든크로스 노이즈 취약** — 일봉 횡보장에서 휩쏘 빈번. EMA 도입 또는 추세 필터(예: 200일선 위) 추가 검토 (`src/analyzer.py:_check_*`)
- **[전략] swing MACD 조건 약함** — `macd > macd_signal`만 봄. 둘 다 음수여도 통과되어 진짜 추세 없을 때 BUY 발생. `macd > 0 AND macd > signal AND 히스토그램 증가` 등 조건 강화 (`src/analyzer.py:analyze`)
- **[전략] scalp 호가 외 추가 알파 부재** — 호가 잔량 검증은 도입됐으나 거래량 가속·체결강도(매수체결/매도체결 비율) 등은 미사용. 단순 가격 모멘텀의 한계 보완 필요
- **[안정성] 시그널 핸들러 `SIGINT`만 처리** — Windows console close, 작업 스케줄러 강제 종료 시 graceful shutdown 보장 안 됨. `SIGTERM`, Windows `SIGBREAK` 처리 추가 (`src/scheduler.py:run_loop`, `src/combined.py:run_*_loop`)
- **[버그] 잔고 페이지네이션 미구현** — `output1`만 읽고 `CTX_AREA_NK100` 무시. 보유 종목 100개 초과 시 일부 누락 (`src/trader.py:_inquire_balance_raw`)

### 🟡 Medium — 개선 권장

- **[정합성] ATR 사이징 vs `%` 손절 기준 불일치** — 포지션 크기는 `ATR×2` 손절 거리로 잡지만 청산은 `SWING_STOP_LOSS_PCT=-3%` 고정. 사이징 정신과 어긋남. 청산도 ATR 기반으로 통일 권장 (`src/analyzer.py:calc_position_size` × `_check_stop_loss_take_profit`)
- **[운영] 에러 후 silent continue + 알림 채널 부재** — `log_error` 후 다음 사이클 진행. 같은 에러 반복 시 조용히 누락. 텔레그램/Slack/이메일 임계값 알림 도입 권장 (`src/scheduler.py`, `src/scalper.py`)
- **[로깅] 일별 CSV/raw 파일 정리 정책 없음** — `app.log`/`error.log`는 `TimedRotatingFileHandler`로 30일 회전되지만, `trades_YYYYMMDD.csv` / `raw_errors_*.log` / `raw_signals_*.log` / `start_snapshot_*.json` 등은 무한 누적. 30일 이전 자동 삭제 cron 또는 startup 정리 필요 (`src/logger.py`, `src/reporter.py`)
- **[운영] `KR_HOLIDAYS` import 시 1회 평가** — 임시휴장(반장 등) 미반영. KIS 영업일 API 활용 또는 매일 자정 갱신 권장 (`src/scheduler.py:14`)

### 🔵 Low — 장기 개선

- **[보안] `.env` 평문 저장** — Windows 자격증명 관리자 / OS keyring 활용 권장
- **[테스트] 통합 테스트 커버리지 부족** — fetcher / trader / auth / scalper / combined의 mock API 응답 테스트 추가 필요. 현재 87 테스트는 analyzer / config / reporter / scheduler 위주 (`tests/`)
- **[일관성] 다국어 혼용** — 로그·주석·메시지 한/영 섞임. 한 언어로 통일 (외부 공유 시 일관성)

---

## 🚧 큰 작업 (별도 PR 가치)

| 항목 | 작업량 | 우선순위 | 비고 |
|------|--------|---------|------|
| **백테스트 모듈** | 1~2일 | ⭐ 최우선 | 모든 파라미터의 데이터 기반 검증. FinanceDataReader 일봉 + KIS 분봉. 그리드 서치 + 결과 리포트 |
| **분봉 데이터 도입** (swing) | 0.5~1일 | High | 5분/15분/60분 분봉으로 swing 사이클 의미 살림. 위 백테스트와 함께 진행하면 효율적 |
| **거래량 가속 / 체결강도** (scalp) | 0.5일 | Medium | scalp 알파 보강. 매 사이클 누적 거래량 vs 평균 비교, 매수체결/매도체결 비율 |
| **알림 채널 도입** | 0.5일 | Medium | 텔레그램 봇 또는 Slack webhook. 매수/매도/에러/서킷 발동 시 푸시 |
| **백테스트 + 분봉 + 거래량** 묶음 | 2~3일 | — | 셋 다 같이 가는 게 효율적. 분봉 데이터로 백테스트하면서 거래량 알파도 검증 |

---

## 🔀 Git 정보

| 항목 | 내용 |
|------|------|
| Repository | `kis-auto-cli` |
| Remote URL | https://github.com/dream-angd/kis-auto-cli.git |
| 기본 브랜치 | `master` |

### 브랜치 전략

- `master` — 메인 브랜치 (배포 가능 상태 유지)
- `feature/*` — 기능 개발 (예: `feature/buy-order`)
- `fix/*` — 버그 수정 (예: `fix/auth-token`)
- `hotfix/*` — 긴급 수정

> 💡 master에 직접 커밋하지 말고 feature 브랜치에서 작업 후 머지를 권장.

### 커밋 컨벤션

| 타입 | 설명 |
|------|------|
| `feat` | 새 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `docs` | 문서 수정 |
| `test` | 테스트 코드 추가/수정 |
| `chore` | 빌드/설정 변경 |

**예시**

```
feat: 이동평균선 매수 전략 추가
fix: 토큰 만료 시 재발급 오류 수정
refactor: auth 모듈 코드 정리
```

### .gitignore 주요 항목

- `.env` — API 키, 계좌번호 등 민감 정보
- `__pycache__/`
- `*.log`
- `.claude/` — Claude Code 설정 (로컬 전용)

---

## 🔗 참고 링크

- [KIS Developers 포털](https://apiportal.koreainvestment.com)
- [GitHub Repository](https://github.com/dream-angd/kis-auto-cli)
