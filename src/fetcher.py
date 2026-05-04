import time
import threading
import requests
import pandas as pd
from src.auth import get_base_url, get_headers, _get_app_keys

_last_call_time = 0
_rate_lock = threading.Lock()
_MIN_INTERVAL = 0.05  # 초당 20건 제한 → 50ms 간격


def _rate_limit():
    global _last_call_time
    with _rate_lock:
        elapsed = time.time() - _last_call_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_call_time = time.time()


_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRY_BACKOFFS = (0.3, 0.5, 0.8, 1.2, 2.0)  # 5회 재시도, 누적 4.8초


def _api_get(path, params, tr_id):
    _rate_limit()
    url = f"{get_base_url()}{path}"
    headers = get_headers(tr_id)
    last_status = None
    attempts = len(_RETRY_BACKOFFS)
    for attempt in range(attempts):
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code in _RETRY_STATUS:
            last_status = resp.status_code
            if attempt < attempts - 1:
                time.sleep(_RETRY_BACKOFFS[attempt])
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"API 호출 실패 (HTTP {last_status} 반복)")


def get_current_price(stock_code):
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    data = _api_get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        params,
        "FHKST01010100",
    )
    output = data.get("output", {})
    return {
        "price": int(output.get("stck_prpr", 0)),
        "change_rate": float(output.get("prdy_ctrt", 0)),
        "volume": int(output.get("acml_vol", 0)),
        "high": int(output.get("stck_hgpr", 0)),
        "low": int(output.get("stck_lwpr", 0)),
        "open": int(output.get("stck_oprc", 0)),
    }


def get_daily_ohlcv(stock_code, days=60):
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    data = _api_get(
        "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        params,
        "FHKST03010100",
    )
    records = data.get("output2", [])
    if not records:
        return pd.DataFrame()

    rows = []
    for r in records[:days]:
        rows.append({
            "date": r.get("stck_bsop_date", ""),
            "open": int(r.get("stck_oprc", 0)),
            "high": int(r.get("stck_hgpr", 0)),
            "low": int(r.get("stck_lwpr", 0)),
            "close": int(r.get("stck_clpr", 0)),
            "volume": int(r.get("acml_vol", 0)),
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)
    return df
