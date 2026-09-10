"""로그인/회원가입 화면 (docs/specs/user_accounts_google_login.md)."""
from __future__ import annotations

import streamlit as st

from theme import render_back_link, render_spacer
from orchestration import auth
from orchestration.db import get_client
from ui.session import goto, login as session_login, persist_local_session


def screen_login() -> None:
    # api_standard는 비로그인에게도 전체 공개가 원칙이므로, 로그인 화면에서
    # 비로그인 진입로를 막지 않는다(session.init_state() 주석 참고 — 첫 화면만
    # login일 뿐 비로그인 이용 자체를 막는 게 아니다).
    if render_back_link("비로그인으로 둘러보기"):
        goto("start")
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
        persist_local_session(user, client=client)
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
        persist_local_session(user, client=client)
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
    st.session_state.screen = "start"
