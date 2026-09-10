"""ChefEar 레시피 화면 데이터 — recipes/recipe_steps 조회 결과를 세션에 캐시하고 재료 칩으로 변환한다."""
from __future__ import annotations

import time

import streamlit as st

from orchestration.db import get_client
from orchestration.pipeline import get_precomputed_steps

# ui/dispatch.py의 _LOOKUP_CACHE_TTL_S와 같은 이유(관리자 승인/삭제로 user_custom
# 레시피가 세션 도중 바뀔 수 있음) — _recipe_view_cache의 항목도 5분이 지나면 버린다.
_VIEW_CACHE_TTL_S = 300


def _view_cache_fresh(view: dict | None) -> bool:
    return view is not None and (time.monotonic() - view.get("_ts", 0.0)) < _VIEW_CACHE_TTL_S


def _fetch_recipe_view(recipe_id: str, client) -> dict:
    row = client.table("recipes").select("*").eq("id", recipe_id).single().execute().data
    steps_result = get_precomputed_steps(recipe_id, client=client)
    return {
        "recipe_id": recipe_id,
        "dish_name": row["dish_name"],
        "ingredients_raw": row.get("ingredients") or "",
        "steps": steps_result.get("steps", []) if steps_result.get("available") else [],
        "_ts": time.monotonic(),
    }


def refresh_recipe_view(force: bool = False) -> None:
    recipe_id = st.session_state.pipeline_session.get("current_recipe_id")
    if not recipe_id:
        st.session_state.recipe_view = None
        return
    cached = st.session_state.recipe_view
    if not force and cached and cached.get("recipe_id") == recipe_id and _view_cache_fresh(cached):
        return
    view_cache = st.session_state.setdefault("_recipe_view_cache", {})
    view = view_cache.get(recipe_id)
    if not _view_cache_fresh(view):
        view = _fetch_recipe_view(recipe_id, get_client())
        view_cache[recipe_id] = view
    st.session_state.recipe_view = view


def _ingredients_to_chips(raw: str) -> list[dict]:
    """"[재료] 두부| 감자| 애호박" 같은 원문 텍스트를 render_chips()가 기대하는
    {"name","qty","emoji"} 목록으로 바꾼다. 실제 DB엔 분량 필드가 따로 없어서(qty는
    재료 문자열 안에 섞여 있음, 예: "애호박 3분의 2개") 통째로 name에 넣고 qty는 비운다
    — 화면 디자인을 새로 짜지 않는 선에서의 최소 변환."""
    import re

    if not raw:
        return []
    text = re.sub(r"\[[^\]]*\]", "", raw)
    items = [seg.strip() for seg in text.split("|") if seg.strip()]
    return [{"name": item, "qty": "", "emoji": "🟠"} for item in items]
