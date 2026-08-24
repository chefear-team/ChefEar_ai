"""④ 재료 대체 제안 확인 - 시나리오 B, FR-04 ① 요리명 정확 매칭."""
import streamlit as st

from mock_data import fresh_recipe
from nav import goto
from theme import render_badge, render_chat


def render() -> None:
    render_badge("재료 대체 제안 · FR-04 ①")
    render_chat(
        [
            ("user", "바지락 넣어도 돼?"),
            ("ai", "바지락된장찌개로 등록된 레시피가 있어요. 이걸로 바꿔드릴까요?"),
        ]
    )

    with st.container(key="sc_swap_card"):
        st.markdown(
            '<div class="ce-card" style="text-align:center;">'
            '<span class="ce-chip">된장찌개</span> → <span class="ce-chip substituted">바지락된장찌개</span>'
            "</div>",
            unsafe_allow_html=True,
        )

    st.caption("“아니요”를 선택하면 직전 상태로 그대로 롤백돼요 (EC-21 · cancel_substitution).")

    # 아래 sc_footer_buttons가 하단에 고정(position:fixed)되면서 흐름에서 빠지는 만큼,
    # 마지막 콘텐츠가 그 밑에 가려지지 않도록 같은 높이의 여백을 미리 남겨둔다.
    st.markdown('<div style="height:90px;"></div>', unsafe_allow_html=True)

    with st.container(key="sc_footer_buttons"):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("네, 바꿔주세요", type="primary", use_container_width=True):
                new_recipe = fresh_recipe("bajirak")
                st.session_state.step_number = min(st.session_state.get("step_number", 1), len(new_recipe["steps"]))
                st.session_state.recipe = new_recipe
                st.session_state.substituted_ingredient = None
                st.session_state.chat_log = [("ai", "네, 바지락된장찌개로 바꿔드렸어요.")]
                goto("cooking_step")
        with c2:
            if st.button("아니요, 원래대로", use_container_width=True):
                st.session_state.chat_log = [("ai", "네, 원래 레시피로 계속할게요.")]
                goto("cooking_step")
