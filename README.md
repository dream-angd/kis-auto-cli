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

코드 분석 기반(2026-04-17) 개선 항목. 우선순위 순.

### 🔴 Critical — 즉시 수정 필요

- **[보안] `token_cache.json` 보안 이슈** — 평문 JSON으로 저장됨. `.gitignore` 추가 + 저장 경로를 `~/.kis/`로 이동 (`src/auth.py:46`)
- **[안정성] `trader.py` rate limit 미적용** — 잔고조회/주문 API에 rate limit + retry 추가 필요 (`src/trader.py:31, 80`)
- **[버그] `daily_loss` 실현손익 계산 오류** — `h["profit_loss"]`는 평가손익(미실현)이라 서킷브레이커 기준값이 틀림. 매도 체결 후 실현손익 별도 누적 필요 (`src/scheduler.py:35`)

### 🟠 High — 기능 안정성

- **[안정성] `daily_loss` 재시작 시 초기화** — 메모리에만 있어 재시작 시 손실 누적 초기화. 파일/DB 영속화 필요 (`src/scheduler.py:103`)
- **[안정성] 주문 API retry/오류처리 없음** — 일시적 네트워크 오류 시 주문 누락. `_api_get` 패턴 적용 (`src/trader.py`)
- **[구조] 환경변수 중앙 관리 없음** — `os.getenv()` 분산. `src/config.py` 단일 진입점으로 통합

### 🟡 Medium — 개선 권장

- **[정확도] RSI 계산 방식 개선** — 단순 SMA → Wilder's SMMA 표준 공식 (`src/analyzer.py:10`)
- **[기능] `analyze` 명령어 보유 종목 연동** — `avg_price=0` 고정 → 실제 평균단가 전달 (`main.py:66`)
- **[기능] `history` 명령어 날짜 지정 옵션** — `--date 20260416` 추가 (`main.py:35`)
- **[로깅] 로그 파일 전략 개선** — INFO 레벨 파일 저장, CSV 파일 잠금 처리 (`src/logger.py`)

### 🔵 Low — 장기 개선

- **[테스트] 단위 테스트 코드 작성** — `unittest.mock` 기반 테스트 환경 구축
- **[패키징] `pyproject.toml` 추가** — `pip install -e .`, `kis-trader` 커맨드 진입점 정의
- **[모니터링] 프로세스 상태 확인 수단 없음** — PID 파일 또는 `status.json` 생성
- **[전략] 포지션 사이징 개선** — 변동성(ATR) 기반 사이징 또는 비중 분산 (`src/trader.py:44`)

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
