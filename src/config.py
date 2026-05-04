"""환경변수/설정 단일 진입점.

모든 환경변수 접근은 이 모듈을 통해 수행한다.
타입 변환과 기본값을 한 곳에서 관리하여 호출부 분산을 방지한다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DOMAIN_REAL = "https://openapi.koreainvestment.com:9443"
DOMAIN_MOCK = "https://openapivts.koreainvestment.com:29443"

# 자주 쓰는 종목명 — 사용자는 .env의 STOCK_NAMES로 추가/덮어쓰기 가능
_BUILTIN_STOCK_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "035420": "NAVER",
    "035720": "카카오",
    "028260": "삼성물산",
    "005490": "POSCO",
    "051910": "LG화학",
    "068270": "셀트리온",
    "207940": "삼성바이오",
    "247540": "에코프로비엠",
    "035900": "JYP Ent.",
    "105560": "KB금융",
    "055550": "신한지주",
    "086790": "하나금융",
    "010140": "삼성중공업",
    "042660": "한화오션",
    "047810": "한국항공우주",
    "003670": "포스코홀딩스",
    "012450": "한화에어로스페이스",
}


def _parse_stock_names_env() -> dict[str, str]:
    """STOCK_NAMES=005930:삼성전자,000660:하이닉스 형식 파싱."""
    raw = os.getenv("STOCK_NAMES", "").strip()
    if not raw:
        return {}
    out = {}
    for pair in raw.split(","):
        if ":" in pair:
            code, name = pair.split(":", 1)
            code, name = code.strip(), name.strip()
            if code:
                out[code] = name
    return out


def get_stock_name(stock_code: str) -> str:
    """종목명 조회. STOCK_NAMES env > 내장 사전 > 종목코드 그대로."""
    if not stock_code:
        return ""
    overrides = _parse_stock_names_env()
    if stock_code in overrides:
        return overrides[stock_code]
    return _BUILTIN_STOCK_NAMES.get(stock_code, stock_code)


def format_stock(stock_code: str) -> str:
    """로그용 표기. '삼성전자(005930)' 형식. 이름 없으면 코드만."""
    name = get_stock_name(stock_code)
    if name and name != stock_code:
        return f"{name}({stock_code})"
    return stock_code


# --- 모드 / 도메인 ---
def get_mode() -> str:
    return os.getenv("MODE", "mock").lower()


def get_base_url() -> str:
    return DOMAIN_REAL if get_mode() == "real" else DOMAIN_MOCK


# --- 인증 ---
def get_app_keys() -> tuple[str | None, str | None]:
    if get_mode() == "real":
        return os.getenv("KIS_APP_KEY"), os.getenv("KIS_APP_SECRET")
    return os.getenv("KIS_MOCK_APP_KEY"), os.getenv("KIS_MOCK_APP_SECRET")


def get_account_no() -> tuple[str, str]:
    """모드에 따른 계좌번호를 (CANO, ACNT_PRDT_CD) 튜플로 반환."""
    if get_mode() == "real":
        acct = os.getenv("KIS_ACCOUNT_NO", "")
    else:
        acct = os.getenv("KIS_MOCK_ACCOUNT_NO", os.getenv("KIS_ACCOUNT_NO", ""))
    parts = acct.split("-")
    if len(parts) != 2:
        raise ValueError(f"계좌번호 형식 오류: {acct} (예: 44407084-01)")
    return parts[0], parts[1]


# --- 토큰 캐시 ---
def get_data_dir() -> Path:
    raw = os.getenv("KIS_DATA_DIR", "").strip()
    return Path(raw).expanduser() if raw else BASE_DIR / ".kis"


def get_token_cache_path() -> Path:
    """토큰 캐시 파일 경로. 디렉토리는 호출 측에서 생성한다."""
    return get_data_dir() / "token_cache.json"


# --- 상태 파일 ---
def get_state_path() -> Path:
    """일별 거래 상태 파일 경로."""
    return get_data_dir() / "state.json"


def get_status_path() -> Path:
    """프로세스 상태 파일 경로 (PID, 시작 시간 등)."""
    return get_data_dir() / "status.json"


# --- 트레이딩 파라미터 ---
def get_target_stocks() -> list[str]:
    """[Deprecated] swing/scalp 분리 이전 전체 감시 종목. get_swing_stocks() 권장."""
    raw = os.getenv("TARGET_STOCKS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def get_swing_stocks() -> list[str]:
    """Swing 전략 대상 종목. SWING_STOCKS 우선, 없으면 TARGET_STOCKS fallback."""
    raw = os.getenv("SWING_STOCKS", "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return get_target_stocks()


def get_max_buy_amount() -> int:
    """[Deprecated] swing 1회 매수 한도. get_swing_max_buy_amount() 권장."""
    return int(os.getenv("MAX_BUY_AMOUNT", "500000"))


def get_swing_max_buy_amount() -> int:
    """Swing 1회 매수 한도. SWING_MAX_BUY_AMOUNT 우선, 없으면 MAX_BUY_AMOUNT fallback."""
    raw = os.getenv("SWING_MAX_BUY_AMOUNT", "").strip()
    if raw:
        return int(raw)
    return get_max_buy_amount()


def get_max_daily_loss() -> float:
    return float(os.getenv("MAX_DAILY_LOSS", "100000"))


def get_max_consecutive_losses() -> int:
    return int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))


def get_heartbeat_interval_sec() -> int:
    """[scalp 상태] heartbeat 주기. 최소 5초."""
    return max(5, int(os.getenv("HEARTBEAT_INTERVAL_SEC", "30")))


# --- 분석 파라미터 ---
def get_stop_loss_pct() -> float:
    """[Deprecated] swing 손절. get_swing_stop_loss_pct() 권장."""
    return float(os.getenv("STOP_LOSS_PCT", "-3.0"))


def get_take_profit_pct() -> float:
    """[Deprecated] swing 익절. get_swing_take_profit_pct() 권장."""
    return float(os.getenv("TAKE_PROFIT_PCT", "5.0"))


def get_swing_stop_loss_pct() -> float:
    """Swing 손절 %. SWING_STOP_LOSS_PCT 우선, 없으면 STOP_LOSS_PCT fallback."""
    raw = os.getenv("SWING_STOP_LOSS_PCT", "").strip()
    if raw:
        return float(raw)
    return get_stop_loss_pct()


def get_swing_take_profit_pct() -> float:
    """Swing 익절 %. SWING_TAKE_PROFIT_PCT 우선, 없으면 TAKE_PROFIT_PCT fallback."""
    raw = os.getenv("SWING_TAKE_PROFIT_PCT", "").strip()
    if raw:
        return float(raw)
    return get_take_profit_pct()


# --- ATR 기반 포지션 사이징 ---
def get_atr_multiplier() -> float:
    """ATR 기반 손절 거리 배수. 기본값 2.0 (2×ATR 손절 거리)."""
    return float(os.getenv("ATR_MULTIPLIER", "2.0"))


def get_atr_risk_pct() -> float:
    """1회 매수 한도 대비 허용 손실 비율. 기본값 0.01 (1%)."""
    return float(os.getenv("ATR_RISK_PCT", "0.01"))


# --- 거래 비용 (수수료/거래세) ---
def get_buy_fee_rate() -> float:
    """매수 수수료율. 기본 0.015% (증권사별 협의 수수료에 맞춰 조정)."""
    return float(os.getenv("BUY_FEE_RATE", "0.00015"))


def get_sell_fee_rate() -> float:
    """매도 수수료율. 기본 0.015%."""
    return float(os.getenv("SELL_FEE_RATE", "0.00015"))


def get_sell_tax_rate() -> float:
    """매도 거래세율. 기본 0.18% (KOSPI/KOSDAQ 공통)."""
    return float(os.getenv("SELL_TAX_RATE", "0.0018"))


# --- 체결 조회 ---
def get_fill_poll_attempts() -> int:
    """주문 후 체결 조회 재시도 횟수. 기본 3회."""
    return max(1, int(os.getenv("FILL_POLL_ATTEMPTS", "3")))


def get_fill_poll_interval_sec() -> float:
    """주문 후 체결 조회 간격(초). 기본 1.5초."""
    return float(os.getenv("FILL_POLL_INTERVAL_SEC", "1.5"))


# --- 로그 디렉토리 ---
def get_logs_dir() -> Path:
    """logs/ 디렉토리 절대 경로. logger.py의 LOGS_DIR과 동일 경로."""
    return Path(__file__).resolve().parent.parent / "logs"


# --- Scalp strategy ---
def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_scalp_stock() -> str:
    """단일 종목 (하위 호환). SCALP_STOCK 또는 SCALP_STOCKS 첫 번째 또는 TARGET_STOCKS 첫 번째."""
    raw = os.getenv("SCALP_STOCK", "").strip()
    if raw:
        return raw
    multi = get_scalp_stocks()
    return multi[0] if multi else ""


def get_scalp_stocks() -> list[str]:
    """다종목 스캘핑 대상. SCALP_STOCKS=A,B,C 또는 SCALP_STOCK 단일 또는 TARGET_STOCKS fallback."""
    raw = os.getenv("SCALP_STOCKS", "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    one = os.getenv("SCALP_STOCK", "").strip()
    if one:
        return [one]
    return []


def get_scalp_interval_sec() -> float:
    return float(os.getenv("SCALP_INTERVAL_SEC", "2"))


def get_scalp_max_buy_amount() -> int:
    return int(os.getenv("SCALP_MAX_BUY_AMOUNT", "100000"))


def get_scalp_window_size() -> int:
    return max(4, int(os.getenv("SCALP_WINDOW_SIZE", "6")))


def get_scalp_min_momentum_pct() -> float:
    return float(os.getenv("SCALP_MIN_MOMENTUM_PCT", "0.2"))


def get_scalp_take_profit_pct() -> float:
    return float(os.getenv("SCALP_TAKE_PROFIT_PCT", "0.5"))


def get_scalp_stop_loss_pct() -> float:
    return float(os.getenv("SCALP_STOP_LOSS_PCT", "-0.3"))


def get_scalp_trailing_drop_pct() -> float:
    return float(os.getenv("SCALP_TRAILING_DROP_PCT", "0.2"))


def get_scalp_max_hold_sec() -> int:
    return int(os.getenv("SCALP_MAX_HOLD_SEC", "300"))


def is_scalp_trade_enabled() -> bool:
    # Default to real orders only in mock mode. Real mode must opt in explicitly.
    return _get_bool("SCALP_TRADE_ENABLED", get_mode() == "mock")


def get_scalp_state_path(stock_code: str = "") -> Path:
    """종목별 state 파일 경로. 인자 없으면 첫 번째 scalp 종목 사용 (하위 호환)."""
    if not stock_code:
        stocks = get_scalp_stocks()
        stock_code = stocks[0] if stocks else "default"
    return get_data_dir() / f"scalp_state_{stock_code}.json"
