"""세션 저장소. 서버는 상태를 들고 있지 않고, 대화 상태 전체를 여기에 맡긴다(서버를 여러 대 띄울 수 있게)."""
from __future__ import annotations

import copy
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

SESSION_TTL_S = 24 * 3600


def default_pipeline() -> dict:
    return {"current_recipe_id": None, "step_number": 1, "registration": None}


def new_session_data(owner_id: str | None) -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "screen": "start",
        "pipeline": default_pipeline(),
        "pending_dish_name": None,
        "chat": [],
        "recipe": None,
        "saved": None,
        "speech": None,
        "notice": None,
    }


class SessionStore(Protocol):
    def get(self, session_id: str) -> dict | None: ...

    def put(self, data: dict) -> None: ...


class MemorySessionStore:
    """개발·테스트용. 프로세스가 바뀌면 사라진다."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            item = self._items.get(session_id)
            if item is None:
                return None
            data, expires = item
            if expires < time.monotonic():
                del self._items[session_id]
                return None
            return copy.deepcopy(data)

    def put(self, data: dict) -> None:
        with self._lock:
            if len(self._items) > 5000:
                now = time.monotonic()
                for k in [k for k, (_, e) in self._items.items() if e < now]:
                    del self._items[k]
            self._items[data["session_id"]] = (copy.deepcopy(data), time.monotonic() + SESSION_TTL_S)


class SupabaseSessionStore:
    """운영용. `sessions` 테이블(db/migrate_renewal.sql)에 jsonb로 저장한다."""

    def __init__(self, client) -> None:
        self._client = client

    def get(self, session_id: str) -> dict | None:
        rows = self._client.table("sessions").select("data").eq("id", session_id).execute().data or []
        return rows[0]["data"] if rows else None

    def put(self, data: dict) -> None:
        self._client.table("sessions").upsert(
            {
                "id": data["session_id"],
                "data": data,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
