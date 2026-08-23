"""⑥ 신규 등록 제안 - 시나리오 D, 6.5: 표준 데이터 밖 요리 요청 시 등록으로 유도."""
import copy

import streamlit as st

from mock_data import REGISTER_DEFAULTS
from nav import goto
from theme import ICON_SPARKLE, render_chat, render_spacer


def render() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon neutral">{ICON_SPARKLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>표준 레시피에 없는 요리예요</h1>'
        "<p>60,282개 표준 레시피 안에는 없지만, 직접 알려주시면 회원님 레시피로 등록해드릴게요.</p></div>",
        unsafe_allow_html=True,
    )

    last_user_msg = next((t for r, t in reversed(st.session_state.get("chat_log", [])) if r == "user"), "문어초무침 어떻게 만들어?")
    render_chat(
        [
            ("user", last_user_msg),
            ("ai", "죄송해요, 이 요리는 아직 등록된 레시피가 없어요. 직접 알려주시면 등록해드릴까요?"),
        ]
    )

    render_spacer()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("네, 등록할래요", type="primary", use_container_width=True):
            st.session_state.register_data = {
                "dish_name": "",
                "ingredients": copy.deepcopy(REGISTER_DEFAULTS["ingredients"]),
                "steps": list(REGISTER_DEFAULTS["steps"]),
            }
            goto("register_dish_name")
    with c2:
        if st.button("괜찮아요", use_container_width=True):
            goto("start")
