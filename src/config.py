"""환경변수/설정 단일 진입점.

모든 환경변수 접근은 이 모듈을 통해 수행한다.
타입 변환과 기본값을 한 곳에서 관리하여 호출부 분산을 방지한다.
"""
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DOMAIN_REAL = "https://openapi.koreainvestment.com:9443"
DOMAIN_MOCK = "https://openapivts.koreainvestment.com:29443"


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


@lru_cache(maxsize=1)
def _load_stock_master() -> dict[str, str]:
    """KRX 코스피/코스닥 종목 마스터 (코드→이름) 로드.

    .kis/stock_master.json에 24시간 캐시.
    fetch 실패 시 빈 dict 반환 (호출 측이 BUILTIN으로 fallback).
    프로세스 수명 동안 lru_cache로 1회만 빌드.
    """
    cache_path = get_data_dir() / "stock_master.json"
    today_iso = date.today().isoformat()

    # 캐시 유효성 확인 (오늘 날짜)
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if cache.get("date") == today_iso and isinstance(cache.get("data"), dict):
                return cache["data"]
        except Exception:
            pass

    # FinanceDataReader로 KRX 마스터 fetch
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return {}

    try:
        master: dict[str, str] = {}
        for market in ("KOSPI", "KOSDAQ"):
            df = fdr.StockListing(market)
            for _, row in df.iterrows():
                code = str(row.get("Code") or row.get("Symbol") or "").strip().zfill(6)
                name = str(row.get("Name") or "").strip()
                if len(code) == 6 and code.isdigit() and name:
                    master[code] = name
        # 캐시 저장
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"date": today_iso, "data": master}, ensure_ascii=False),
            encoding="utf-8",
        )
        return master
    except Exception:
        # 네트워크 실패 등 — BUILTIN fallback 위해 빈 dict
        return {}


def get_stock_name(stock_code: str) -> str:
    """종목명 조회. 우선순위: STOCK_NAMES env > KRX 마스터 > 코드 그대로."""
    if not stock_code:
        return ""
    overrides = _parse_stock_names_env()
    if stock_code in overrides:
        return overrides[stock_code]
    return _load_stock_master().get(stock_code, stock_code)


def format_stock(stock_code: str) -> str:
    """로그용 표기. '삼성전자(005930)' 형식. 이름 없으면 코드만."""
    name = get_stock_name(stock_code)
    if name and name != stock_code:
        return f"{name}({stock_code})"
    return stock_code


@lru_cache(maxsize=1)
def _build_name_to_code_map() -> dict[str, str]:
    """이름 → 코드 역매핑 (KRX 마스터 + STOCK_NAMES env).

    우선순위 (낮음 → 높음, 후자가 충돌 시 덮어씀):
      1) KRX 마스터 (FinanceDataReader, 24시간 캐시)
      2) STOCK_NAMES env (사용자 정의 — 최우선)
    프로세스 수명 동안 lru_cache로 1회만 빌드.
    """
    out: dict[str, str] = {}
    for code, name in _load_stock_master().items():
        out[name] = code
    for code, name in _parse_stock_names_env().items():
        out[name] = code
    return out


def resolve_stock_code(token: str) -> str:
    """입력이 6자리 종목코드면 그대로, 이름이면 매핑에서 코드로 변환.

    예) '카카오' → '035720', '005380' → '005380'
    매핑에 없는 이름이면 ValueError를 던진다 (오타 즉시 발견 목적).
    """
    token = (token or "").strip()
    if not token:
        return ""
    if len(token) == 6 and token.isdigit():
        return token
    name_map = _build_name_to_code_map()
    if token in name_map:
        return name_map[token]
    raise ValueError(
        f"알 수 없는 종목명/코드: {token!r}. "
        f"종목명 입력 시 KRX 코스피/코스닥에 상장된 정확한 이름이어야 하며, "
        f".env의 STOCK_NAMES로 별칭을 추가할 수 있습니다."
    )


def _resolve_token_list(raw: str) -> list[str]:
    """콤마 구분 입력을 코드 리스트로 변환. 이름·코드 혼용 가능."""
    return [resolve_stock_code(tok) for tok in raw.split(",") if tok.strip()]


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
    """[Deprecated] swing/scalp 분리 이전 전체 감시 종목. get_swing_stocks() 권장.

    이름·코드 혼용 가능 (예: '삼성전자,000660').
    """
    raw = os.getenv("TARGET_STOCKS", "")
    return _resolve_token_list(raw) if raw.strip() else []


def get_swing_stocks() -> list[str]:
    """Swing 전략 대상 종목. SWING_STOCKS 우선, 없으면 TARGET_STOCKS fallback.

    이름·코드 혼용 가능 (예: 'SK하이닉스,005490,셀트리온').
    """
    raw = os.getenv("SWING_STOCKS", "").strip()
    if raw:
        return _resolve_token_list(raw)
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


def get_max_total_exposure() -> int:
    """계좌 전체 노출 한도(원). 보유 평가액 + 신규 주문금액의 상한.

    swing/scalp 양쪽이 각자 매수 직전 검증한다.
    0 또는 음수면 비활성 (무한대 노출 허용).
    예: 5천만 모의 계좌의 30%만 사용하려면 15,000,000.
    """
    return int(os.getenv("MAX_TOTAL_EXPOSURE", "0"))


def get_heartbeat_interval_sec() -> int:
    """[scalp 상태] heartbeat 주기. 최소 5초."""
    return max(5, int(os.getenv("HEARTBEAT_INTERVAL_SEC", "30")))


def get_max_scalp_stocks() -> int:
    """스캘프 동시 모니터링 종목 수 한도. 기본 10. KIS API rate limit(20건/s) 고려."""
    return max(1, int(os.getenv("MAX_SCALP_STOCKS", "10")))


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """tmp 파일에 쓴 후 원본으로 rename — SIGTERM 등 중단 시 파일 손상 방지.

    같은 파티션의 임시 파일이라 os.replace는 atomic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


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
    """매도 거래세율. 기본 0.20% (2026년 기준 KOSPI/KOSDAQ 공통).

    참고: 한국 증권거래세는 시기별로 변동 — 정확한 값은 KRX 공지 또는 PwC tax summary 확인.
    """
    return float(os.getenv("SELL_TAX_RATE", "0.0020"))


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
    """단일 종목 (하위 호환). SCALP_STOCK > SCALP_STOCKS 첫 번째 > 빈 문자열.

    이름·코드 혼용 가능 (예: '카카오' 또는 '035720').
    """
    raw = os.getenv("SCALP_STOCK", "").strip()
    if raw:
        return resolve_stock_code(raw)
    multi = get_scalp_stocks()
    return multi[0] if multi else ""


def get_scalp_stocks() -> list[str]:
    """다종목 스캘핑 대상. SCALP_STOCKS=A,B,C > SCALP_STOCK 단일.

    이름·코드 혼용 가능 (예: 'SCALP_STOCKS=카카오,005380,에코프로비엠').
    """
    raw = os.getenv("SCALP_STOCKS", "").strip()
    if raw:
        return _resolve_token_list(raw)
    one = os.getenv("SCALP_STOCK", "").strip()
    if one:
        return [resolve_stock_code(one)]
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


def get_scalp_slippage_buffer_pct() -> float:
    """매도 판단 시 break-even 계산에 더할 슬리피지 버퍼 (소수, 기본 0.0005 = 0.05%).

    실제 시장가 주문은 호가 spread/유동성에 따라 ±0.05~0.1% 정도 슬리피지 발생.
    break_even = buy_fee + sell_fee + sell_tax + slippage_buffer.
    """
    return float(os.getenv("SCALP_SLIPPAGE_BUFFER_PCT", "0.0005"))


def get_scalp_bid_ask_ratio_min() -> float:
    """매수 진입 시 매수잔량/매도잔량 최소 비율.
    1.0 = 매수≥매도, 1.2 = 매수가 매도보다 20% 많아야 진입.
    0 또는 음수면 호가 검증 비활성.
    """
    return float(os.getenv("SCALP_BID_ASK_RATIO_MIN", "1.0"))


def get_scalp_no_new_buy_before_close_min() -> int:
    """장 마감 N분 전부터 scalp 신규 매수 차단. 기본 15분.
    0 또는 음수면 비활성.
    """
    return max(0, int(os.getenv("SCALP_NO_NEW_BUY_BEFORE_CLOSE_MIN", "15")))


def get_scalp_force_close_before_close_min() -> int:
    """장 마감 N분 전부터 scalp 보유 강제 청산. 기본 12분.
    KIS 정규 거래는 15:20에 끝나므로 12분 전(=15:18)이 안전 마진.
    0 또는 음수면 비활성.
    """
    return max(0, int(os.getenv("SCALP_FORCE_CLOSE_BEFORE_CLOSE_MIN", "12")))


def is_scalp_trade_enabled() -> bool:
    # Default to real orders only in mock mode. Real mode must opt in explicitly.
    return _get_bool("SCALP_TRADE_ENABLED", get_mode() == "mock")


def get_scalp_state_path(stock_code: str = "") -> Path:
    """종목별 state 파일 경로. 인자 없으면 첫 번째 scalp 종목 사용 (하위 호환)."""
    if not stock_code:
        stocks = get_scalp_stocks()
        stock_code = stocks[0] if stocks else "default"
    return get_data_dir() / f"scalp_state_{stock_code}.json"
