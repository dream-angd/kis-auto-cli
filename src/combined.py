import csv
import json
import threading
import time
import unicodedata
from datetime import datetime

from src import config, risk
from src.logger import log_error, log_info
from src.scalper import ScalpMonitor
from src.scheduler import is_market_open, load_state, run_swing_cycle
from src.signals import install_shutdown_handlers, restore_handlers
from src.trader import get_holdings


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

    # 부팅 시 N개 monitor가 각자 get_holdings()를 호출하면 KIS API에 N번
    # 직렬 요청 → 부팅 3~6초 지연. 1회만 받아 공유한다.
    log_info(f"[부팅] {len(seen)}종목 초기화 중 (잔고 1회 조회 후 공유)...")
    try:
        prefetched = get_holdings()
    except Exception as e:
        log_error(f"부팅 잔고조회 실패 (각 monitor가 개별 fetch로 진행): {e}")
        prefetched = None

    return [ScalpMonitor(code, holdings=prefetched) for code in seen]


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


def print_daily_summary() -> None:
    """장 마감 / 종료 시 오늘의 거래 요약을 콘솔에 출력.

    - 매수/매도 횟수, 승/패, 총 실현손익 (수수료/세금 포함)
    - 시작 잔고 vs 현재 잔고 비교
    - 미청산 보유 종목
    """
    today = datetime.now().strftime("%Y%m%d")
    csv_path = config.get_logs_dir() / f"trades_{today}.csv"

    log_info("")
    log_info("==================== 오늘 거래 요약 ====================")

    # 거래 집계
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f))
            buy_count = 0
            sell_count = 0
            wins = 0
            losses = 0
            total_pnl = 0.0
            buy_amount_total = 0
            sell_amount_total = 0
            for r in rows:
                action = r.get("action", "") or ""
                amount = int(r.get("amount") or 0)
                pnl_str = r.get("pnl", "") or ""
                if "BUY" in action:
                    buy_count += 1
                    buy_amount_total += amount
                elif "SELL" in action:
                    sell_count += 1
                    sell_amount_total += amount
                    if pnl_str.strip():
                        try:
                            pnl = float(pnl_str)
                            total_pnl += pnl
                            if pnl > 0:
                                wins += 1
                            elif pnl < 0:
                                losses += 1
                        except ValueError:
                            pass

            log_info(f"  거래: 총 {buy_count + sell_count}건  (매수 {buy_count} / 매도 {sell_count})")
            if sell_count > 0:
                breakeven = sell_count - wins - losses
                win_rate = wins / sell_count * 100
                log_info(
                    f"  성적: {wins}승 {losses}패"
                    + (f" {breakeven}본전" if breakeven > 0 else "")
                    + f"  (승률 {win_rate:.1f}%)"
                )
            log_info(f"  매수 총 거래대금: {buy_amount_total:,}원")
            log_info(f"  매도 총 거래대금: {sell_amount_total:,}원")
            log_info(f"  실현 손익: {total_pnl:+,.0f}원  (수수료·거래세 차감 후)")
        except Exception as e:
            log_error(f"  거래 집계 실패: {e}")
    else:
        log_info("  오늘 거래 없음")

    log_info("")

    # 잔고 비교 (시작 스냅샷 vs 현재)
    try:
        from src.trader import get_account_info
        balance, holdings = get_account_info()
        log_info(
            f"  현재 평가액: {balance['total_eval']:,}원  "
            f"(Cash {balance['cash']:,}원)"
        )
        snap_path = config.get_logs_dir() / f"start_snapshot_{today}.json"
        if snap_path.exists():
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
                start_eval = int(snap.get("balance", {}).get("total_eval", 0))
                if start_eval > 0:
                    diff = balance["total_eval"] - start_eval
                    pct = diff / start_eval * 100
                    log_info(f"  시작 대비: {diff:+,}원  ({pct:+.2f}%)")
            except Exception:
                pass
        if holdings:
            log_info(f"  미청산 보유: {len(holdings)}종목")
            for h in holdings:
                name = config.get_stock_name(h["stock_code"])
                log_info(
                    f"    - {name}({h['stock_code']}) "
                    f"{h['quantity']}주  pnl {h['profit_rate']:+.2f}% "
                    f"({h['profit_loss']:+,}원)"
                )
        else:
            log_info("  미청산 보유: 없음 ✓")
    except Exception as e:
        log_error(f"  잔고 조회 실패: {e}")

    log_info("==========================================================")
    log_info("")


def _disp_width(s: str) -> int:
    """동아시아 wide 문자(한글 등)는 2칸, 그 외는 1칸으로 계산."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad_right(s: str, width: int) -> str:
    """display 폭 기준 우측 패딩 (한글 정렬용)."""
    return s + " " * max(0, width - _disp_width(s))


def _is_post_close_done(monitors) -> bool:
    """장 마감 강제 청산 시점 + 모든 scalp 보유 0이면 True (조기 종료 신호)."""
    force_close_min = config.get_scalp_force_close_before_close_min()
    if force_close_min <= 0:
        return False
    close_in = ScalpMonitor._market_close_in_min()
    if not (0 < close_in <= force_close_min):
        return False
    return all(not m._has_position() for m in monitors)


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
    # 비용 포함 본전선 표시 (추적/타임아웃 판단 기준)
    from src.scalper import ScalpMonitor
    be_pct = ScalpMonitor._break_even_pct()
    lines.append(
        f"  비용 break-even ≈ {be_pct:.2f}%  "
        f"(매수·매도 수수료 + 거래세 + 슬리피지 {config.get_scalp_slippage_buffer_pct()*100:.2f}%)"
    )
    ratio_min = config.get_scalp_bid_ask_ratio_min()
    if ratio_min > 0:
        lines.append(f"  호가 검증 bid/ask >= {ratio_min:.1f}")
    else:
        lines.append("  호가 검증 비활성")
    no_buy = config.get_scalp_no_new_buy_before_close_min()
    force_close = config.get_scalp_force_close_before_close_min()
    if no_buy > 0 or force_close > 0:
        lines.append(
            f"  장 마감 처리: 마감 {no_buy}분 전 신규매수 차단 / "
            f"마감 {force_close}분 전 보유 강제 청산"
        )
    return "\n".join(lines)


def _format_heartbeat_compact(monitors, balance, swing_holdings) -> str:
    """모든 monitor가 보유 0(idle)일 때 사용하는 컴팩트 포맷.

    1줄: [scalp 대기 N/N] 005930=267,000 000660=1,605,000 ...
    2줄: (잔고 있을 때) Cash {cash} 실현 {realized} W/L {w}/{l}({pct}%)
    3줄+: swing 보유가 있으면 그것만 추가 (대기 종목 N줄은 압축됨)
    """
    n = len(monitors)
    parts = []
    for m in monitors:
        # 코드 대신 종목명 (없으면 코드로 fallback) — 사용자 가독성
        name = config.get_stock_name(m.stock_code)
        if m.last_price > 0:
            parts.append(f"{name}={m.last_price:,}")
        else:
            parts.append(f"{name}=조회중")
    lines = [f"[scalp 대기 {n}/{n}] " + " ".join(parts)]

    if balance:
        cash = balance.get("cash", 0)
        try:
            rs = risk.load_state()
            realized = rs.get("daily_loss", 0.0)
            wins = rs.get("wins", 0)
            losses = rs.get("losses", 0)
            trade_count = rs.get("trade_count", 0)
            max_loss = config.get_max_daily_loss()
            used_pct = (abs(realized) / max_loss * 100) if max_loss > 0 and realized < 0 else 0.0
            limit_tag = " ⚠ 한도 초과" if risk.is_daily_loss_limit_hit() else ""
            lines.append(
                f"  Cash {cash:,} 실현 {realized:+,.0f} "
                f"W/L {wins}/{losses} (총 {trade_count}건, 한도 {used_pct:.0f}%){limit_tag}"
            )
        except Exception:
            lines.append(f"  Cash {cash:,}")

    if swing_holdings:
        for h in swing_holdings:
            name = config.format_stock(h["stock_code"])
            lines.append(
                f"  Swing 보유: {name} {h['quantity']}주 "
                f"{h['profit_rate']:+.2f}% ({h['profit_loss']:+,}원)"
            )

    return "\n".join(lines)


def _format_heartbeat(monitors, balance=None, swing_holdings=None) -> str:
    """scalp 종목별 가격/상태/손익 + (옵션) 잔고/swing 보유 한 줄 추가.

    보유 0(idle) 시 컴팩트 모드로 분기 (`_format_heartbeat_compact`).
    보유가 1개라도 있으면 풀 포맷:
      [scalp 상태] (보유 N / 대기 M)
        삼성전자(005930)        227,500   대기
        현대차(005380)          540,000   보유 +0.32%

        Cash 50,000,000원  Eval 49,940,000원  PnL -60,000원 (-0.12%)
        Swing 보유: SK하이닉스(000660) 1주 +0.50%
    """
    if not monitors:
        return "[scalp 상태] (모니터 없음)"

    held = sum(1 for m in monitors if m._has_position())
    if held == 0:
        return _format_heartbeat_compact(monitors, balance, swing_holdings)

    waiting = len(monitors) - held
    # 풀 모드(보유 ≥ 1)는 N줄로 떠서 직전 로그와 시각적 분리가 필요 — 빈 줄 prepend
    lines = ["", f"[scalp 상태] (보유 {held} / 대기 {waiting})"]

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
        # 미실현 PnL (보유 종목 평가손익) — 보유 0이면 항상 0
        unrealized = balance.get("profit_loss", 0)
        total_eval = balance.get("total_eval", 0)
        principal = total_eval - unrealized
        unr_pct = (unrealized / principal * 100) if principal > 0 else 0.0
        cash = balance.get("cash", 0)
        cash_deposit = balance.get("cash_deposit", cash)
        # 가용 cash와 예수금이 다르면 둘 다 표시 (D+2 정산 미반영 차이)
        if cash != cash_deposit:
            cash_str = f"가용 {cash:,}원 (예수금 {cash_deposit:,}원)"
        else:
            cash_str = f"Cash {cash:,}원"
        lines.append(
            f"  {cash_str}  Eval {total_eval:,}원  "
            f"미실현 {unrealized:+,}원 ({unr_pct:+.4f}%)"
        )

        # 오늘 손익: KIS 자산증감(asst_icdc_amt)과 우리 risk.daily_loss 둘 다 표시
        try:
            rs = risk.load_state()
            realized = rs.get("daily_loss", 0.0)
            wins = rs.get("wins", 0)
            losses = rs.get("losses", 0)
            trade_count = rs.get("trade_count", 0)
            max_loss = config.get_max_daily_loss()
            used_pct = (abs(realized) / max_loss * 100) if max_loss > 0 and realized < 0 else 0.0
            limit_tag = "  ⚠ 한도 초과" if risk.is_daily_loss_limit_hit() else ""
            asset_change = balance.get("asset_change", 0)
            lines.append(
                f"  오늘 자산변화 {asset_change:+,}원 (KIS)  "
                f"실현 {realized:+,.0f}원 (자체)"
            )
            lines.append(
                f"  Daily Loss 사용 {used_pct:.0f}%  "
                f"W/L {wins}/{losses} (총 {trade_count}건){limit_tag}"
            )
        except Exception:
            pass  # risk state 로드 실패 시 그 줄 생략
    if swing_holdings:
        for h in swing_holdings:
            name = config.format_stock(h["stock_code"])
            lines.append(
                f"  Swing 보유: {name} {h['quantity']}주 "
                f"{h['profit_rate']:+.2f}% ({h['profit_loss']:+,}원)"
            )
    return "\n".join(lines)


def _reconcile_all_monitors(monitors) -> None:
    """get_holdings를 1회만 호출하고 모든 monitor의 state를 재동기화.

    주기적으로 run_loop에서 호출. HTS 직접 매도/매수, KIS 내부 desync 등을
    unknown_fill 발생 전에 발견·정정해 다음 사이클이 깨끗한 state로 진입하게 한다.
    잔고 조회 실패 시 모두 skip (로그만 남김).
    """
    if not monitors:
        return
    try:
        holdings = get_holdings()
    except Exception as e:
        log_error(f"Periodic reconcile skipped (잔고조회 실패): {e}")
        return

    by_code = {h["stock_code"]: h for h in holdings}
    for m in monitors:
        held = by_code.get(m.stock_code)
        actual_qty = int(held["quantity"]) if held else 0
        local_qty = int(m.state.get("position_qty", 0))
        if actual_qty == local_qty:
            continue

        if actual_qty == 0 and local_qty > 0:
            log_info(
                f"SCALP {m.display} reconcile desync: local={local_qty}주, "
                f"actual=0 → 포지션 초기화"
            )
            m.state = m._empty_state()
        elif actual_qty < local_qty:
            log_info(
                f"SCALP {m.display} reconcile desync: local={local_qty}주, "
                f"actual={actual_qty}주 → position_qty 동기화"
            )
            m.state["position_qty"] = actual_qty
        else:
            # actual_qty > local_qty: 외부 매수 감지
            avg = int(held.get("avg_price", 0)) if held else 0
            log_info(
                f"SCALP {m.display} reconcile desync: local={local_qty}주, "
                f"actual={actual_qty}주 → 외부 매수 감지, 평균가로 entry 추정"
            )
            m.state["position_qty"] = actual_qty
            if avg > 0 and m.state.get("entry_price", 0) <= 0:
                m.state["entry_price"] = avg
                m.state["high_price"] = max(avg, int(m.state.get("high_price", 0)))
                m.state["entry_time"] = m.state.get("entry_time") or time.time()

        try:
            m._save_state()
        except Exception as e:
            log_error(f"SCALP {m.display} reconcile save 실패: {e}")


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


def run_all_loop(swing_interval_sec=None, scalp_stock=None, scalp_interval_sec=None):
    if swing_interval_sec is None:
        swing_interval_sec = config.get_swing_interval_sec()
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Combined strategy stopping...")
        running = False

    prev_handlers = install_shutdown_handlers(signal_handler)

    swing_state = load_state()
    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()
    excluded_from_swing = {m.stock_code for m in monitors}

    swing_codes = [c for c in config.get_swing_stocks() if c not in excluded_from_swing]

    log_info(f"=== 자동매매 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(_format_swing_block(swing_codes, swing_interval_sec) + "\n")
    log_info(_format_scalp_block(monitors, scalp_interval_sec))

    stop_event = threading.Event()
    scalp_threads = []
    next_swing_at = 0
    next_heartbeat_at = 0
    next_reconcile_at = 0
    reconcile_interval = config.get_reconcile_interval_sec()
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
                if reconcile_interval > 0:
                    next_reconcile_at = time.time() + reconcile_interval

            now = time.time()
            if now >= next_swing_at:
                if not run_swing_cycle(swing_state, excluded_codes=excluded_from_swing):
                    break
                next_swing_at = now + swing_interval_sec

            # 마감 강제 청산 + 모든 보유 0 → 조기 종료
            if _is_post_close_done(monitors):
                log_info("마감 임박 + 모든 보유 청산 완료 — 자동매매 조기 종료")
                break

            if reconcile_interval > 0 and now >= next_reconcile_at:
                _reconcile_all_monitors(monitors)
                next_reconcile_at = now + reconcile_interval

            if now >= next_heartbeat_at:
                scalp_codes = {m.stock_code for m in monitors}
                bal, swing_held = _fetch_balance_and_swing_holdings(scalp_codes)
                log_info(_format_heartbeat(monitors, bal, swing_held))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        restore_handlers(prev_handlers)
        print_daily_summary()

    log_info("=== Combined strategy stopped ===")


def run_scalp_loop(scalp_stock=None, scalp_interval_sec=None):
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log_info("Shutdown signal received. Scalp strategy stopping...")
        running = False

    prev_handlers = install_shutdown_handlers(signal_handler)

    monitors = _build_monitors(scalp_stock)
    scalp_interval_sec = scalp_interval_sec or config.get_scalp_interval_sec()

    log_info(f"=== Scalp 시작 (MODE: {config.get_mode().upper()}) ===")
    log_info(_format_scalp_block(monitors, scalp_interval_sec))

    stop_event = threading.Event()
    scalp_threads = []
    next_heartbeat_at = 0
    next_reconcile_at = 0
    reconcile_interval = config.get_reconcile_interval_sec()
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
                if reconcile_interval > 0:
                    next_reconcile_at = time.time() + reconcile_interval

            # 마감 강제 청산 + 모든 보유 0 → 조기 종료
            if _is_post_close_done(monitors):
                log_info("마감 임박 + 모든 보유 청산 완료 — 자동매매 조기 종료")
                break

            now = time.time()
            if reconcile_interval > 0 and now >= next_reconcile_at:
                _reconcile_all_monitors(monitors)
                next_reconcile_at = now + reconcile_interval

            if now >= next_heartbeat_at:
                scalp_codes = {m.stock_code for m in monitors}
                bal, swing_held = _fetch_balance_and_swing_holdings(scalp_codes)
                log_info(_format_heartbeat(monitors, bal, swing_held))
                next_heartbeat_at = now + config.get_heartbeat_interval_sec()

            time.sleep(1)
    finally:
        if market_threads_active:
            _stop_scalp_threads(scalp_threads, stop_event)
        restore_handlers(prev_handlers)
        print_daily_summary()

    log_info("=== Scalp strategy stopped ===")
