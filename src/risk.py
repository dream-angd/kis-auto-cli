"""swing/scalp 공통 리스크 회계.

scheduler.py에 매몰돼 있던 daily_loss 관리를 분리해 swing/scalp 양쪽이
일관되게 손익을 누적하고 한도를 검사할 수 있게 한다.

State 구조 (.kis/state.json):
    {
      "date": "2026-05-06",
      "daily_loss": -29807.5,        # 누적 실현손익 (음수=손실)
      "consecutive_losses": 3,        # 연속 손실 횟수 (서킷용)
      "wins": 6,                      # 익절(또는 본전 초과) 거래 수
      "losses": 13,                   # 손절(또는 본전 미만) 거래 수
      "trade_count": 19               # 매도 체결 건수 (= wins + losses + breakeven)
    }

Thread-safe: 모듈 단위 lock으로 동시 record_realized_pnl 보장.
"""
import json
import threading
from datetime import date

from src import config

_lock = threading.Lock()
_cached_state: dict | None = None


def _empty_state() -> dict:
    return {
        "date": date.today().isoformat(),
        "daily_loss": 0.0,
        "consecutive_losses": 0,
        "wins": 0,
        "losses": 0,
        "trade_count": 0,
    }


def _reset_for_test(keep_disk: bool = False) -> None:
    """테스트 격리용. 메모리 캐시 초기화. keep_disk=False면 디스크 state 파일도 삭제."""
    global _cached_state
    with _lock:
        _cached_state = None
        if not keep_disk:
            path = config.get_state_path()
            if path.exists():
                path.unlink()


def _read_disk() -> dict:
    """디스크 state 파일 로드. 손상/날짜 불일치 시 빈 state 반환."""
    path = config.get_state_path()
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()

    today = date.today().isoformat()
    if data.get("date") != today:
        return _empty_state()

    # 기존 호환 (wins/losses/trade_count 누락 가능)
    base = _empty_state()
    base.update({k: data.get(k, base[k]) for k in base})
    return base


def _write_disk(state: dict) -> None:
    config.atomic_write_text(
        config.get_state_path(),
        json.dumps(state, ensure_ascii=False, indent=2),
    )


def load_state() -> dict:
    """현재 risk state. 첫 호출 시 디스크에서 로드, 이후 메모리 캐시."""
    global _cached_state
    with _lock:
        if _cached_state is None:
            _cached_state = _read_disk()
        return dict(_cached_state)  # 외부 변경 방지 위해 복사본


def save_state(state: dict) -> None:
    """state를 디스크 + 메모리 캐시에 동시 저장 (atomic)."""
    global _cached_state
    with _lock:
        _cached_state = dict(state)
        _write_disk(_cached_state)


def record_realized_pnl(strategy: str, pnl: float) -> dict:
    """매도 체결 후 실현손익을 state에 반영.

    Args:
        strategy: "swing" 또는 "scalp" (현재는 합산만, 추후 분리 가능)
        pnl: 수수료·거래세 차감 후 순손익 (음수=손실, 양수=수익)

    Returns:
        갱신된 state dict.
    """
    global _cached_state
    with _lock:
        if _cached_state is None:
            _cached_state = _read_disk()
        s = _cached_state
        s["daily_loss"] = float(s.get("daily_loss", 0)) + float(pnl)
        s["trade_count"] = int(s.get("trade_count", 0)) + 1
        if pnl > 0:
            s["wins"] = int(s.get("wins", 0)) + 1
            s["consecutive_losses"] = 0
        elif pnl < 0:
            s["losses"] = int(s.get("losses", 0)) + 1
            s["consecutive_losses"] = int(s.get("consecutive_losses", 0)) + 1
        # pnl == 0이면 wins/losses 둘 다 유지 (본전, consecutive 리셋만)
        else:
            s["consecutive_losses"] = 0
        _write_disk(s)
        return dict(s)


def is_daily_loss_limit_hit() -> bool:
    """현재 daily_loss가 -MAX_DAILY_LOSS 이하면 True. 한도 초과 = 신규 진입 차단 신호."""
    state = load_state()
    max_loss = config.get_max_daily_loss()
    return state.get("daily_loss", 0) <= -max_loss


def is_consecutive_loss_limit_hit() -> bool:
    """연속 손실 횟수가 MAX_CONSECUTIVE_LOSSES 이상이면 True."""
    state = load_state()
    return state.get("consecutive_losses", 0) >= config.get_max_consecutive_losses()
