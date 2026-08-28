"""ChefEar 레시피 표시용 데이터 — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

recipes 테이블 조회(handle_utterance() 응답엔 재료 원문이 없어서 별도로 필요).
"""
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
    # 2026-08-28 — recipe_id별 세션 캐시(_recipe_view_cache). 이번 세션에서 한 번이라도
    # 조회한 레시피면 force=True로 불려도 DB 왕복(recipes by id + recipe_steps by
    # recipe_id, _fetch_recipe_view() 참고) 없이 캐시에서 돌려준다. "같은 메뉴를 반복
    # 조회할 때마다 매번 DB를 들른다"는 실측 리포트 대응(ui/dispatch.py의 요리명 조회
    # 캐시와 한 쌍). 관리자 승인/삭제로 세션 도중 바뀔 수 있어 _VIEW_CACHE_TTL_S(5분)
    # 지난 항목은 버리고 다시 조회한다. 캐시는 reset_to_start()가 안 지운다.
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
