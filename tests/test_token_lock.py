"""auth.py 토큰 갱신 thread lock 통합 테스트.

분석가 권고: 다중 스레드(scalp N개 + swing 메인) 환경에서 캐시 만료 시점에
여러 스레드가 동시에 _request_token을 호출하면 KIS rate limit 또는 토큰
중복 발급으로 이전 토큰이 무효화될 수 있다. Double-check 패턴 lock 필요.
"""
import threading
import time
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_auth(tmp_path, monkeypatch):
    """매 테스트마다 캐시 경로를 격리하고 모듈 lock도 리셋."""
    from src import auth, config
    cache_path = tmp_path / "token_cache.json"
    monkeypatch.setattr(config, "get_token_cache_path", lambda: cache_path)
    monkeypatch.setenv("KIS_APP_KEY", "test_key")
    monkeypatch.setenv("KIS_APP_SECRET", "test_secret")
    # 모듈 lock 자체는 reset 불필요 (lock은 process-wide).
    # 단, 테스트 격리를 위해 cached token이 없어야 한다.
    yield auth


def test_concurrent_get_access_token_calls_request_once(fresh_auth):
    """20개 스레드가 동시에 토큰을 요청해도 _request_token은 1회만 호출된다."""
    auth = fresh_auth
    call_count = {"n": 0}
    lock = threading.Lock()

    def slow_request():
        # 다른 스레드가 동시에 진입할 시간을 주기 위해 약간 지연
        time.sleep(0.05)
        with lock:
            call_count["n"] += 1
        return "test_token_abc"

    results = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()  # 모든 스레드를 동시에 출발시킴
        results.append(auth.get_access_token())

    with patch.object(auth, "_request_token", side_effect=slow_request):
        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

    assert call_count["n"] == 1, f"_request_token이 {call_count['n']}회 호출됨 (1회여야)"
    assert all(r == "test_token_abc" for r in results)
    assert len(results) == 20


def test_get_access_token_returns_cached_when_valid(fresh_auth):
    """이미 유효한 캐시가 있으면 _request_token을 호출하지 않는다."""
    auth = fresh_auth
    call_count = {"n": 0}

    def counting_request():
        call_count["n"] += 1
        return "fresh_token"

    with patch.object(auth, "_request_token", side_effect=counting_request):
        t1 = auth.get_access_token()
        t2 = auth.get_access_token()
        t3 = auth.get_access_token()

    assert t1 == t2 == t3 == "fresh_token"
    assert call_count["n"] == 1, "캐시 히트는 _request_token을 호출하지 않아야 한다"


def test_token_lock_exists_as_module_attribute(fresh_auth):
    """thread lock이 auth 모듈에 존재해야 한다 (이름은 _token_lock)."""
    auth = fresh_auth
    assert hasattr(auth, "_token_lock"), "auth._token_lock이 정의되어야 한다"
    # threading.Lock() / RLock() 둘 다 acquire/release를 가지므로 duck-typing으로 확인
    assert hasattr(auth._token_lock, "acquire")
    assert hasattr(auth._token_lock, "release")
