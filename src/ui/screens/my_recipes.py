"""마이레시피(내가 등록한 레시피 목록/수정/삭제) 화면 — docs/specs/my_recipes.md.

2026-08-22~27 사이 존재했다가 계정 시스템 전체 제거와 함께 삭제됐던 화면(git show
92a29ec^:src/ui/screens/my_recipes.py)을 새 인증 스킴(orchestration.auth.User,
ui.session.get_owner_id())에 맞춰 되살린다 — 카드 레이아웃/삭제 2단계 확인/
잔상 방지 key 패턴은 그때 구현을 그대로 재사용한다.

다른 화면과 달리 이 둘(my_recipes/edit_recipe)도 login/signup과 같은 이유로
app.py::main()이 listen()을 아예 안 부른다(마이크 컴포넌트 자체를 안 그림) —
폼/버튼 조작 전용 화면이라 마이크가 필요 없고, login/signup에서 실제로 겪은
"Cannot create so many PeerConnections" 재현을 미리 피한다.
"""
from __future__ import annotations

import streamlit as st

from theme import ICON_BASKET_SM, ICON_INBOX, render_back_link, render_badge, render_spacer, truncate_display_name
from orchestration.db import get_client
from orchestration.registration import delete_recipe, update_recipe
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


def _approval_label(row: dict) -> str:
    """AC-06 — 승인 상태 배지 문구."""
    return "승인됨" if row.get("approved") == "Y" else "심사중"


def _authorized_recipe(recipe_id: str, user_id: str, client) -> dict | None:
    """AC-05 — recipe_id를 조회하되, 존재하지 않거나 소유자가 다르면 None.

    정상 UI 경로로는 screen_my_recipes()가 이미 본인 소유 레시피만 목록에 올리므로
    남의 recipe_id가 여기 들어올 일이 없지만, editing_recipe_id는 세션 상태값이라
    실제로 고치기 전에 소유권을 한 번 더 확인한다(EC-04, 방어적 처리).
    """
    recipe = client.table("recipes").select("*").eq("id", recipe_id).single().execute().data
    if not recipe or recipe.get("owner_id") != user_id:
        return None
    return recipe


def screen_my_recipes() -> None:
    user = st.session_state.get("current_user")
    if not user:
        goto("login")
        return
    if render_back_link("처음 화면으로"):
        goto("start")

    # 2026-09-01 — 여기 render_spacer()를 뒀었는데(다른 화면들의 관행), 아래 빈 목록
    # 상태(no rows)의 "정가운데 정렬용" render_spacer() 두 개와 같은 flex:1 형제로
    # 경쟁하면서 뒤로가기 링크와 배지 사이에 의도치 않은 큰 공백이 생겼다(사용자 리포트
    # — "윗공간이 붙게 해달라고"). 뒤로가기 링크 바로 아래 배지가 붙어 보이도록 뺀다.
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
        # register.py/cooking.py가 쓰는 "원형 아이콘 + 중앙정렬 제목"(ce-lead-icon +
        # ce-center) 패턴을 그대로 재사용 — st.info()의 파란 박스 대신, 화면 정가운데
        # 빈 상태(empty state) 표시로 통일한다(2026-09-01 요청).
        #
        # render_spacer()로 앞뒤를 감싸는 이유 — render_loading_message()와 완전히
        # 같은 이유(위 그 함수 문서 참고): block-container가 flex column(min-height:
        # 100vh)이라, flex:1인 .ce-spacer 두 개가 위/아래 남는 공간을 똑같이 나눠 가지며
        # 화면 크기와 무관하게 이 블록을 화면 정가운데로 밀어준다(사용자 요청 — "어느
        # 화면에 가도 정가운데에 오게끔"). 헤더(뒤로가기/배지/로그아웃) 아래로 남는
        # 공간 기준의 중앙이다.
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
                            delete_recipe(recipe_id, client=client)
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
        "재료 (쉼표로 구분)", value=recipe.get("ingredients") or "", key="edit_recipe_ingredients"
    )
    instructions_text = st.text_area(
        "조리 순서 (한 줄에 한 단계씩)",
        value="\n".join(s["step_text"] for s in steps),
        key="edit_recipe_instructions",
        height=200,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("저장", key="edit_recipe_save", type="primary", use_container_width=True):
            ingredients = [x.strip() for x in ingredients_text.split(",") if x.strip()]
            instructions = [x.strip() for x in instructions_text.split("\n") if x.strip()]
            update_recipe(recipe_id, dish_name.strip(), ingredients, instructions, client=client)
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
    with c2:
        if st.button("취소", key="edit_recipe_cancel", use_container_width=True):
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
