import requests
from src import config
from src.auth import get_base_url, get_headers, get_mode


def _get_account():
    return config.get_account_no()


def _order_request(tr_id, stock_code, qty, price=0, order_type="01"):
    """주문 공통 요청. order_type: 01=시장가, 00=지정가"""
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
    resp = requests.post(url, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("rt_cd") != "0":
        raise RuntimeError(f"주문 실패: {data.get('msg1', data)}")
    return data


def buy(stock_code, amount, current_price=0):
    """금액 기준 시장가 매수. current_price가 주어지면 수량 계산."""
    if current_price <= 0:
        from src.fetcher import get_current_price
        current_price = get_current_price(stock_code)["price"]
    qty = amount // current_price
    if qty <= 0:
        raise ValueError(f"매수 수량 0: 금액({amount}) < 현재가({current_price})")

    tr_id = "TTTC0802U" if get_mode() == "real" else "VTTC0802U"
    result = _order_request(tr_id, stock_code, qty)
    result["_qty"] = qty
    result["_price"] = current_price
    return result


def sell(stock_code, quantity):
    """수량 기준 시장가 매도."""
    tr_id = "TTTC0801U" if get_mode() == "real" else "VTTC0801U"
    return _order_request(tr_id, stock_code, quantity)


def _inquire_balance_raw():
    """잔고 조회 API 1회 호출 → 원본 응답 반환 (balance + holdings 공용)"""
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
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_account_info():
    """잔고 + 보유종목을 한 번의 API 호출로 조회."""
    data = _inquire_balance_raw()

    output2 = data.get("output2", [{}])
    summary = output2[0] if output2 else {}
    balance = {
        "total_eval": int(summary.get("tot_evlu_amt", 0)),
        "cash": int(summary.get("dnca_tot_amt", 0)),
        "profit_loss": int(summary.get("evlu_pfls_smtl_amt", 0)),
        "profit_rate": float(summary.get("evlu_pfls_rt", 0)),
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
