import time
from datetime import datetime

import requests

from src import config
from src.auth import get_base_url, get_headers, get_mode
from src.fetcher import _rate_limit, _RETRY_BACKOFFS


def _get_account():
    return config.get_account_no()


def _order_request(tr_id, stock_code, qty, price=0, order_type="01"):
    """주문 공통 요청. order_type: 01=시장가, 00=지정가"""
    _rate_limit()
    cano, acnt = _get_account()
    url = f"{get_base_url()}/uapi/domestic-stock/v1/trading/order-cash"
    headers = get_headers(tr_id)
    body = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt,
        "PDNO": stock_code,
        "ORD_DVSN": order_type,
        "ORD_QTY": str(qty),
        "ORD_UNPR": str(price) if order_type == "00" else "0",
    }
    attempts = len(_RETRY_BACKOFFS)
    for attempt in range(attempts):
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt < attempts - 1:
                time.sleep(_RETRY_BACKOFFS[attempt])
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"주문 실패: {data.get('msg1', data)}")
        return data
    raise RuntimeError("주문 API 호출 실패: 429 Too Many Requests 반복")


def get_order_execution(odno: str, stock_code: str) -> dict:
    """주문번호로 당일 체결 결과를 조회한다.

    반환:
        {ord_qty, filled_qty, avg_fill_price, tot_ccld_amt}
        해당 주문이 없으면 모두 0으로 반환.
    """
    _rate_limit()
    cano, acnt = _get_account()
    today = datetime.now().strftime("%Y%m%d")
    tr_id = "TTTC0081R" if get_mode() == "real" else "VTTC0081R"
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt,
        "INQR_STRT_DT": today,
        "INQR_END_DT": today,
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": stock_code,
        "CCLD_DVSN": "00",
        "ORD_GNO_BRNO": "",
        "ODNO": odno,
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    url = f"{get_base_url()}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    headers = get_headers(tr_id)
    attempts = len(_RETRY_BACKOFFS)
    for attempt in range(attempts):
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt < attempts - 1:
                time.sleep(_RETRY_BACKOFFS[attempt])
            continue
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("output1", [])
        for row in rows:
            if row.get("odno") != odno:
                continue
            filled_qty = int(row.get("tot_ccld_qty", 0))
            tot_amt = int(float(row.get("tot_ccld_amt", 0)))
            avg_price = int(tot_amt / filled_qty) if filled_qty > 0 else 0
            return {
                "ord_qty": int(row.get("ord_qty", 0)),
                "filled_qty": filled_qty,
                "avg_fill_price": avg_price,
                "tot_ccld_amt": tot_amt,
            }
        return {"ord_qty": 0, "filled_qty": 0, "avg_fill_price": 0, "tot_ccld_amt": 0}
    raise RuntimeError("체결 조회 API 호출 실패: 429 Too Many Requests 반복")


def _try_fetch_fill(odno: str, stock_code: str) -> dict | None:
    """체결 정보를 조회. 체결량이 1주 이상 잡히면 그 시점 결과 반환,
    재시도해도 0이면 None (미체결 또는 mock 미지원).
    """
    if not odno:
        return None
    attempts = config.get_fill_poll_attempts()
    interval = config.get_fill_poll_interval_sec()
    for attempt in range(attempts):
        if attempt > 0:
            time.sleep(interval)
        try:
            info = get_order_execution(odno, stock_code)
        except Exception:
            continue
        if info["filled_qty"] > 0:
            return info
    return None


def buy(stock_code, amount, current_price=0):
    """금액 기준 시장가 매수. 체결 결과를 조회해 실제 체결가/수량을 반환.

    반환 dict:
        ord_qty, filled_qty, avg_fill_price, amount, odno,
        fully_filled (bool), estimated (bool: 체결조회 실패 시 True)
    """
    if current_price <= 0:
        from src.fetcher import get_current_price
        current_price = get_current_price(stock_code)["price"]
    qty = amount // current_price
    if qty <= 0:
        raise ValueError(f"매수 수량 0: 금액({amount}) < 현재가({current_price})")

    tr_id = "TTTC0802U" if get_mode() == "real" else "VTTC0802U"
    response = _order_request(tr_id, stock_code, qty)
    odno = (response.get("output") or {}).get("ODNO", "")

    fill = _try_fetch_fill(odno, stock_code)
    if fill:
        filled_qty = fill["filled_qty"]
        avg_price = fill["avg_fill_price"]
        tot_amt = fill["tot_ccld_amt"] or filled_qty * avg_price
        return {
            "ord_qty": qty,
            "filled_qty": filled_qty,
            "avg_fill_price": avg_price,
            "amount": tot_amt,
            "odno": odno,
            "fully_filled": filled_qty >= qty,
            "estimated": False,
        }

    # 체결 정보를 못 받은 경우의 처리:
    #   real 모드: 체결을 임의로 가정하면 local state ↔ 실제 잔고 불일치(중복매도/잘못된 PnL)
    #              위험. 미체결 상태(filled_qty=0)로 명시적 반환하여 호출 측이 인지하게 한다.
    #   mock 모드: KIS 모의 서버가 체결조회 API를 자주 거부하므로 운영 편의로
    #              주문 시점 가격으로 fallback (estimated=True).
    if get_mode() == "real":
        return {
            "ord_qty": qty,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "amount": 0,
            "odno": odno,
            "fully_filled": False,
            "estimated": False,
            "unknown_fill": True,  # 호출 측이 reconcile 트리거 가능
        }
    return {
        "ord_qty": qty,
        "filled_qty": qty,
        "avg_fill_price": current_price,
        "amount": qty * current_price,
        "odno": odno,
        "fully_filled": True,
        "estimated": True,
    }


def sell(stock_code, quantity, current_price=0):
    """수량 기준 시장가 매도. 체결 결과를 조회해 실제 체결가/수량을 반환."""
    tr_id = "TTTC0801U" if get_mode() == "real" else "VTTC0801U"
    response = _order_request(tr_id, stock_code, quantity)
    odno = (response.get("output") or {}).get("ODNO", "")

    fill = _try_fetch_fill(odno, stock_code)
    if fill:
        filled_qty = fill["filled_qty"]
        avg_price = fill["avg_fill_price"]
        tot_amt = fill["tot_ccld_amt"] or filled_qty * avg_price
        return {
            "ord_qty": quantity,
            "filled_qty": filled_qty,
            "avg_fill_price": avg_price,
            "amount": tot_amt,
            "odno": odno,
            "fully_filled": filled_qty >= quantity,
            "estimated": False,
        }

    # real 모드: 미체결 상태 명시. mock 모드: 주문 시점 가격 fallback.
    if get_mode() == "real":
        return {
            "ord_qty": quantity,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "amount": 0,
            "odno": odno,
            "fully_filled": False,
            "estimated": False,
            "unknown_fill": True,
        }

    if current_price <= 0:
        try:
            from src.fetcher import get_current_price
            current_price = get_current_price(stock_code)["price"]
        except Exception:
            current_price = 0
    return {
        "ord_qty": quantity,
        "filled_qty": quantity,
        "avg_fill_price": current_price,
        "amount": quantity * current_price,
        "odno": odno,
        "fully_filled": True,
        "estimated": True,
    }


def _inquire_balance_raw():
    """잔고 조회 API 1회 호출 → 원본 응답 반환 (balance + holdings 공용)"""
    _rate_limit()
    cano, acnt = _get_account()
    tr_id = "TTTC8434R" if get_mode() == "real" else "VTTC8434R"
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    url = f"{get_base_url()}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = get_headers(tr_id)
    attempts = len(_RETRY_BACKOFFS)
    for attempt in range(attempts):
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt < attempts - 1:
                time.sleep(_RETRY_BACKOFFS[attempt])
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("잔고 조회 API 호출 실패: 429 Too Many Requests 반복")


def get_account_info():
    """잔고 + 보유종목을 한 번의 API 호출로 조회."""
    data = _inquire_balance_raw()

    output2 = data.get("output2", [{}])
    summary = output2[0] if output2 else {}
    # KIS 잔고 필드 매핑 (한국 D+2 정산 고려):
    #   prvs_rcdl_excc_amt = 가수도 정산금액 = 실제 사용 가능 현금 ⭐
    #   dnca_tot_amt       = 예수금 총액 (정산 미반영, 매수해도 그대로 남는 misleading 값)
    #   tot_evlu_amt       = 총평가금액 (cash + 보유주식 평가)
    #   asst_icdc_amt      = 오늘 자산 증감액 (KIS가 직접 계산한 일일 손익)
    #   evlu_pfls_smtl_amt = 미실현 평가손익 (보유 종목)
    balance = {
        "total_eval": int(summary.get("tot_evlu_amt", 0)),
        "cash": int(summary.get("prvs_rcdl_excc_amt", summary.get("dnca_tot_amt", 0))),
        "cash_deposit": int(summary.get("dnca_tot_amt", 0)),  # 정산 전 예수금 (참고용)
        "profit_loss": int(summary.get("evlu_pfls_smtl_amt", 0)),  # 미실현
        "profit_rate": float(summary.get("evlu_pfls_rt", 0)),
        "asset_change": int(summary.get("asst_icdc_amt", 0)),  # 오늘 자산 증감 (D 단위 손익)
    }

    holdings = []
    for item in data.get("output1", []):
        qty = int(item.get("hldg_qty", 0))
        if qty <= 0:
            continue
        holdings.append({
            "stock_code": item.get("pdno", ""),
            "stock_name": item.get("prdt_name", ""),
            "quantity": qty,
            "avg_price": int(float(item.get("pchs_avg_pric", 0))),
            "current_price": int(item.get("prpr", 0)),
            "profit_rate": float(item.get("evlu_pfls_rt", 0)),
            "profit_loss": int(item.get("evlu_pfls_amt", 0)),
        })

    return balance, holdings


def get_balance():
    balance, _ = get_account_info()
    return balance


def get_holdings():
    _, holdings = get_account_info()
    return holdings
