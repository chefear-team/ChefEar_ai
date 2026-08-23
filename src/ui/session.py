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
    "previous_recipe_id": None,
    "registration": None,
    "owner_id": None,
}


def init_state() -> None:
    st.session_state.setdefault("screen", "start")
    st.session_state.setdefault("pipeline_session", dict(_DEFAULT_PIPELINE_SESSION))
    st.session_state.setdefault("chat_log", [])
    st.session_state.setdefault("recipe_view", None)  # {"recipe_id","dish_name","ingredients_raw","steps"}
    st.session_state.setdefault("pending_dish_name", None)  # no_match -> 등록 유도용
    # 마이 레시피(로그인 -> 내가 등록한 레시피 목록 -> 수정/삭제) 관련 상태.
    # current_user는 로그인 성공 시 {"id","username"}(orchestration/auth.py의
    # authenticate_user() 반환값), 로그아웃 상태면 None이다. 세션이 끝나면(브라우저
    # 새로고침 등) 다시 로그인해야 한다 - "로그인 상태 유지" 같은 영속 세션은 아직 없음.
    st.session_state.setdefault("current_user", None)
    st.session_state.setdefault("editing_recipe_id", None)  # edit_recipe 화면이 수정 중인 레시피
    st.session_state.setdefault("confirm_delete_id", None)  # my_recipes 화면의 삭제 확인 대상
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


def goto(screen: str) -> None:
    st.session_state.screen = screen
    st.rerun()


# 로그인 계정 id를 저장해두는 쿠키 키(작업3의 익명 owner_id 쿠키, identity.COOKIE_KEY와는
# 다른 키). 같은 EncryptedCookieManager(prefix="chefear/")를 재사용하니 브라우저에서
# 보면 이 둘이 같은 쿠키 묶음 안에 나란히 들어간다.
_LOGIN_COOKIE_KEY = "chefear_user_id"


def restore_login_from_cookie() -> None:
    """새로고침해도 로그인이 풀리지 않게, 앱이 뜰 때 로그인 쿠키로 세션을 복원한다
    (2026-08-22 요청 — "로그인 되면 세션, 쿠키는 물려있어야지 계속").

    main()이 매 rerun마다 부르지만, 이번 브라우저 세션에서 이미 한 번 시도했으면
    (성공/실패 무관, _login_cookie_checked) 다시 쿠키 컴포넌트와 통신하지 않는다 —
    get_owner_id()와 달리 이건 "특정 버튼을 눌렀을 때"가 아니라 "화면이 뜰 때마다"
    실행돼야 해서, 매번 쿠키 컴포넌트를 기다리면 불필요하게 느려진다.

    쿠키 컴포넌트가 아직 준비 안 됐으면(cookies.ready()==False) st.stop()으로 이번
    실행을 멈추고 다음 rerun을 기다린다(get_owner_id()와 같은 패턴) — 그때 다시
    시도해야 하므로 _login_cookie_checked를 이번엔 True로 남기지 않는다.
    """
    if st.session_state.current_user is not None:
        return
    if st.session_state.get("_login_cookie_checked"):
        return
    try:
        from orchestration.identity import build_cookie_manager

        cookies = build_cookie_manager()
        if not cookies.ready():
            st.stop()
        st.session_state["_login_cookie_checked"] = True
        user_id = cookies.get(_LOGIN_COOKIE_KEY)
        if user_id:
            from orchestration.auth import get_user_by_id

            user = get_user_by_id(user_id)
            if user:
                st.session_state.current_user = user
    except Exception:
        # COOKIE_SECRET 미설정 등 - 쿠키가 안 돼도 서비스는 계속 동작해야 한다
        # (EC-04와 같은 "손대지 않는 최소 fallback" 정신). 이번 세션은 그냥 매번
        # 새로 로그인해야 할 뿐, 로그인 자체가 막히진 않는다.
        st.session_state["_login_cookie_checked"] = True


def login(user: dict) -> None:
    """로그인/회원가입 성공 시 세션 상태 + 쿠키(새로고침 유지용)를 같이 채운다."""
    st.session_state.current_user = user
    try:
        from orchestration.identity import build_cookie_manager

        cookies = build_cookie_manager()
        if cookies.ready():
            cookies[_LOGIN_COOKIE_KEY] = user["id"]
            cookies.save()
    except Exception:
        pass  # 쿠키 저장이 실패해도 이번 세션 안에서는 로그인 상태가 그대로 유지됨


def logout() -> None:
    """세션 상태 + 쿠키를 같이 지운다."""
    st.session_state.current_user = None
    try:
        from orchestration.identity import build_cookie_manager

        cookies = build_cookie_manager()
        if cookies.ready():
            cookies[_LOGIN_COOKIE_KEY] = ""
            cookies.save()
    except Exception:
        pass


def get_owner_id() -> str | None:
    """레시피 등록 시 recipes.owner_id에 쓸 식별자를 고른다.

    2026-08-22부터 우선순위가 생겼다: 로그인한 계정이 있으면(current_user, 진짜
    아이디/비밀번호 계정) 그 계정 id를 최우선으로 쓴다 — 그래야 로그인해서 등록한
    레시피가 "내가 등록한 레시피"(screen_my_recipes())에 계정 기준으로 걸러져
    나온다. 로그인하지 않았으면 기존 방식(작업3, FR-08)대로 쿠키 UUID를 쓴다 —
    회원가입 없이도 자유발화로 레시피를 등록하는 조리 흐름은 그대로 동작해야 하므로
    (음성 우선 UX 원칙상 등록 도중 로그인을 강제하지 않음), 로그인 여부와 무관하게
    등록 자체는 항상 되게 하기 위한 fallback이다.

    컴포넌트가 없거나 실패해도 서비스는 계속 동작한다 — select_standard_recipe()가
    owner_id=None을 "개인화 없이 표준만" 취급하도록 이미 설계돼 있어서(하위 호환),
    쿠키가 안 돼도 조회/진행 자체는 죽지 않는다(EC-04와 같은 "손대지 않는 최소
    fallback" 정신).
    """
    current_user = st.session_state.get("current_user")
    if current_user:
        # 2026-08-22 리포트 — 여기서 반환만 하고 pipeline_session에 안 쓰고 있었다.
        # register_intro의 "네, 등록할래요" 버튼은 이 함수의 반환값을 안 쓰고 그냥
        # 호출만 하므로(get_owner_id() 자체가 부작용으로 세션에 남겨야 함), 로그인
        # 상태로 등록해도 confirm 시점(session.get("owner_id"))엔 계속 None이라 계정에
        # 안 묶이는 버그였다. 아래 쿠키 분기처럼 여기서도 캐시해서 고친다. 매 호출마다
        # 최신 로그인 계정으로 덮어써야 하므로(로그인 전에 캐시된 쿠키 값이 남아있을 수
        # 있음) 아래 cached 캐시 확인보다 먼저 처리한다.
        st.session_state.pipeline_session["owner_id"] = current_user["id"]
        return current_user["id"]

    cached = st.session_state.pipeline_session.get("owner_id")
    if cached:
        return cached
    try:
        from orchestration.identity import build_cookie_manager, get_or_create_anon_id

        cookies = build_cookie_manager()
        if not cookies.ready():
            st.stop()
        anon_id = get_or_create_anon_id(cookies)
        st.session_state.pipeline_session["owner_id"] = anon_id
        return anon_id
    except Exception:
        return None
