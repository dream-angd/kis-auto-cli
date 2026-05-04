import signal
import threading
import time
import unicodedata
from datetime import datetime

from src import config
from src.logger import log_info
from src.scalper import ScalpMonitor
from src.scheduler import is_market_open, load_state, run_swing_cycle


def _market_closed_for_today():
    now = datetime.now()
    return now.hour > 15 or (now.hour == 15 and now.minute >= 30)


def _log_waiting_for_market():
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 10):
        log_info("Waiting for market open...")
    elif _market_closed_for_today():
        log_info("Market closed. Strategy finished for today.")
    else:
        log_info("Waiting outside market hours...")


def _build_monitors(scalp_codes):
    """입력 종목 리스트로 ScalpMonitor 인스턴스를 만든다.

    종목 수가 MAX_SCALP_STOCKS를 초과하면 ValueError.
    종목명 입력 시 자동으로 코드로 변환된다 (config.resolve_stock_code).
    """
    if isinstance(scalp_codes, str):
        scalp_codes = [c.strip() for c in scalp_codes.split(",") if c.strip()]
    if scalp_codes:
        # CLI 인자 등으로 들어온 값도 이름→코드 resolve
        scalp_codes = [config.resolve_stock_code(c) for c in scalp_codes if c]
    else:
        scalp_codes = config.get_scalp_stocks()
    if not scalp_codes:
        raise ValueError("스캘프 대상 종목이 없습니다. SCALP_STOCKS / SCALP_STOCK / TARGET_STOCKS 중 하나 설정 필요.")

    seen = []
    for code in scalp_codes:
        if code not in seen:
            seen.append(code)

    limit = config.get_max_scalp_stocks()
    if len(seen) > limit:
        raise ValueError(
            f"스캘프 종목 수가 한도 초과: {len(seen)}개 (한도: {limit}개). "
            f".env의 MAX_SCALP_STOCKS 또는 SCALP_STOCKS를 조정하세요."
        )

    return [ScalpMonitor(code) for code in seen]


def _start_scalp_threads(monitors, interval_sec, stop_event):
    """각 monitor를 자기 thread에서 무한 run_loop 실행."""
    threads = []
    for m in monitors:
        t = threading.Thread(
            target=m.run_loop,
            args=(interval_sec, stop_event),
            name=f"scalp-{m.stock_code}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    return threads


def _stop_scalp_threads(threads, stop_event, timeout=5):
    stop_event.set()
    for t in threads:
        t.join(timeout=timeout)


def _disp_width(s: str) -> int:
    """동아시아 wide 문자(한글 등)는 2칸, 그 외는 1칸으로 계산."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad_right(s: str, width: int) -> str:
    """display 폭 기준 우측 패딩 (한글 정렬용)."""
    return s + " " * max(0, width - _disp_width(s))


def _format_swing_block(swing_codes: list, interval_sec: int) -> str:
    """시작 로그 swing 블럭."""
    lines = [f"[Swing] {interval_sec // 60}분 간격 일봉 분석 ({len(swing_codes)}종목)"]
    for c in swing_codes:
        lines.append(f"  - {config.format_stock(c)}")
    lines.append(
        f"  손절 {config.get_swing_stop_loss_pct():.1f}% / "
        f"익절 +{config.get_swing_take_profit_pct():.1f}% / "
        f"한도 {config.get_swing_max_buy_amount():,}원"
    )
    return "\n".join(lines)


def _format_scalp_block(monitors, interval_sec: float) -> str:
    """시작 로그 scalp 블럭."""
    lines = [f"[Scalp] {interval_sec}초 간격 모멘텀 ({len(monitors)}종목, 독립 thread)"]
    for m in monitors:
        lines.append(f"  - {m.display}")
    lines.append(
        f"  손절 {config.get_scalp_stop_loss_pct():.1f}% / "
        f"익절 +{config.get_scalp_take_profit_pct():.1f}% / "
        f"추적 -{config.get_scalp_trailing_drop_pct():.1f}% / "
        f"한도 {config.get_scalp_max_buy_amount():,}원"
    )
    ratio_min = config.get_scalp_bid_ask_ratio_min()
    if ratio_min > 0:
        lines.append(f"  호가 검증 bid/ask >= {ratio_min:.1f}")
    else:
        lines.append("  호가 검증 비활성")
    return "\n".join(lines)


def _format_heartbeat(monitors, balance=None, swing_holdings=None) -> str:
    """scalp 종목별 가격/상태/손익 + (옵션) 잔고/swing 보유 한 줄 추가.

    포맷:
      [scalp 상태] (보유 N / 대기 M)
        삼성전자(005930)        227,500   대기
        현대차(005380)          540,000   보유 +0.32%

        Cash 50,000,000원  Eval 49,940,000원  PnL -60,000원 (-0.12%)
        Swing 보유: SK하이닉스(000660) 1주 +0.50%
    """
    if not monitors:
        return "[scalp 상태] (모니터 없음)"

    held = sum(1 for m in monitors if m._has_position())
    waiting = len(monitors) - held
    lines = [f"[scalp 상태] (보유 {held} / 대기 {waiting})"]

    name_w = max(_disp_width(m.display) for m in monitors)
    for m in monitors:
        disp = _pad_right(m.display, name_w)
        if m.last_price <= 0:
            lines.append(f"  {disp}    조회중")
            continue

        price_str = f"{m.last_price:>10,}"
        if m._has_position():
            entry = int(m.state.get("entry_price", 0))
            if entry > 0:
                pnl_pct = ((m.last_price - entry) / entry) * 100
                lines.append(f"  {disp}  {price_str}   보유 {pnl_pct:+.2f}%")
            else:
                lines.append(f"  {disp}  {price_str}   보유")
        else:
            lines.append(f"  {disp}  {price_str}   대기")

    # 잔고 + swing 보유 추가
    if balance:
        lines.append("")
        lines.append(
            f"  Cash {balance.get('cash', 0):,}원  "
            f"Eval {balance.get('total_eval', 0):,}원  "
            f"PnL {balance.get('profit_loss', 0):+,}원 "
            f"({balance.get('profit_rate', 0):+.2f}%)"
        )
    if swing_holdings:
        for h in swing_holdings:
            name = config.format_stock(h["stock_code"])
            lines.append(
                f"  Swing 보유: {name} {h['quantity']}주 "
                f"{h['profit_rate']:+.2f}% ({h['profit_loss']:+,}원)"
            )
    return "\n".join(lines)


def _fetch_balance_and_swing_holdings(scalp_codes: set):
    """heartbeat용 잔고 + swing 보유 조회. 실패 시 (None, None) 반환."""
    try:
        from src.trader import get_account_info
        balance, holdings = get_account_info()
        # scalp가 추적하는 종목은 heartbeat 본문에 이미 표시되니 swing 보유에서 제외
        swing_holdings = [
            h for h in holdings
            if h["stock_code"] not in scalp_codes and h["quantity"] > 0
        ]
        return balance, swing_holdings
    except Exception:
        return None, None


def run_all_loop(swing_interval_sec=300, scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Combined strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    swing_state = load_state()
    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()
    excluded_from_swing = {m.stock_code for m in monitors}

    swing_codes = [c for c in config.get_swing_stocks() if c not in excluded_from_swing]

    log_info(f"=== 자동매매 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(_format_swing_block(swing_codes, swing_interval_sec))
    log_info(_format_scalp_block(monitors, scalp_interval_sec))

    stop_event = threading.Event()
    scalp_threads = []
    next_swing_at = 0
    next_heartbeat_at = 0
    market_threads_active = False

    try:
        while running:
            if not is_market_open():
                if market_threads_active:
                    _stop_scalp_threads(scalp_threads, stop_event)
                    scalp_threads = []
                    market_threads_active = False
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            if not market_threads_active:
                stop_event = threading.Event()
                scalp_threads = _start_scalp_threads(monitors, scalp_interval_sec, stop_event)
                market_threads_active = True
                next_heartbeat_at = time.time() + config.get_heartbeat_interval_sec()

            now = time.time()
            if now >= next_swing_at:
                if not run_swing_cycle(swing_state, excluded_codes=excluded_from_swing):
                    break
                next_swing_at = now + swing_interval_sec

            if now >= next_heartbeat_at:
                scalp_codes = {m.stock_code for m in monitors}
                bal, swing_held = _fetch_balance_and_swing_holdings(scalp_codes)
                log_info(_format_heartbeat(monitors, bal, swing_held))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Combined strategy stopped ===")


def run_scalp_loop(scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Scalp strategy stopping...")
        running = False

    prev_handler = signal.signal(signal.SIGINT, signal_handler)

    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()

    log_info(f"=== Scalp 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(_format_scalp_block(monitors, scalp_interval_sec))

    stop_event = threading.Event()
    scalp_threads = []
    next_heartbeat_at = 0
    market_threads_active = False

    try:
        while running:
            if not is_market_open():
                if market_threads_active:
                    _stop_scalp_threads(scalp_threads, stop_event)
                    scalp_threads = []
                    market_threads_active = False
                _log_waiting_for_market()
                if _market_closed_for_today():
                    break
                time.sleep(60)
                continue

            if not market_threads_active:
                stop_event = threading.Event()
                scalp_threads = _start_scalp_threads(monitors, scalp_interval_sec, stop_event)
                market_threads_active = True
                next_heartbeat_at = time.time() + config.get_heartbeat_interval_sec()

            now = time.time()
            if now >= next_heartbeat_at:
                scalp_codes = {m.stock_code for m in monitors}
                bal, swing_held = _fetch_balance_and_swing_holdings(scalp_codes)
                log_info(_format_heartbeat(monitors, bal, swing_held))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        signal.signal(signal.SIGINT, prev_handler)

    log_info("=== Scalp strategy stopped ===")
