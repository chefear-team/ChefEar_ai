"""화면 전환 헬퍼. st.session_state.screen을 바꾸고 즉시 rerun한다."""
import streamlit as st


def goto(screen: str) -> None:
    st.session_state.screen = screen
    # app.py의 main()이 다음 rerun에서 실제 화면 대신 스피너를 한 번 먼저 보여주게 하는
    # 신호(2026-08-20, "화면마다 로딩화면" 요청). 여기서 True로 세팅만 하고, 실제로
    # 소비(pop)하는 쪽은 app.py다.
    st.session_state._screen_loading = True
    st.rerun()
