import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_CACHE_FILE = BASE_DIR / "token_cache.json"

DOMAIN_REAL = "https://openapi.koreainvestment.com:9443"
DOMAIN_MOCK = "https://openapivts.koreainvestment.com:29443"


def get_mode():
    return os.getenv("MODE", "mock").lower()


def get_base_url():
    return DOMAIN_REAL if get_mode() == "real" else DOMAIN_MOCK


def _get_app_keys():
    mode = get_mode()
    if mode == "real":
        return os.getenv("KIS_APP_KEY"), os.getenv("KIS_APP_SECRET")
    return os.getenv("KIS_MOCK_APP_KEY"), os.getenv("KIS_MOCK_APP_SECRET")


def _load_token_cache():
    if not TOKEN_CACHE_FILE.exists():
        return None
    with open(TOKEN_CACHE_FILE, "r") as f:
        cache = json.load(f)
    mode = get_mode()
    if cache.get("mode") != mode:
        return None
    expires_at = cache.get("expires_at", 0)
    if time.time() >= expires_at - 60:
        return None
    return cache.get("access_token")


def _save_token_cache(access_token, expires_in=86400):
    cache = {
        "access_token": access_token,
        "mode": get_mode(),
        "expires_at": time.time() + expires_in,
    }
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _request_token():
    app_key, app_secret = _get_app_keys()
    if not app_key or not app_secret:
        raise ValueError("APP_KEY 또는 APP_SECRET이 .env에 설정되지 않았습니다.")

    url = f"{get_base_url()}/oauth2/tokenP"
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    resp = requests.post(url, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"토큰 발급 실패: {data}")

    return data["access_token"]


def get_access_token():
    token = _load_token_cache()
    if token:
        return token
    token = _request_token()
    _save_token_cache(token)
    return token


def get_headers(tr_id=""):
    app_key, app_secret = _get_app_keys()
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    if tr_id:
        headers["tr_id"] = tr_id
    return headers
