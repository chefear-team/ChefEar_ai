"""마이레시피(내가 등록한 레시피 목록/수정/삭제) 화면 — docs/specs/my_recipes.md."""
from __future__ import annotations

import re

import streamlit as st

from theme import ICON_BASKET_SM, ICON_INBOX, render_back_link, render_badge, render_spacer, truncate_display_name
from orchestration.db import get_client
from orchestration.registration import delete_recipe, update_recipe
from ui.dispatch import reset_to_start
from ui.session import goto, logout as session_logout


def _my_recipes(user_id: str, client) -> list[dict]:
    """AC-01 — 본인 소유의 user_custom 레시피만, 등록일 최신순으로."""
    rows = (
        client.table("recipes")
        .select("id,dish_name,approved,created_at")
        .eq("source", "user_custom")
        .eq("owner_id", user_id)
        .execute()
        .data
        or []
    )
    return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)


_STEP_PREFIX_RE = re.compile(r"^\d+\.\s*")


def _strip_step_prefix(step_text: str) -> str:
    """수정 폼 프리필용 — registration.py::save_recipe/update_recipe가 저장 시
    붙이는 "N. " 순번 접두어를 뗀다. 안 떼고 그대로 프리필하면 사용자가
    안 건드리고 그대로 저장해도 update_recipe가 또 새 순번을 앞에 붙여
    "1. 1. 재료를 볶는다"처럼 매번 겹쳐 쌓인다. 접두어가 없는(이 변경 이전에 저장된)
    레거시 행은 패턴이 안 맞아 그대로 반환된다.
    """
    return _STEP_PREFIX_RE.sub("", step_text, count=1)


def _approval_label(row: dict) -> str:
    """AC-06 — 승인 상태 배지 문구."""
    return "승인됨" if row.get("approved") == "Y" else "심사중"


def _authorized_recipe(recipe_id: str, user_id: str, client) -> dict | None:
    """AC-05 — recipe_id를 조회하되, 존재하지 않거나 소유자가 다르면 None.

    정상 UI 경로로는 screen_my_recipes()가 이미 본인 소유 레시피만 목록에 올리므로
    남의 recipe_id가 여기 들어올 일이 없지만, editing_recipe_id는 세션 상태값이라
    실제로 고치기 전에 소유권을 한 번 더 확인한다(EC-04, 방어적 처리).

    .single()을 쓰지 않는다 — 실DB(PostgREST)는 0행에서 PGRST116 예외를 올려
    `if not recipe` 방어에 닿기 전에 500이 되므로, 일반 조회 후 비어있으면 None이다.
    """
    rows = client.table("recipes").select("*").eq("id", recipe_id).execute().data or []
    if not rows:
        return None
    recipe = rows[0]
    if recipe.get("owner_id") != user_id:
        return None
    return recipe


def screen_my_recipes() -> None:
    user = st.session_state.get("current_user")
    if not user:
        goto("login")
        return
    if render_back_link("처음 화면으로"):
        goto("start")

    client = get_client()
    rows = _my_recipes(user.id, client)

    header_l, header_r = st.columns([4, 1])
    with header_l:
        render_badge(f"{truncate_display_name(user.username)}님이 등록한 레시피 · {len(rows)}개")
    with header_r:
        if st.button("로그아웃", key="my_recipes_logout", use_container_width=True):
            session_logout()
            goto("login")

    if not rows:
        render_spacer()
        st.markdown(f'<div class="ce-lead-icon neutral">{ICON_INBOX}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ce-center"><h1>아직 등록한 레시피가<br>없어요</h1></div>',
            unsafe_allow_html=True,
        )
        render_spacer()
        return

    confirm_id = st.session_state.get("confirm_delete_id")
    # 카드 개수(len(rows))가 삭제로 줄어드는 시점에 #8360류 잔상이 재현되는 걸 막기
    # 위해, 목록 컨테이너 key에 개수를 섞는다(app.py의 st.empty() 슬롯 교체와 별개로,
    # 이 화면 안쪽 목록 자체도 같은 문제를 겪을 수 있음 — 과거 구현과 동일 이유).
    with st.container(key=f"my_recipes_list_{len(rows)}"):
        for row in rows:
            recipe_id = row["id"]
            card_mode = "confirm" if confirm_id == recipe_id else "normal"
            with st.container(key=f"my_recipe_card_{recipe_id}_{card_mode}"):
                c1, c_actions = st.columns([4, 1])
                with c1:
                    st.markdown(
                        f'<div class="ce-recipe-name"><span class="icon">{ICON_BASKET_SM}</span>'
                        f'{row["dish_name"]}</div>',
                        unsafe_allow_html=True,
                    )
                    render_badge(_approval_label(row))
                with c_actions:
                    # st.columns([1,1])는 칸이 넓어질수록 두 버튼도 같이 벌어진다 — 세로
                    # 블록 하나에 버튼 둘을 넣고 CSS(st-key-my_recipe_actions_)로 가로
                    # 정렬 + 오른쪽 붙임 처리해서 화면 폭과 무관하게 항상 붙어있게 한다
                    # (과거 my_recipes.py 구현과 동일한 이유).
                    with st.container(key=f"my_recipe_actions_{recipe_id}"):
                        if st.button(":material/edit:", key=f"my_recipes_edit_{recipe_id}", help="수정"):
                            st.session_state.editing_recipe_id = recipe_id
                            goto("edit_recipe")
                        if st.button(":material/delete:", key=f"my_recipes_delete_{recipe_id}", help="삭제"):
                            st.session_state.confirm_delete_id = recipe_id
                            st.rerun()

                if confirm_id == recipe_id:
                    st.warning(f'"{row["dish_name"]}"를 정말 삭제할까요? 되돌릴 수 없어요.')
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button(
                            "네, 삭제할게요",
                            key=f"my_recipes_confirm_delete_{recipe_id}",
                            type="primary",
                            use_container_width=True,
                        ):
                            delete_recipe(recipe_id, client=client, owner_id=user.id)
                            st.session_state.confirm_delete_id = None
                            st.rerun()
                    with cc2:
                        if st.button(
                            "취소", key=f"my_recipes_cancel_delete_{recipe_id}", use_container_width=True
                        ):
                            st.session_state.confirm_delete_id = None
                            st.rerun()


def screen_edit_recipe() -> None:
    user = st.session_state.get("current_user")
    if not user:
        goto("login")
        return
    recipe_id = st.session_state.get("editing_recipe_id")
    if not recipe_id:
        goto("my_recipes")
        return

    client = get_client()
    recipe = _authorized_recipe(recipe_id, user.id, client)
    if recipe is None:
        st.session_state.editing_recipe_id = None
        goto("my_recipes")
        return

    steps = (
        client.table("recipe_steps")
        .select("step_number,step_text")
        .eq("recipe_id", recipe_id)
        .order("step_number")
        .execute()
        .data
        or []
    )

    if render_back_link("마이레시피로"):
        st.session_state.editing_recipe_id = None
        goto("my_recipes")
    render_spacer()

    st.markdown(f'**{recipe["dish_name"]} 수정**')

    dish_name = st.text_input("요리명", value=recipe["dish_name"], key="edit_recipe_dish_name")
    ingredients_text = st.text_area(
        "재료 (쉼표로 구분)", value=(recipe.get("ingredients") or "").replace("|", ", "), key="edit_recipe_ingredients"
    )
    instructions_text = st.text_area(
        "조리 순서 (한 줄에 한 단계씩)",
        # "N. " 순번 접두어를 떼고 프리필 — _strip_step_prefix() 문서 참고.
        value="\n".join(_strip_step_prefix(s["step_text"]) for s in steps),
        key="edit_recipe_instructions",
        height=200,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("저장", key="edit_recipe_save", type="primary", use_container_width=True):
            ingredients = [x.strip() for x in ingredients_text.split(",") if x.strip()]
            instructions = [x.strip() for x in instructions_text.split("\n") if x.strip()]
            update_recipe(recipe_id, dish_name.strip(), ingredients, instructions, client=client, owner_id=user.id)
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
    with c2:
        if st.button("취소", key="edit_recipe_cancel", use_container_width=True):
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
