"""ChefEar 세션 상태 초기화(`init_state`)와 화면 전환(`goto`, `reset_to_start`)."""
from __future__ import annotations

import secrets

import streamlit as st

# handle_utterance()/advance_step()/register_recipe()가 그대로 받아쓰는 딕셔너리 — 이
# 프로젝트의 오케스트레이션 계약을 그대로 따른다(새 세션 구조를 따로 만들지 않음).
_DEFAULT_PIPELINE_SESSION = {
    "current_recipe_id": None,
    "step_number": 1,
    "registration": None,
}


def init_state() -> None:
    st.session_state.setdefault("_sid", secrets.token_hex(3))
    st.session_state.setdefault("screen", "login")
    st.session_state.setdefault("pipeline_session", dict(_DEFAULT_PIPELINE_SESSION))
    st.session_state.setdefault("chat_log", [])
    st.session_state.setdefault("current_user", None)
    st.session_state.setdefault("editing_recipe_id", None)
    st.session_state.setdefault("confirm_delete_id", None)
    st.session_state.setdefault("recipe_view", None)  # {"recipe_id","dish_name","ingredients_raw","steps"}
    st.session_state.setdefault("pending_dish_name", None)  # 등록 화면 진입 시 추정 요리명 프리필용
    st.session_state.setdefault("input_turn", 0)
    st.session_state.setdefault("_active_recipe_box", {"recipe_id": None})
    st.session_state.setdefault("_recipe_lookup_cache", {})  # 정규화 발화 -> {"recipe_id","dish_name"}
    st.session_state.setdefault("_recipe_view_cache", {})    # recipe_id -> recipe_view dict


def goto(screen: str) -> None:
    """화면을 전환한다."""
    print(
        f"[GOTO] sid={st.session_state.get('_sid')} "
        f"{st.session_state.get('screen')!r} -> {screen!r}",
        flush=True,
    )
    st.session_state.screen = screen
    st.rerun()


def login(user) -> None:
    """orchestration.auth.User를 세션에 로그인 상태로 기록한다(로컬/구글 공통 진입점)."""
    st.session_state.current_user = user


def persist_local_session(user, client=None) -> None:
    """일반(로컬) 로그인/회원가입 성공 직후 호출 — 새로고침해도 로그인이 안 풀리게"""
    from orchestration import auth
    from orchestration.db import get_client

    client = client or get_client()
    token = auth.create_session_token(user.id, client)
    st.query_params["session_token"] = token


def restore_local_session(client=None) -> None:
    """app.py::main()이 매 rerun 시작부에서 호출한다. 이미 로그인 상태(current_user
    있음)면 아무것도 안 한다 — persist_local_session()이 심어둔 st.query_params의
    session_token으로 아직 로그인이 안 된 경우에만 계정을 복원한다.

    한계: 탭을 닫았다 나중에 주소창에 토큰 없는 새 URL로 재방문하면 복원 안 된다
    (쿠키/localStorage가 아니라 주소창 쿼리파라미터 기반이라서) — "새로고침에도 로그인이
    안 풀리게" 요청 범위까지만 해결한다.
    """
    if st.session_state.get("current_user") is not None:
        return
    token = st.query_params.get("session_token")
    if not token:
        return

    from orchestration import auth
    from orchestration.db import get_client

    client = client or get_client()
    user = auth.resolve_session_token(token, client)
    if user is None:
        del st.query_params["session_token"]  # 만료/무효 토큰이면 주소창에서도 정리
        return
    st.session_state.current_user = user
    st.session_state.screen = "start"


def logout() -> None:
    """로그아웃. 구글 계정으로 로그인한 상태였다면 Streamlit이 들고 있는 OIDC 쿠키도
    같이 지워야 다음 방문 때 자동 재로그인되지 않는다(st.login() 문서: st.logout()이
    쿠키를 지움). 로컬 로그인은 애초에 쿠키가 없으니 그냥 넘어간다.
    """
    user = st.session_state.get("current_user")
    if getattr(st.user, "is_logged_in", False):
        st.logout()
    if user is not None:
        from orchestration import auth
        from orchestration.db import get_client

        auth.clear_session_token(user.id, client=get_client())
    if "session_token" in st.query_params:
        del st.query_params["session_token"]
    st.session_state.current_user = None


def get_owner_id() -> str | None:
    """레시피 등록 시 `recipes.owner_id`에 넣을 값. 비로그인 상태면 None(기존과 동일)."""
    user = st.session_state.get("current_user")
    return user.id if user else None
