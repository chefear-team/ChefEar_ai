"""ChefEar 세션 상태 부트스트랩·화면 전환 — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

speak()/listen() 같은 STT/TTS 연결은 ui/voice_io.py, 화면별 함수는 ui/screens/ 참고.

주의: 이 패키지 이름(`ui`)은 `src/app.py`가 `sys.path.insert(0, PROJECT_ROOT/"ui")`로
따로 얹는 최상위 `ui/`(theme.py 등, `from theme import ...`로 씀) 폴더와 이름이 같지만
서로 다른 경로다 — 이쪽은 `src/ui/`이고 `src`가 sys.path에 있어서 `ui.session`처럼
패키지로 import된다. 헷갈리지 않도록 참고.
"""
from __future__ import annotations

import streamlit as st

# handle_utterance()/advance_step()/register_recipe()가 그대로 받아쓰는 딕셔너리 — 이
# 프로젝트의 오케스트레이션 계약을 그대로 따른다(새 세션 구조를 따로 만들지 않음).
_DEFAULT_PIPELINE_SESSION = {
    "current_recipe_id": None,
    "step_number": 1,
    "registration": None,
}


def init_state() -> None:
    # 2026-09-01 요청 — 첫 진입 화면을 "무엇을 만들고 싶으세요?"(start) 대신 로그인
    # 화면으로 바꾼다. login 화면의 "처음 화면으로" 뒤로가기 링크로 start에 그대로
    # 갈 수 있으므로, 비로그인 이용 자체를 막는 건 아니다 — 세션이 새로 시작될 때
    # 맨 처음 보이는 화면만 바뀐다.
    st.session_state.setdefault("screen", "login")
    st.session_state.setdefault("pipeline_session", dict(_DEFAULT_PIPELINE_SESSION))
    st.session_state.setdefault("chat_log", [])
    # 2026-09-01 — 로그인 재도입(docs/specs/user_accounts_google_login.md).
    # orchestration.auth.User 또는 None. 로컬 로그인/회원가입은 이 값을 직접 채우고,
    # 구글 로그인은 st.user(브라우저 쿠키 기반, Streamlit이 자체로 유지)가 진짜
    # 로그인 상태를 들고 있어서 이 세션 값은 그 결과를 캐시해두는 용도다(app.py::
    # main()이 매 rerun마다 st.user.is_logged_in과 동기화).
    st.session_state.setdefault("current_user", None)
    # 2026-09-01 — 마이레시피 재도입(docs/specs/my_recipes.md). editing_recipe_id는
    # edit_recipe 화면이 수정 대상을 특정할 때, confirm_delete_id는 my_recipes 화면이
    # "정말 삭제할까요?" 확인 문구를 어느 카드에 띄울지 결정할 때 쓴다.
    st.session_state.setdefault("editing_recipe_id", None)
    st.session_state.setdefault("confirm_delete_id", None)
    st.session_state.setdefault("recipe_view", None)  # {"recipe_id","dish_name","ingredients_raw","steps"}
    st.session_state.setdefault("pending_dish_name", None)  # 등록 화면 진입 시 추정 요리명 프리필용
    # listen()의 위젯 키에 붙는 턴 번호. text_input/audio_input 값은 Streamlit 세션에
    # 그대로 남아있어서, goto()의 st.rerun() 이후에도 "다음" 같은 이전 입력이 그대로
    # 다시 읽혀 process_utterance()가 무한 반복 호출되는 버그가 있었다(2026-08-19,
    # AppTest로 발견 — "다음" 한 번 입력했는데 스텝이 끝없이 올라가다 타임아웃).
    # 매번 새 키를 쓰게 해서 이전 위젯 값이 절대 재사용되지 않게 한다.
    st.session_state.setdefault("input_turn", 0)
    # voice_io.prefetch_remaining_steps_audio()의 백그라운드 스레드가 "사용자가 아직도
    # 이 레시피를 보고 있는지" 확인할 때 쓰는 평범한 dict(2026-08-22 요청 — 사용자가
    # 초기 화면으로 돌아가거나 다른 레시피로 넘어가도 버려진 레시피의 남은 단계를 계속
    # 만들고 있으면 안 됨). st.session_state를 백그라운드 스레드에서 직접 읽는 건
    # Streamlit이 지원하지 않는 위험한 패턴이라(ScriptRunContext 필요), 이 안에 담긴
    # "평범한 파이썬 dict" 객체 하나를 스레드에 넘겨서 그것만 읽고 쓰게 한다 — main()이
    # 매 rerun마다 이 값을 pipeline_session["current_recipe_id"]와 동기화한다
    # (src/app.py 참고).
    st.session_state.setdefault("_active_recipe_box", {"recipe_id": None})
    # 2026-08-28 — 세션 요리명 조회 캐시. 같은 메뉴를 반복해서 물어볼 때 LLM/임베딩/DB를
    # 다시 안 타게 한다(ui/dispatch.py::process_utterance() / ui/recipe_view.py::
    # refresh_recipe_view() 참고). reset_to_start()는 이 둘을 안 지운다 — 만개레시피
    # 실데이터는 세션 도중 안 바뀌므로 세션 수명 내내 유효하다.
    st.session_state.setdefault("_recipe_lookup_cache", {})  # 정규화 발화 -> {"recipe_id","dish_name"}
    st.session_state.setdefault("_recipe_view_cache", {})    # recipe_id -> recipe_view dict


def goto(screen: str) -> None:
    """화면을 전환한다.

    2026-08-24 — "더블 rerun 플러시"(goto()마다 st.rerun()을 두 번 태워서 화면 전환
    잔상을 지우려던 시도)는 되돌렸다. 잔상도 안 없어졌고("A->B->C에서 초기로 돌아가도
    잔상이 남는다"는 리포트로 여러 화면을 거치면 계속 쌓이는 전반적인 문제임이 확인됨),
    오히려 goto()마다 마이크 프레임을 하나도 안 비우는 "빈" 실행이 하나 더 끼어들면서
    그 왕복 시간만큼 webrtc audio_receiver 큐가 못 비워지는 구간이 늘어나 "Queue
    overflow" 경고가 급증하는 부작용만 생겼다(실측 확인). 단순한 st.rerun() 한 번으로
    되돌린다.
    """
    st.session_state.screen = screen
    st.rerun()


def login(user) -> None:
    """orchestration.auth.User를 세션에 로그인 상태로 기록한다(로컬/구글 공통 진입점)."""
    st.session_state.current_user = user


def persist_local_session(user, client=None) -> None:
    """일반(로컬) 로그인/회원가입 성공 직후 호출 — 새로고침해도 로그인이 안 풀리게
    한다(2026-09-01 사용자 요청).

    st.session_state는 브라우저를 새로고침하면 통째로 사라지지만, 브라우저 주소창의
    쿼리파라미터(st.query_params)는 새로고침해도 URL의 일부로 그대로 남는다 — 이
    성질을 이용해서, 로그인 성공 시 무작위 세션 토큰(orchestration.auth.
    create_session_token(), 추측 불가능)을 발급해 주소창에 실어두고, 다음 로드 때
    restore_local_session()이 그 토큰으로 계정을 다시 찾는다.

    구글 로그인은 이 함수를 호출하지 않는다 — Streamlit 자체 OIDC 쿠키(st.user)가
    이미 새로고침에도 살아남아서 이 메커니즘이 따로 필요 없다.
    """
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


def logout() -> None:
    """로그아웃. 구글 계정으로 로그인한 상태였다면 Streamlit이 들고 있는 OIDC 쿠키도
    같이 지워야 다음 방문 때 자동 재로그인되지 않는다(st.login() 문서: st.logout()이
    쿠키를 지움). 로컬 로그인은 애초에 쿠키가 없으니 그냥 넘어간다.

    2026-09-01 — persist_local_session()이 심어둔 세션 유지 토큰도 여기서 같이
    정리한다. 서버 쪽(DB) 토큰을 안 지우면, 주소창에 남아있는 URL을 나중에 다시 열었을
    때 로그아웃 이전 계정으로 재로그인돼버린다.
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
