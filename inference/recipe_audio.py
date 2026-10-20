"""사용자가 등록·수정한 레시피의 음성을 만들어 비공개 저장소에 올린다.

합성기(synthesize: 문장 -> mp3 바이트)와 DB·저장소 클라이언트를 밖에서 넣는다(테스트는 가짜).
- 본인 소유 레시피만 처리한다(owner 불일치면 아무것도 하지 않는다).
- 이미 올라간 문장은 건너뛴다(파일 이름이 문장+목소리 버전의 해시이므로 같은 문장이면 같은 파일).
- 고친 레시피에서 더는 쓰지 않는 예전 음성은 지운다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from chefear_api.speech import audio_key, confirm_text, step_speech_text

PRIVATE_BUCKET = "tts-private"


def recipe_texts(dish_name: str, raw_step_texts: list[str]) -> list[str]:
    """서비스가 이 레시피를 읽어 줄 때 요청하는 문장들(service.py와 같은 함수로 만든다)."""
    texts = [confirm_text(dish_name)] + [step_speech_text(t) for t in raw_step_texts]
    seen: set[str] = set()
    out = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_job(client, recipe_id: str, owner_id: str, status: str, error: str | None = None) -> None:
    client.table("tts_jobs").upsert(
        {"recipe_id": recipe_id, "owner_id": owner_id, "status": status, "error": error, "updated_at": _now()}
    ).execute()


def generate_for_recipe(
    client, recipe_id: str, owner_id: str, synthesize: Callable[[str], bytes], bucket: str = PRIVATE_BUCKET
) -> dict:
    rows = client.table("recipes").select("*").eq("id", recipe_id).execute().data or []
    if not rows or rows[0].get("owner_id") != owner_id:
        return {"status": "skipped", "reason": "not_owner_or_missing"}
    dish_name = rows[0]["dish_name"]
    steps = (
        client.table("recipe_steps").select("step_number,step_text").eq("recipe_id", recipe_id)
        .order("step_number").execute().data or []
    )
    texts = recipe_texts(dish_name, [s["step_text"] for s in steps])
    wanted = {f"users/{owner_id}/{audio_key(t)}.mp3": t for t in texts}

    _set_job(client, recipe_id, owner_id, "running")
    try:
        existing = {
            r["path"]
            for r in (client.table("tts_assets").select("path").eq("owner_id", owner_id).eq("recipe_id", recipe_id)
                      .execute().data or [])
        }
        made = 0
        for path, text in wanted.items():
            if path in existing:
                continue
            data = synthesize(text)
            client.storage.from_(bucket).upload(path, data, {"content-type": "audio/mpeg", "upsert": "true"})
            client.table("tts_assets").upsert(
                {"path": path, "scope": "user", "owner_id": owner_id, "recipe_id": recipe_id, "created_at": _now()}
            ).execute()
            made += 1

        stale = sorted(existing - set(wanted))
        if stale:
            client.storage.from_(bucket).remove(stale)
            for path in stale:
                client.table("tts_assets").delete().eq("path", path).execute()

        _set_job(client, recipe_id, owner_id, "done")
        return {"status": "done", "made": made, "reused": len(wanted) - made, "removed": len(stale)}
    except Exception as exc:  # noqa: BLE001 — 실패 사유를 남기고 호출한 쪽에 다시 알린다
        _set_job(client, recipe_id, owner_id, "failed", repr(exc)[:300])
        raise
