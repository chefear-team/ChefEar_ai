"""읽을 문장 -> 미리 만들어 둔 음성 파일 주소. 없으면 None(웹이 실시간 TTS를 부르거나 글자만 보여 준다)."""
from __future__ import annotations

import threading
import time
from typing import Protocol

from chefear_api.config import Settings
from chefear_api.speech import audio_key


class AudioIndex(Protocol):
    def url_for(self, text: str, owner_id: str | None) -> str | None: ...

    def audio_ready_recipe_ids(self, owner_id: str) -> set[str]: ...

    def delete_recipe_assets(self, owner_id: str, recipe_id: str) -> None: ...


class StaticAudioIndex:
    """테스트·로컬용: 주소를 만들 수 있는 키 목록을 직접 준다."""

    def __init__(self, public_keys: set[str] | None = None, private: dict[str, set[str]] | None = None,
                 ready: dict[str, set[str]] | None = None) -> None:
        self.public_keys = public_keys or set()
        self.private = private or {}
        self.ready = ready or {}
        self.deleted: list[tuple[str, str]] = []

    def url_for(self, text: str, owner_id: str | None) -> str | None:
        key = audio_key(text)
        if key in self.public_keys:
            return f"https://static.test/standard/{key}.mp3"
        if owner_id and key in self.private.get(owner_id, set()):
            return f"https://static.test/users/{owner_id}/{key}.mp3?signed=1"
        return None

    def audio_ready_recipe_ids(self, owner_id: str) -> set[str]:
        return set(self.ready.get(owner_id, set()))

    def delete_recipe_assets(self, owner_id: str, recipe_id: str) -> None:
        self.deleted.append((owner_id, recipe_id))


class SupabaseAudioIndex:
    """운영용. tts_assets 테이블에 있는 파일만 주소를 만든다. 공용은 공개 주소, 본인 것은 서명 주소(1시간)."""

    _REFRESH_S = 600
    _SIGN_S = 3600

    def __init__(self, settings: Settings, client) -> None:
        self._s = settings
        self._client = client
        self._public: set[str] = set()
        self._loaded_at = 0.0
        self._lock = threading.Lock()
        self._private_cache: dict[str, tuple[set[str], float]] = {}

    def _load_public(self) -> set[str]:
        with self._lock:
            if time.monotonic() - self._loaded_at < self._REFRESH_S and self._public:
                return self._public
        keys: set[str] = set()
        start = 0
        try:
            while True:
                rows = (
                    self._client.table("tts_assets").select("path").eq("scope", "standard")
                    .range(start, start + 999).execute().data or []
                )
                keys.update(r["path"].rsplit("/", 1)[-1].removesuffix(".mp3") for r in rows)
                if len(rows) < 1000:
                    break
                start += 1000
        except Exception as exc:  # noqa: BLE001 — 목록을 못 읽어도 서비스는 계속(실시간 TTS로 대체)
            print(f"[audio] 공용 음성 목록 조회 실패: {exc!r}", flush=True)
            return self._public
        with self._lock:
            self._public, self._loaded_at = keys, time.monotonic()
        return keys

    def _load_private(self, owner_id: str) -> set[str]:
        now = time.monotonic()
        with self._lock:
            hit = self._private_cache.get(owner_id)
            if hit and hit[1] > now:
                return hit[0]
        keys: set[str] = set()
        try:
            rows = self._client.table("tts_assets").select("path").eq("owner_id", owner_id).execute().data or []
            keys = {r["path"].rsplit("/", 1)[-1].removesuffix(".mp3") for r in rows}
        except Exception as exc:  # noqa: BLE001
            print(f"[audio] 개인 음성 목록 조회 실패: {exc!r}", flush=True)
        with self._lock:
            self._private_cache[owner_id] = (keys, now + 30)
        return keys

    def url_for(self, text: str, owner_id: str | None) -> str | None:
        key = audio_key(text)
        if key in self._load_public():
            return self._s.public_audio_url(key)
        if owner_id and key in self._load_private(owner_id):
            try:
                res = self._client.storage.from_(self._s.tts_private_bucket).create_signed_url(
                    f"users/{owner_id}/{key}.mp3", self._SIGN_S
                )
                return res.get("signedURL") or res.get("signedUrl")
            except Exception as exc:  # noqa: BLE001
                print(f"[audio] 서명 주소 실패: {exc!r}", flush=True)
        return None

    def audio_ready_recipe_ids(self, owner_id: str) -> set[str]:
        try:
            rows = self._client.table("tts_jobs").select("recipe_id").eq("owner_id", owner_id).eq("status", "done").execute().data or []
            return {r["recipe_id"] for r in rows}
        except Exception as exc:  # noqa: BLE001
            print(f"[audio] 음성 상태 조회 실패: {exc!r}", flush=True)
            return set()

    def delete_recipe_assets(self, owner_id: str, recipe_id: str) -> None:
        try:
            rows = self._client.table("tts_assets").select("path").eq("owner_id", owner_id).eq("recipe_id", recipe_id).execute().data or []
            paths = [r["path"] for r in rows]
            if paths:
                self._client.storage.from_(self._s.tts_private_bucket).remove(paths)
            self._client.table("tts_assets").delete().eq("owner_id", owner_id).eq("recipe_id", recipe_id).execute()
            self._client.table("tts_jobs").delete().eq("recipe_id", recipe_id).execute()
        except Exception as exc:  # noqa: BLE001 — 지우기 실패가 삭제 자체를 막으면 안 된다
            print(f"[audio] 음성 파일 삭제 실패(레시피 삭제는 완료): {exc!r}", flush=True)
        with self._lock:
            self._private_cache.pop(owner_id, None)
