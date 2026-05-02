"""환경변수/설정 단일 진입점.

모든 환경변수 접근은 이 모듈을 통해 수행한다.
타입 변환과 기본값을 한 곳에서 관리하여 호출부 분산을 방지한다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DOMAIN_REAL = "https://openapi.koreainvestment.com:9443"
DOMAIN_MOCK = "https://openapivts.koreainvestment.com:29443"


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
def get_token_cache_path() -> Path:
    """토큰 캐시 파일 경로. 디렉토리는 호출 측에서 생성한다."""
    return Path.home() / ".kis" / "token_cache.json"


# --- 상태 파일 ---
def get_state_path() -> Path:
    """일별 거래 상태 파일 경로."""
    return Path.home() / ".kis" / "state.json"


def get_status_path() -> Path:
    """프로세스 상태 파일 경로 (PID, 시작 시간 등)."""
    return Path.home() / ".kis" / "status.json"


# --- 트레이딩 파라미터 ---
def get_target_stocks() -> list[str]:
    raw = os.getenv("TARGET_STOCKS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def get_max_buy_amount() -> int:
    return int(os.getenv("MAX_BUY_AMOUNT", "500000"))


def get_max_daily_loss() -> float:
    return float(os.getenv("MAX_DAILY_LOSS", "100000"))


def get_max_consecutive_losses() -> int:
    return int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))


# --- 분석 파라미터 ---
def get_stop_loss_pct() -> float:
    return float(os.getenv("STOP_LOSS_PCT", "-3.0"))


def get_take_profit_pct() -> float:
    return float(os.getenv("TAKE_PROFIT_PCT", "5.0"))


# --- ATR 기반 포지션 사이징 ---
def get_atr_multiplier() -> float:
    """ATR 기반 손절 거리 배수. 기본값 2.0 (2×ATR 손절 거리)."""
    return float(os.getenv("ATR_MULTIPLIER", "2.0"))


def get_atr_risk_pct() -> float:
    """1회 매수 한도 대비 허용 손실 비율. 기본값 0.01 (1%)."""
    return float(os.getenv("ATR_RISK_PCT", "0.01"))


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
    raw = os.getenv("SCALP_STOCK", "").strip()
    if raw:
        return raw
    targets = get_target_stocks()
    return targets[0] if targets else ""


def get_scalp_interval_sec() -> float:
    return float(os.getenv("SCALP_INTERVAL_SEC", "5"))


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


def get_scalp_state_path() -> Path:
    return Path.home() / ".kis" / "scalp_state.json"
