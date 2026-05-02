import json
import os
import time
import requests

from src import config

# 하위 호환을 위한 wrapper (다른 모듈이 from src.auth import get_mode/get_base_url 사용 중)
get_mode = config.get_mode
get_base_url = config.get_base_url
_get_app_keys = config.get_app_keys


def _ensure_cache_dir(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _restrict_permissions(path):
    """POSIX 환경에서 토큰 파일 권한을 0o600으로 제한. Windows에서는 무시."""
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _load_token_cache():
    cache_path = config.get_token_cache_path()
    if not cache_path.exists():
        return None
    with open(cache_path, "r") as f:
        cache = json.load(f)
    if cache.get("mode") != config.get_mode():
        return None
    expires_at = cache.get("expires_at", 0)
    if time.time() >= expires_at - 60:
        return None
    return cache.get("access_token")


def _save_token_cache(access_token, expires_in=86400):
    cache_path = config.get_token_cache_path()
    _ensure_cache_dir(cache_path)
    cache = {
        "access_token": access_token,
        "mode": config.get_mode(),
        "expires_at": time.time() + expires_in,
    }
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)
    _restrict_permissions(cache_path)


def _request_token():
    app_key, app_secret = config.get_app_keys()
    if not app_key or not app_secret:
        raise ValueError("APP_KEY 또는 APP_SECRET이 .env에 설정되지 않았습니다.")

    url = f"{config.get_base_url()}/oauth2/tokenP"
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
    app_key, app_secret = config.get_app_keys()
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    if tr_id:
        headers["tr_id"] = tr_id
    return headers
