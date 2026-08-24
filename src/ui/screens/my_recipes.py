"""ChefEar 마이 레시피(로그인/회원가입 -> 내가 등록한 레시피 목록 -> 수정/삭제) 화면 —
src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

2026-08-22: 목업(.env TEST_LOGIN_ID/PASSWORD 단일 계정) 로그인을 진짜 계정 시스템으로
바꿨다 — orchestration/auth.py의 create_user()/authenticate_user()로 회원가입/로그인하고,
users 테이블(db/schema.sql)에 아이디/비밀번호 해시를 저장한다. 이 로그인은 FR-08의 쿠키
owner_id(회원가입 없이 같은 브라우저를 기억하는 익명 식별, orchestration/identity.py)와는
별개 개념이지만, 로그인한 상태에서 새 레시피를 등록하면 ui/session.py의 get_owner_id()가
쿠키 대신 이 계정 id를 recipes.owner_id로 쓴다 — 그래서 아래 screen_my_recipes()가 계정
기준(owner_id == 로그인한 내 id)으로 "내가 등록한 레시피"를 제대로 걸러낼 수 있다.
"""
from __future__ import annotations

import streamlit as st

from theme import ICON_BASKET_SM, ICON_CHECK_CIRCLE, render_back_link, render_badge, render_spacer
from orchestration.auth import authenticate_user, create_user
from orchestration.db import get_client
from orchestration.registration import delete_recipe, update_recipe
from ui.session import goto, login, logout


def screen_login() -> None:
    """로그인/회원가입을 탭이 아니라 한 화면 안에서 링크로 전환한다(2026-08-22 재요청 —
    "계정이 없으신가요? 회원가입" 링크로). _login_view 세션 상태로 login/signup/
    signup_done 세 모드를 오간다 - my_recipes.py 안에서만 쓰는 값이라 ui/session.py의
    init_state()에는 안 넣고 여기서 setdefault한다(register.py의 reg_step_editing_idx와
    같은 패턴).

    회원가입 성공 시 바로 로그인시키지 않고(2026-08-22 재요청) "회원가입이 완료됐어요!"
    화면을 한 번 보여준 뒤 "로그인하기"를 눌러야 로그인 폼으로 돌아간다 - 아이디/비밀번호를
    직접 입력해서 로그인하는 과정 자체가 "계정이 잘 만들어졌다"는 확인이 되게 한다.
    """
    if render_back_link("첫화면으로 가기"):
        st.session_state["_login_view"] = "login"
        goto("start")

    view = st.session_state.setdefault("_login_view", "login")

    render_spacer()

    if view == "signup_done":
        st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
        st.markdown('<div class="ce-center"><h1>회원가입이 완료됐어요!</h1></div>', unsafe_allow_html=True)
        render_spacer()
        if st.button("로그인하기", type="primary", use_container_width=True, key="signup_done_login_btn"):
            st.session_state["_login_view"] = "login"
            st.rerun()
        return

    title = "회원가입" if view == "signup" else "로그인"
    st.markdown(
        f'<div class="ce-center"><h1>{title}</h1>'
        "<p>등록한 레시피를 관리하려면 로그인해주세요.</p></div>",
        unsafe_allow_html=True,
    )
    render_spacer()

    if view == "signup":
        new_id = st.text_input("아이디", key="signup_id_input")
        new_pw = st.text_input("비밀번호", type="password", key="signup_pw_input")
        new_pw2 = st.text_input("비밀번호 확인", type="password", key="signup_pw2_input")
        if st.button("회원가입", type="primary", use_container_width=True, key="signup_submit"):
            if new_pw != new_pw2:
                st.error("비밀번호가 서로 달라요.")
            else:
                try:
                    create_user(new_id, new_pw)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["_login_view"] = "signup_done"
                    st.rerun()
        if st.button("이미 계정이 있으신가요? 로그인", key="signup_to_login_link", use_container_width=True):
            st.session_state["_login_view"] = "login"
            st.rerun()
    else:
        user_id = st.text_input("아이디", key="login_id_input")
        password = st.text_input("비밀번호", type="password", key="login_pw_input")
        if st.button("로그인", type="primary", use_container_width=True, key="login_submit"):
            user = authenticate_user(user_id, password)
            if user:
                login(user)
                goto("start")
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않아요.")
        if st.button("계정이 없으신가요? 회원가입", key="login_to_signup_link", use_container_width=True):
            st.session_state["_login_view"] = "signup"
            st.rerun()


def screen_my_recipes() -> None:
    current_user = st.session_state.current_user
    if not current_user:
        goto("login")
        return
    if render_back_link("첫화면으로 가기"):
        goto("start")

    client = get_client()
    rows = (
        client.table("recipes")
        .select("id,dish_name,created_at")
        .eq("source", "user_custom")
        .eq("owner_id", current_user["id"])  # 2026-08-22 - 로그인한 계정 소유만 걸러낸다
        .order("created_at", desc=True)
        .execute()
        .data
    )

    header_l, header_r = st.columns([4, 1])
    with header_l:
        render_badge(f'{current_user["username"]}님이 등록한 레시피 · {len(rows)}개')
    with header_r:
        if st.button("로그아웃", key="my_recipes_logout", use_container_width=True):
            logout()
            goto("login")

    if not rows:
        st.info("아직 등록한 레시피가 없어요. 로그인한 상태에서 새 레시피를 등록하면 여기 보여요.")
        return

    confirm_id = st.session_state.confirm_delete_id
    # 2026-08-22 요청 - 레시피가 많아지면 목록이 화면 밖으로 길게 늘어나던 걸, 일정
    # 높이가 넘으면 그 안에서만 스크롤되게 감싼다(CSS는 theme.py의 st-key-my_recipes_list
    # 선택자 참고).
    with st.container(key="my_recipes_list"):
        for row in rows:
            with st.container(key=f"my_recipe_card_{row['id']}"):
                c1, c_actions = st.columns([5, 2])
                with c1:
                    st.markdown(
                        f'<div class="ce-recipe-name"><span class="icon">{ICON_BASKET_SM}</span>{row["dish_name"]}</div>',
                        unsafe_allow_html=True,
                    )
                with c_actions:
                    # st.columns([1,1])는 c_actions 칸 자체가 넓어지면 두 버튼도 같이
                    # 벌어진다(각 컬럼이 그 절반씩을 차지) - 화면이 넓을수록 간격이
                    # 커지는 문제가 실측으로 확인됐다(2026-08-21). 컬럼 대신 세로
                    # 블록 하나에 버튼 둘을 넣고 CSS로 가로 정렬 + 오른쪽 붙임
                    # 처리해서, 화면 폭과 무관하게 항상 붙어있게 한다.
                    with st.container(key=f"my_recipe_actions_{row['id']}"):
                        if st.button(":material/edit:", key=f"edit_{row['id']}", help="수정"):
                            st.session_state.editing_recipe_id = row["id"]
                            goto("edit_recipe")
                        if st.button(":material/delete:", key=f"delete_{row['id']}", help="삭제"):
                            st.session_state.confirm_delete_id = row["id"]
                            st.rerun()

                if confirm_id == row["id"]:
                    st.warning(f'"{row["dish_name"]}"를 정말 삭제할까요? 되돌릴 수 없어요.')
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button(
                            "네, 삭제할게요", key=f"confirm_delete_{row['id']}", type="primary", use_container_width=True
                        ):
                            delete_recipe(row["id"], client=client)
                            st.session_state.confirm_delete_id = None
                            st.rerun()
                    with cc2:
                        if st.button("취소", key=f"cancel_delete_{row['id']}", use_container_width=True):
                            st.session_state.confirm_delete_id = None
                            st.rerun()


def screen_edit_recipe() -> None:
    current_user = st.session_state.current_user
    if not current_user:
        goto("login")
        return
    recipe_id = st.session_state.editing_recipe_id
    if not recipe_id:
        goto("my_recipes")
        return

    client = get_client()
    recipe = client.table("recipes").select("*").eq("id", recipe_id).single().execute().data
    # 2026-08-22 - screen_my_recipes()가 이미 current_user 소유 레시피만 목록에 올려서
    # 정상 경로로는 남의 recipe_id가 여기 들어올 일이 없지만, editing_recipe_id는 세션
    # 상태값이라 실제로 저장/삭제하기 전에 소유권을 한 번 더 확인한다(방어적 처리).
    if not recipe or recipe.get("owner_id") != current_user["id"]:
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
    )

    if render_back_link("첫화면으로 가기"):
        st.session_state.editing_recipe_id = None
        goto("start")

    st.markdown(f'**{recipe["dish_name"]} 수정**')

    dish_name = st.text_input("요리명", value=recipe["dish_name"], key="edit_dish_name")
    ingredients_text = st.text_area(
        "재료 (쉼표로 구분)", value=recipe.get("ingredients") or "", key="edit_ingredients"
    )
    instructions_text = st.text_area(
        "조리 순서 (한 줄에 한 단계씩)",
        value="\n".join(s["step_text"] for s in steps),
        key="edit_instructions",
        height=200,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("저장", type="primary", use_container_width=True):
            ingredients = [x.strip() for x in ingredients_text.split(",") if x.strip()]
            instructions = [x.strip() for x in instructions_text.split("\n") if x.strip()]
            update_recipe(recipe_id, dish_name.strip(), ingredients, instructions, client=client)
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
    with c2:
        if st.button("취소", use_container_width=True):
            st.session_state.editing_recipe_id = None
            goto("my_recipes")
