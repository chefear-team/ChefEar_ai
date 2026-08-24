"""⑧ 신규 등록 2/3 - 재료 + 확인 체크포인트 (FR-06, 2단계 확인 구조 중 1번째)."""
import streamlit as st

from nav import goto
from theme import render_chips, render_dots


def render() -> None:
    data = st.session_state.get("register_data")
    if not data:
        goto("register_intro")

    st.markdown(f'<p class="ce-hint">{data["dish_name"]} · 2 / 3 · 재료</p>', unsafe_allow_html=True)
    render_dots(3, 2)

    st.markdown("**재료를 알려주세요**")
    st.caption("재료를 하나씩 말씀해주시면 목록에 추가해요. 다르면 아래에서 바로 뺄 수도 있어요.")

    render_chips(data["ingredients"])

    c1, c2 = st.columns([3, 1])
    with c1:
        new_item = st.text_input("재료 추가 (예: 오이 1/2개)", key="reg_ing_new", label_visibility="collapsed", placeholder="재료 추가 (예: 오이 1/2개)")
    with c2:
        if st.button("추가", use_container_width=True) and new_item.strip():
            name, _, qty = new_item.strip().partition(" ")
            data["ingredients"].append({"name": name, "qty": qty or "적당량", "emoji": "✅"})
            st.rerun()

    if data["ingredients"]:
        remove_name = st.selectbox(
            "뺄 재료 선택", ["(선택 안 함)"] + [ing["name"] for ing in data["ingredients"]], key="reg_ing_remove"
        )
        if remove_name != "(선택 안 함)" and st.button("선택한 재료 빼기"):
            data["ingredients"] = [ing for ing in data["ingredients"] if ing["name"] != remove_name]
            st.rerun()

    st.markdown(
        '<div class="ce-checkpoint"><p class="title">재료 확인 체크포인트</p>'
        "<p>이 재료들이 맞나요? 다르면 위에서 추가하거나 빼주세요.</p></div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("네, 맞아요", type="primary", use_container_width=True):
            goto("register_steps")
    with c2:
        if st.button("이전", use_container_width=True):
            goto("register_dish_name")
