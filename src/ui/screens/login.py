"""로그인/회원가입 화면 (docs/specs/user_accounts_google_login.md).

2026-08-27에 제거됐던 로그인 화면(remove_user_accounts.md)을 새 스킴으로 재작성한다.
아이디+비밀번호는 발화가 아니라 폼(텍스트 입력)으로만 받는다 — 비밀번호를 마이크에
대고 소리 내어 말하게 하는 건 보안상 부적절하다.

app.py::main()이 이 둘을 포함한 4개 화면(login/signup/my_recipes/edit_recipe)에서
register_ingredients와 같은 방식으로 listen_for_speech=False를 부른다(register_steps는
listen_for_speech를 안 넘겨서 실제로는 STT까지 계속 돌리고 결과만 버리는 별개의 패턴이라
정확히 같지는 않음) — 마이크 연결은 유지하되 음성 처리는 건너뛴다(비밀번호를 마이크에 대고 말하게 하는
건 보안상 부적절하므로 폼으로만 받는다는 원래 취지는 그대로). 한때 "Cannot create so
many PeerConnections" 크래시로 마이크를 아예 안 그리는 쪽으로 후퇴했었으나, 진짜
원인(이 넷만 화면을 짧은 간격으로 반복 왕복해 재협상 중인 연결을 죽은 걸로 오판)을
규명해 voice_io._recover_dead_mic()에서 고쳤다 — app.py의 해당 분기 주석 참고.

구글 로그인은 Streamlit 내장 st.login()/st.user(OIDC)를 그대로 쓴다 — 리다이렉트 왕복은
Streamlit이 알아서 처리하고, 우리 코드는 돌아온 뒤 st.user.is_logged_in만 확인하면
된다(handle_google_login_if_returned(), app.py::main()이 매 rerun 앞부분에서 호출).
"""
from __future__ import annotations

import streamlit as st

from theme import render_back_link, render_spacer
from orchestration import auth
from orchestration.db import get_client
from ui.session import goto, login as session_login, persist_local_session


def screen_login() -> None:
    # 2026-09-01 요청 — 로그인 화면에서 "처음 화면으로" 뒤로가기 링크 주석 처리
    # (로그인을 첫 화면으로 삼은 이상 이 화면에서 굳이 비로그인 우회로를 보여줄
    # 필요가 없다는 판단). app.py 쪽 로그인 아이콘 버튼도 이 화면에서만 같이 뺐다
    # (app.py::main()의 render_brand() 호출부 참고).
    # if render_back_link("처음 화면으로"):
    #     goto("start")
    render_spacer()
    st.markdown("**로그인**")

    # 구글 "G" 로고는 st.button() 라벨(텍스트/머티리얼 아이콘만 지원)로는 못 그려서,
    # key로 잡고 theme.py의 CSS(background-image, [class*="st-key-login_google_btn"])로
    # 아이콘을 입힌다 — render_back_link()의 "스타일은 CSS, 클릭은 실제 st.button()"과
    # 같은 원리.
    if st.button("구글로 로그인", key="login_google_btn", use_container_width=True):
        st.login()  # secrets.toml [auth] 설정 사용, 리다이렉트는 Streamlit이 처리

    st.markdown(
        "<div style='text-align:center;color:var(--muted);margin:10px 0;font-size:13px;'>또는</div>",
        unsafe_allow_html=True,
    )

    _turn = st.session_state.setdefault("login_form_turn", 0)
    username = st.text_input("아이디", key=f"login_username_{_turn}")
    password = st.text_input("비밀번호", type="password", key=f"login_password_{_turn}")

    error = st.session_state.pop("login_error", None)
    if error:
        st.error(error)

    if st.button("로그인", type="primary", use_container_width=True):
        client = get_client()
        user = auth.login_local(username, password, client=client)
        if user is None:
            st.session_state["login_error"] = "아이디 또는 비밀번호가 올바르지 않습니다."
            st.session_state.login_form_turn = _turn + 1
            st.rerun()
            return
        session_login(user)
        persist_local_session(user, client=client)  # 새로고침해도 로그인 유지(2026-09-01)
        goto("start")

    with st.container(key="login_signup_link"):
        if st.button("계정이 없으신가요? 회원가입", use_container_width=True):
            goto("signup")


def screen_signup() -> None:
    if render_back_link("로그인 화면으로"):
        goto("login")
    render_spacer()
    st.markdown("**회원가입**")

    if st.button("구글로 회원가입", key="signup_google_btn", use_container_width=True):
        st.login()  # 로그인과 동일한 진입점 — login_or_create_google()이 신규면 insert

    st.markdown(
        "<div style='text-align:center;color:var(--muted);margin:10px 0;font-size:13px;'>또는</div>",
        unsafe_allow_html=True,
    )

    _turn = st.session_state.setdefault("signup_form_turn", 0)
    username = st.text_input("아이디", key=f"signup_username_{_turn}")
    password = st.text_input("비밀번호 (8자 이상)", type="password", key=f"signup_password_{_turn}")
    password2 = st.text_input("비밀번호 확인", type="password", key=f"signup_password2_{_turn}")

    error = st.session_state.pop("signup_error", None)
    if error:
        st.error(error)

    if st.button("가입하기", type="primary", use_container_width=True):
        if password != password2:
            st.session_state["signup_error"] = "비밀번호가 일치하지 않습니다."  # EC-03
            st.session_state.signup_form_turn = _turn + 1
            st.rerun()
            return
        client = get_client()
        try:
            user = auth.signup_local(username, password, client=client)
        except auth.SignupError as exc:  # EC-01/EC-04/EC-08
            st.session_state["signup_error"] = str(exc)
            st.session_state.signup_form_turn = _turn + 1
            st.rerun()
            return
        session_login(user)
        persist_local_session(user, client=client)  # 새로고침해도 로그인 유지(2026-09-01)
        goto("start")


def handle_google_login_if_returned() -> None:
    """app.py::main()이 매 rerun 시작부에서 호출한다. st.login() 리다이렉트로 돌아온
    직후 st.user.is_logged_in이 True인데 세션엔 아직 current_user가 없는 경우에만
    DB 조회/insert(login_or_create_google, AC-03: 최초 1회만 insert)를 수행한다 —
    이미 세션에 반영돼 있으면 매 rerun마다 DB를 다시 안 친다."""
    if not getattr(st.user, "is_logged_in", False):
        return
    if st.session_state.get("current_user") is not None:
        return
    user = auth.login_or_create_google(st.user.sub, st.user.email, client=get_client())
    session_login(user)
    # 2026-09-01 — 로컬 로그인/회원가입(session_login 직후 goto("start"))과 달리
    # 구글 로그인은 st.login() 리다이렉트로 돌아온 뒤라 화면 상태가 리다이렉트 전
    # 그대로(대개 "login")였다 — current_user는 채워지는데 화면은 안 넘어가서
    # 로그인 화면에 그대로 머무는 버그(사용자 리포트, 2026-09-01)가 있었다. 여기서도
    # goto()를 그대로 쓰면 이 함수 자체가 main()의 화면 렌더링보다 앞에서 호출되는
    # 도중에 st.rerun()이 걸려버려 이번 rerun에서 하려던 나머지 초기화(restore_local_
    # session 등)를 건너뛰게 된다 — goto() 대신 세션 상태만 "start"로 바꿔서, 이번
    # rerun은 그대로 이어가고 그 결과로 그려질 화면만 바꾼다.
    st.session_state.screen = "start"
