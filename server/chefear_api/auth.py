"""로그인 확인. 웹이 보낸 Supabase access_token을 Supabase에 물어 사용자 id를 얻는다."""
from __future__ import annotations

import threading
import time

import httpx

from chefear_api.config import Settings

_CACHE_TTL_S = 300
_cache: dict[str, tuple[str | None, float]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def user_id_from_headers(settings: Settings, authorization: str | None, dev_user: str | None = None) -> str | None:
    """로그인했으면 사용자 id, 아니면 None(익명). 토큰이 잘못돼도 익명으로 취급한다."""
    if settings.allow_dev_user and dev_user:
        return dev_user
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token or not settings.supabase_url:
        return None

    now = time.monotonic()
    with _lock:
        hit = _cache.get(token)
        if hit and hit[1] > now:
            return hit[0]

    user_id: str | None = None
    try:
        res = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={"apikey": settings.auth_apikey, "Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        if res.status_code == 200:
            user_id = res.json().get("id")
    except (httpx.HTTPError, ValueError):
        user_id = None

    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        # 확인 실패는 짧게만 기억한다(네트워크 오류로 잠깐 익명이 돼도 곧 복구).
        _cache[token] = (user_id, now + (_CACHE_TTL_S if user_id else 20))
    return user_id
