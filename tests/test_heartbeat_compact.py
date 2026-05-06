"""heartbeat 컴팩트 모드 (idle) 통합 테스트.

문제: 6종목 모두 "대기"인 idle 상태에서도 heartbeat가 매번 10줄 풀 출력 →
가용/실현/W-L 같은 무변화 정보가 매 사이클 반복되어 가독성 저하.

해결: 모든 monitor가 보유 0이면 컴팩트 2줄로 출력
- 1줄: [scalp 대기 N/N] 005930=267,000 000660=1,605,000 ...
- 2줄: (잔고 있을 때만) Cash 49,867k 실현 -31,945 W/L 5/11(32%)

보유가 1개라도 있으면 기존 다중 줄 포맷 유지 (보유 종목 정보 손실 방지).
"""
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    from src import config, risk
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config, "get_state_path", lambda: state_file)
    risk._reset_for_test()
    scalp_dir = tmp_path / "scalp_states"
    scalp_dir.mkdir()
    monkeypatch.setattr(
        config, "get_scalp_state_path",
        lambda code="": scalp_dir / f"scalp_state_{code or 'default'}.json",
    )
    # 기본은 stock master 비움 + STOCK_NAMES 미설정 — 코드가 그대로 fallback되어
    # 테스트가 실 KRX 캐시 의존성에서 자유로워진다. 개별 테스트가 setenv("STOCK_NAMES",...)로 override 가능.
    monkeypatch.delenv("STOCK_NAMES", raising=False)
    config._load_stock_master.cache_clear()
    monkeypatch.setattr(config, "_load_stock_master", lambda: {})
    yield
    risk._reset_for_test()


def _make_monitor(code, last_price=0, position_qty=0, entry_price=0):
    """ScalpMonitor를 외부 API 호출 없이 만들기 위한 헬퍼."""
    from src.scalper import ScalpMonitor
    with patch("src.scalper.get_holdings", return_value=[]):
        m = ScalpMonitor(code, holdings=[])
    m.last_price = last_price
    if position_qty > 0:
        m.state["position_qty"] = position_qty
        m.state["entry_price"] = entry_price
        m.state["high_price"] = max(entry_price, last_price)
    return m


def test_heartbeat_compact_when_all_idle(isolated_state):
    """모든 monitor가 보유 0이면 컴팩트 한 줄 + 잔고 한 줄 = 2줄로 끝."""
    from src.combined import _format_heartbeat

    monitors = [
        _make_monitor("005930", last_price=267000),
        _make_monitor("000660", last_price=1605000),
        _make_monitor("035720", last_price=46450),
    ]
    balance = {
        "cash": 49867404, "cash_deposit": 50000000,
        "total_eval": 49867404, "profit_loss": 0,
        "asset_change": -70887,
    }

    out = _format_heartbeat(monitors, balance)
    lines = out.split("\n")
    # 컴팩트 모드: 첫 줄 헤더 + (1줄 가격) + 잔고 1줄 + W/L 1줄 = 최대 ~4줄
    # 기존 풀 모드 (idle 시): 헤더 + 종목 N줄 + 빈줄 + 잔고 1줄 + 자산변화 1줄 + W/L 1줄
    # 압축 후 기존 절반 미만이어야 한다.
    assert len(lines) <= 4, f"idle 시 4줄 이내여야 함 (실제 {len(lines)}줄)\n{out}"
    # 모든 종목코드가 한 줄에 들어가야 한다 (컴팩트)
    assert "005930" in out and "000660" in out and "035720" in out
    # 가격도 표시
    assert "267,000" in out
    assert "1,605,000" in out
    # idle 표시
    assert "대기 3" in out or "대기 3/3" in out


def test_heartbeat_full_when_any_holding(isolated_state):
    """보유가 1개라도 있으면 기존 풀 포맷 유지 + 헤더 앞 빈 줄."""
    from src.combined import _format_heartbeat

    monitors = [
        _make_monitor("005930", last_price=267000, position_qty=1, entry_price=265000),
        _make_monitor("000660", last_price=1605000),
        _make_monitor("035720", last_price=46450),
    ]
    balance = {
        "cash": 49867404, "cash_deposit": 50000000,
        "total_eval": 49867404, "profit_loss": 1500,
    }

    out = _format_heartbeat(monitors, balance)
    lines = out.split("\n")
    # 풀 모드: 빈 줄(separator) + 헤더 + 3 종목 줄 + 빈 줄 + 잔고 등 → 7줄 이상
    assert len(lines) >= 7, f"보유 있을 때 풀 포맷이어야 함 (실제 {len(lines)}줄)\n{out}"
    # 헤더 앞 시각적 분리용 빈 줄 (직전 로그와 분리)
    assert lines[0] == "", f"풀 모드 첫 줄은 빈 줄이어야 함: {repr(lines[0])}"
    assert lines[1].startswith("[scalp 상태]"), f"빈 줄 다음에 헤더: {repr(lines[1])}"
    # 보유 표시
    assert "보유" in out
    # 보유 종목 손익 % 표시되어야 한다
    assert "+0.75%" in out  # (267000-265000)/265000*100


def test_heartbeat_compact_no_leading_blank_line(isolated_state):
    """컴팩트 모드는 자주 떠서 빈 줄 prepend 없음 (밀도 유지)."""
    from src.combined import _format_heartbeat

    monitors = [_make_monitor("005930", last_price=267000)]
    out = _format_heartbeat(monitors, balance=None)
    assert out.startswith("[scalp 대기"), f"컴팩트는 빈 줄 없이 헤더 시작: {out!r}"


def test_heartbeat_compact_handles_loading_price(isolated_state):
    """가격이 아직 0(조회중)인 monitor도 컴팩트 모드에서 깨지지 않는다."""
    from src.combined import _format_heartbeat

    monitors = [
        _make_monitor("005930", last_price=0),  # 아직 조회 안 됨
        _make_monitor("000660", last_price=1605000),
    ]

    out = _format_heartbeat(monitors, balance=None)
    # 적어도 헤더 1줄 + 가격 줄 1줄. 잔고는 None이라 생략
    assert "005930" in out
    assert "000660" in out
    assert "1,605,000" in out
    # 0인 종목은 "조회중" 또는 "?" 또는 "-" 등으로 표시 (구체 표현은 구현에 위임)
    assert "조회중" in out or "?" in out or "-" in out


def test_heartbeat_compact_no_balance(isolated_state):
    """잔고 fetch 실패 (None)일 때도 컴팩트 모드에서 깨지지 않는다."""
    from src.combined import _format_heartbeat

    monitors = [_make_monitor("005930", last_price=267000)]
    out = _format_heartbeat(monitors, balance=None)
    # 헤더 + 가격 줄만 (잔고/W-L 줄 없음)
    lines = out.split("\n")
    assert len(lines) <= 2, f"balance=None idle 시 2줄 이내 (실제 {len(lines)}줄)\n{out}"
    assert "005930" in out or "삼성전자" in out


def test_heartbeat_compact_uses_stock_names(isolated_state, monkeypatch):
    """컴팩트 모드는 코드 대신 종목명을 사용한다 (사용자 가독성)."""
    monkeypatch.setenv(
        "STOCK_NAMES",
        "005930:삼성전자,000660:SK하이닉스,035720:카카오",
    )
    from src.combined import _format_heartbeat

    monitors = [
        _make_monitor("005930", last_price=267000),
        _make_monitor("000660", last_price=1605000),
        _make_monitor("035720", last_price=46450),
    ]
    out = _format_heartbeat(monitors, balance=None)

    assert "삼성전자=267,000" in out, f"종목명 노출 누락: {out}"
    assert "SK하이닉스=1,605,000" in out
    assert "카카오=46,450" in out
    # 코드는 컴팩트 라인에 없어도 됨 (이름이 우선)


def test_heartbeat_compact_falls_back_to_code_without_name(isolated_state):
    """이름이 없는 종목코드는 코드로 fallback (isolated_state가 stock master 비움)."""
    from src.combined import _format_heartbeat

    monitors = [_make_monitor("999999", last_price=1000)]
    out = _format_heartbeat(monitors, balance=None)
    assert "999999=1,000" in out
