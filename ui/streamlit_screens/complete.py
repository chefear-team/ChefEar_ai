"""⑩ 완료 화면 - FR-08: 원본 보존 + user_custom 별도 저장, 다음 조회 시 개인 버전 우선."""
import streamlit as st

from nav import goto
from theme import ICON_CHECK_CIRCLE, ICON_CHECK_SMALL, render_spacer


def render() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>저장이 완료됐어요!</h1>'
        "<p>다음에 다시 찾으면 회원님 버전으로 먼저 안내해드릴게요.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="text-align:center;">'
        f'<span class="ce-status-badge">{ICON_CHECK_SMALL} 원본 레시피 보존됨</span>'
        f'<span class="ce-status-badge">{ICON_CHECK_SMALL} 나만의 레시피로 저장됨</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="ce-card"><p style="margin:0; font-size:13.5px; color:var(--text-secondary); line-height:1.6;">'
        "원본(api_standard)은 그대로 남고, 회원님이 바꾼 내용은 user_custom으로 별도 저장돼요. "
        "다음 조회부터는 개인 버전이 우선 제공돼요 (FR-08).</p></div>",
        unsafe_allow_html=True,
    )
    render_spacer()

    if st.button("처음 화면으로", type="primary", use_container_width=True):
        st.session_state.recipe = None
        st.session_state.register_data = None
        st.session_state.pending_recipe_key = None
        st.session_state.chat_log = []
        st.session_state.substituted_ingredient = None
        st.session_state.step_number = 1
        for widget_key in ("reg_dish_name_input", "reg_ing_new", "reg_ing_remove", "reg_step_new", "free_text"):
            st.session_state.pop(widget_key, None)
        goto("start")
