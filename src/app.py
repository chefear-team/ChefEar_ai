"""ChefEar 서비스 엔트리포인트 — `streamlit run src/app.py`.

상시 마이크 입력 → STT → 오케스트레이션(의도분류·레시피 조회·등록) → TTS 재생을 한 화면
루프로 엮고, 화면 컴포넌트(`src/ui/`)와 공용 스타일(`ui/theme.py`)을 조립한다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "ui"))

import threading

import streamlit as st

from orchestration.db import load_env
from theme import (
    inject_css,
    render_access_blocked,
    render_brand,
    render_error_notice,
    render_screen_cleanup,
)
from ui.dispatch import process_utterance
from ui.screens.cooking import (
    handle_recipe_confirm,
    screen_cooking_complete,
    screen_cooking_step,
    screen_recipe_confirm,
    screen_start,
)
from ui.screens.login import (
    handle_google_login_if_returned,
    screen_login,
    screen_signup,
)
from ui.screens.my_recipes import screen_edit_recipe, screen_my_recipes
from ui.screens.register import (
    handle_register_dish_name,
    screen_complete,
    screen_register_dish_name,
    screen_register_ingredients,
    screen_register_steps,
    screen_unclassified,
)
from ui.session import _DEFAULT_PIPELINE_SESSION, goto, init_state, restore_local_session
from ui.voice_io import listen

load_env()

SCREENS = {
    "start": screen_start,
    "recipe_confirm": screen_recipe_confirm,
    "cooking_step": screen_cooking_step,
    "cooking_complete": screen_cooking_complete,
    "unclassified": screen_unclassified,
    "register_dish_name": screen_register_dish_name,
    "register_ingredients": screen_register_ingredients,
    "register_steps": screen_register_steps,
    "complete": screen_complete,
    "login": screen_login,
    "signup": screen_signup,
    "my_recipes": screen_my_recipes,
    "edit_recipe": screen_edit_recipe,
}

# 화면 본문 뒤에 붙이는 빈 슬롯 개수(main()의 st.empty() 스왑 안, #8360 꼬리 패딩).
# 화면 중 본문이 가장 긴 것(cooking_step: 대화기록+칩+마이크바+fallback 버튼)과 가장
# 짧은 것(start)의 top-level 엘리먼트 수 차이를 넉넉히 덮을 만큼. 빈 st.empty()라 렌더
# 비용·시각 영향 없음.
_SCREEN_TRAILING_PAD = 25

# 음성 트리거로 관리자 페이지↔메인을 전환할 때 st.switch_page()에 넘길 st.Page 객체.
# __main__ 블록이 Page를 실제로 만들 때 여기에 채운다(main()/_exit_admin()은 읽기만).
_MAIN_PAGE = None
_ADMIN_PAGE = None


def _access_gate_ok() -> bool:
    """랜딩페이지(https://chefear-landingpage.vercel.app) 버튼을 거쳐 ?key=<토큰>이
    붙은 URL로 들어왔는지 확인한다( Cloudflare Tunnel로 chefear.store를
    공개해둔 상태에서, 랜딩페이지 버튼을 거치지 않은 직접 URL 접근을 "토큰 붙은 URL"
    방식으로 약하게 막음. 완전한 보안 아님 — 대화 배경은 render_access_blocked 문서
    참고).
    """
    expected = os.environ.get("ACCESS_GATE_TOKEN", "").strip()
    if not expected:
        return True
    if st.query_params.get("key") == expected:
        st.session_state["_access_ok"] = True
        return True
    return bool(st.session_state.get("_access_ok"))


def _admin_gate_ok() -> bool:
    """관리자 페이지 접근 게이트 **1차** — `.env`의 ADMIN_ACCESS_TOKEN 토큰
    (docs/specs/admin_recipe_approval.md). 2차(화자검증)는 통과 뒤 `_run_admin_page()`
    안에서 `ui/screens/admin_auth.py`가 한다(docs/specs/admin_voice_2fa.md).

    _access_gate_ok()와 정반대 방향의 기본값을 쓴다는 점에 주의: 토큰이 비어있으면
    _access_gate_ok()는 fail-open(게이트 꺼짐, 로컬 개발 편의)이지만, 여긴
    fail-closed(아무도 못 들어감)다. 여긴 "약한 접근 제한"이 아니라 레시피 승인/삭제
    같은 실제 데이터 조작 권한이라, 설정을 깜빡했을 때 기본값이 안전한 쪽(닫힘)이어야
    한다.
    """
    expected = os.environ.get("ADMIN_ACCESS_TOKEN", "").strip()
    if not expected:
        return False
    return st.query_params.get("admin_key") == expected


def _enroll_gate_ok() -> bool:
    """관리자 목소리 등록 화면(`/enroll?enroll_key=`) 접근 게이트 —
    docs/specs/admin_voice_2fa.md. `_admin_gate_ok()`와 완전히 같은 fail-closed 패턴,
    별개 시크릿(ADMIN_ENROLL_TOKEN). 등록이 끝나면 이 값을 비우거나 바꿔서 등록 창을
    닫아두는 걸 권장한다."""
    expected = os.environ.get("ADMIN_ENROLL_TOKEN", "").strip()
    if not expected:
        return False
    return st.query_params.get("enroll_key") == expected


def _start_model_warmup() -> None:
    """gpu_worker_pool의 GPU 워커 프로세스들을 백그라운드 스레드에서 미리 띄워둔다."""
    if st.session_state.get("_warmup_thread_started"):
        return
    st.session_state["_warmup_thread_started"] = True

    def _run() -> None:
        from orchestration.gpu_worker_pool import warm_pool

        try:
            warm_pool()
        except Exception as exc:  # noqa: BLE001 — 위 문서 참고, 조용히 넘어감
            print(f"[app] gpu_worker_pool 워밍업 실패: {exc!r}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


_DEBUG_FAKE_RECIPE_ID = "00000000-0000-0000-0000-000000000001"


def _debug_fill_fake_state(screen: str) -> None:
    st.session_state.screen = screen
    if screen == "start":
        # 깨끗한 초기 상태로(잔상 테스트의 도착 화면) — 가짜 값 안 채운다.
        st.session_state.pipeline_session = dict(_DEFAULT_PIPELINE_SESSION)
        st.session_state.recipe_view = None
        st.session_state.chat_log = []
        st.session_state.pending_dish_name = None
        return
    # recipe_id는 실제 UUID 형식이어야 한다 — 임의 문자열이면 manual_fallback()/
    # advance_step()의 Supabase 쿼리가 "invalid input syntax for type uuid"로 크래시.
    # _ts를 채워야 recipe_view.py::_view_cache_fresh()가 이 가짜 view를 신선한 걸로
    # 보고 refresh_recipe_view()가 존재하지 않는 UUID로 DB 재조회(.single() -> PGRST116
    # 크래시)를 안 한다.
    import time as _t

    st.session_state.recipe_view = {
        "recipe_id": _DEBUG_FAKE_RECIPE_ID,
        "dish_name": "디버그용 테스트 요리",
        "ingredients_raw": "테스트 재료 1개",
        "steps": [{"step_number": 1, "text": "테스트 1단계"}],
        "_ts": _t.monotonic(),
    }
    st.session_state.pipeline_session["current_recipe_id"] = _DEBUG_FAKE_RECIPE_ID
    st.session_state.pipeline_session["step_number"] = 1
    # register_ingredients/register_steps는 pipeline_session["registration"]이 없으면
    # 곧장 start로 튕겨나간다(screen_register_ingredients() 상단 가드).
    if screen in ("register_ingredients", "register_steps"):
        st.session_state.pipeline_session["registration"] = {
            "dish_name": "디버그용 테스트 요리",
            "ingredients": ["테스트 재료 1개"],
            "instructions": ["테스트 1단계"],
        }
    st.session_state.pending_dish_name = "디버그용 테스트 요리"


# 디버그 패널 "화면 점프" 버튼 목록 (라벨, 화면키).
_DEBUG_JUMP_SCREENS = (
    ("등록 1·요리명", "register_dish_name"),
    ("등록 2·재료", "register_ingredients"),
    ("등록 3·순서", "register_steps"),
    ("저장 완료", "complete"),
    ("조리 확인", "recipe_confirm"),
    ("조리 단계", "cooking_step"),
    ("조리 완료", "cooking_complete"),
    ("미분류", "unclassified"),
    ("처음(start)", "start"),
)


def main() -> None:

    if not _access_gate_ok():
        inject_css()
        render_access_blocked()
        st.stop()

    if (
        st.session_state.get("_admin_via_voice")
        and not st.session_state.get("_admin_verified")
        and _ADMIN_PAGE is not None
    ):
        st.switch_page(_ADMIN_PAGE)

    init_state()
    handle_google_login_if_returned()
    restore_local_session()

    _debug_enabled = bool(os.environ.get("CHEFEAR_DEBUG"))

    _debug_screen = st.query_params.get("debug_screen") if _debug_enabled else None
    if _debug_screen and _debug_screen not in SCREENS and not st.session_state.get("_debug_jumped"):
        print(f"[app] 잘못된 ?debug_screen={_debug_screen!r} 무시(SCREENS에 없음)", flush=True)
    elif _debug_screen and not st.session_state.get("_debug_jumped"):
        st.session_state["_debug_jumped"] = True
        _debug_fill_fake_state(_debug_screen)

    if _debug_enabled and st.query_params.get("debug_panel") == "1":
        _dump_dir = Path(__file__).resolve().parent.parent / "ui" / "assets" / "_mic_debug_dumps"
        _files = sorted(_dump_dir.glob("*.m4a")) if _dump_dir.exists() else []
        with st.expander(f"🎙️ 디버그 음성 주입 ({len(_files)}개)", expanded=True):
            _cols = st.columns(3)
            for _i, _f in enumerate(_files):
                with _cols[_i % 3]:
                    if st.button(_f.stem, key=f"debug_voice_btn_{_f.stem}", use_container_width=True):
                        from stt.infer import stt_transcribe

                        _text = stt_transcribe(str(_f))
                        st.session_state["_debug_voice_pending_text"] = _text
                        print(f"[DEBUG_VOICE] button {_f.stem!r} -> STT: {_text!r}", flush=True)

        with st.expander("🧭 화면 점프 (가짜 데이터)", expanded=True):
            st.caption("등록/조리 화면으로 바로 이동. 가짜 recipe_view/registration을 채워 렌더링만 확인용.")
            _jcols = st.columns(3)
            for _j, (_label, _scr) in enumerate(_DEBUG_JUMP_SCREENS):
                with _jcols[_j % 3]:
                    if st.button(_label, key=f"debug_jump_{_scr}", use_container_width=True):
                        _debug_fill_fake_state(_scr)
                        print(f"[DEBUG_JUMP] -> {_scr}", flush=True)
                        st.rerun()

    st.session_state._active_recipe_box["recipe_id"] = st.session_state.pipeline_session.get("current_recipe_id")
    _start_model_warmup()
    inject_css()
    _current_user = st.session_state.get("current_user")
    if st.session_state.screen == "start":
        _brand_clicked = render_brand(show_login=True, username=_current_user.username if _current_user else None)
    else:
        render_brand()
        _brand_clicked = False
    if _brand_clicked:
        if _current_user:
            # 로그인 아이콘이 아이디로 바뀐 뒤 다시 누르면 마이레시피로 이동한다
            # (기존엔 여기서 바로 로그아웃했으나, 로그아웃 버튼은 my_recipes 화면
            # 안으로 옮겼다 — screens/my_recipes.py::screen_my_recipes() 참고).
            goto("my_recipes")
        else:
            goto("login")


    screen = st.session_state.screen
    _screen_slot = st.empty()
    with _screen_slot.container(key=f"screen_{screen}"):
        SCREENS[screen]()
        for _ in range(_SCREEN_TRAILING_PAD):
            st.empty()

    # render_screen_cleanup()은 이제 보조 역할 — 시각 잔상은 위 st.empty()가 막고,
    # 여기서는 다른 화면 소속 <audio> 정지(ruleStaleAudio)와 브라우저 수준 에러 토스트만
    # 담당한다. theme.py::render_screen_cleanup() 문서 참고.
    render_screen_cleanup(screen)

    def _next_text(*args, **kwargs) -> str | None:
        pending = st.session_state.pop("_debug_voice_pending_text", None)
        if pending is not None:
            return pending
        return listen(*args, **kwargs)

    # 화면별로 원래 각 screen_*() 함수 안에서 하던 listen()/listen_background_only()
    # 호출과 그 결과 처리를 그대로 여기로 옮겼다 — 파라미터(show_mic/show_text_fallback/
    # key_prefix)와 처리 로직은 원래 화면 파일에 있던 것과 동일하다.
    if screen == "start":
        text = _next_text("start", show_mic=False, show_text_fallback=False)
        if text:
            process_utterance(text)
    elif screen == "recipe_confirm":
        text = _next_text("recipe_confirm", show_mic=False, show_text_fallback=False)
        if text:
            handle_recipe_confirm(text)
    elif screen == "cooking_step":
        text = _next_text("cooking_step", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "cooking_complete":
        text = _next_text("cooking_complete", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "unclassified":
        text = _next_text("unclassified")
        if text:
            process_utterance(text)
    elif screen == "register_dish_name":
        text = _next_text("register_dish_name", show_mic=False)
        if text:
            handle_register_dish_name(text)
    elif screen == "register_ingredients":
        listen("register_ingredients", listen_for_speech=False, show_text_fallback=False)
    elif screen == "register_steps":
        listen("register_steps", show_text_fallback=False)
    elif screen == "complete":
        text = _next_text("complete", show_mic=False)
        if text:
            process_utterance(text)
    elif screen in ("login", "signup"):
        pass
    elif screen in ("my_recipes", "edit_recipe"):
        listen(screen, listen_for_speech=False, show_text_fallback=False)


def _run_with_error_notice(label: str, fn) -> None:
    """"예방 차원으로 다른 에러들에 대해서도 셋팅"(오늘 밤 RTCPeerConnection
    브라우저 예외에 이어, 파이썬 쪽에서 예상 못한 예외가 나는 경우까지 포함). main/admin
    화면 안 곳곳의 개별 try/except(TTS 합성 실패, DB 조회 실패 등, speak 등 각자
    st.warning 문구를 이미 갖고 있음)는 그대로 두고 건드리지 않는다 — 저것들은 그
    자리에서 뭐가 실패했는지 알려주는 게 사용자에게 더 유용하다. 이건 그 어디서도 안
    잡힌 완전히 예상 못한 예외(코드 버그, 새 화면 추가 시 놓친 분기 등)의 최후
    """
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — 의도적으로 넓게 잡는 최후 방어선(위 문서 참고)
        import traceback

        print(f"[app] {label} 예상 못한 예외: {exc!r}", flush=True)
        traceback.print_exc()
        render_error_notice()


def _exit_admin() -> None:
    """관리자 페이지에서 메인으로 빠져나온다 — 음성 트리거 플래그와 인증 상태를 지운다.
    (IP 기준 시도 제한은 admin_auth 모듈 메모리라 여기서 안 건드린다 — 나가도 잠금은 유지.)"""
    for k in ("_admin_via_voice", "_admin_verified", "_admin_challenge", "_admin_warm_started"):
        st.session_state.pop(k, None)
    if _MAIN_PAGE is not None:
        access_token = os.environ.get("ACCESS_GATE_TOKEN", "").strip()
        st.switch_page(_MAIN_PAGE, query_params={"key": access_token} if access_token else None)


def _run_admin_page() -> None:
    # 1차 = ?admin_key= 토큰(_admin_gate_ok) 또는 음성 트리거 플래그(_admin_via_voice).
    # 2차 = 화자검증(랜덤 단어 챌린지). 통과 세션 플래그가 서면 Phase 1 승인 목록을
    # 보여준다(docs/specs/admin_voice_2fa.md). 새로고침하면 세션이 날아가 다시 인증(EC-10).
    from ui.screens.admin import render_admin
    from ui.screens.admin_auth import render_voice_challenge

    inject_css()
    if st.button("← 메인으로", key="admin_exit"):
        _exit_admin()
    if not st.session_state.get("_admin_verified"):
        render_voice_challenge()
        return
    # 음성 트리거(_admin_via_voice)만으로는 챌린지 화면까지만 도달하고, 실제 승인/
    # 삭제 목록은 ?admin_key= 토큰까지 있어야 보인다 — 토큰(1차)+화자검증(2차) 둘 다
    # 통과해야 진입(admin_voice_2fa.md 확정 사항). 토큰 없으면 여기서 fail-closed.
    if not _admin_gate_ok():
        st.warning("관리자 토큰이 확인되지 않았습니다.")
        return
    st.caption(f"관리자: {st.session_state['_admin_verified']}")
    render_admin()


def _run_enroll_page() -> None:
    from ui.screens.admin_enroll import render_admin_enroll

    inject_css()
    render_admin_enroll()


if __name__ == "__main__":
    st.set_page_config(page_title="ChefEar", page_icon="🍲", layout="centered", initial_sidebar_state="collapsed")

    _MAIN_PAGE = st.Page(lambda: _run_with_error_notice("main()", main), title="ChefEar", default=True)
    _pages = [_MAIN_PAGE]
    # 토큰(?admin_key=)이 맞거나, 음성 트리거("관리자 페이지 접근할게요")로 세션 플래그가
    # 서면 관리자 Page를 등록한다. 둘 다 아니면 목록에 아예 안 넣어 /admin이 "없는
    # 페이지"로 보인다(존재를 숨김). 등록되더라도 실제 진입은 화자검증 챌린지가 막는다.
    if _admin_gate_ok() or st.session_state.get("_admin_via_voice"):
        _ADMIN_PAGE = st.Page(
            lambda: _run_with_error_notice("admin", _run_admin_page), title="관리자", url_path="admin"
        )
        _pages.append(_ADMIN_PAGE)
    if _enroll_gate_ok():
        # 관리자 목소리 등록 화면(docs/specs/admin_voice_2fa.md). enroll_key 별도 시크릿,
        # 위 admin과 같은 이유로 토큰 안 맞으면 목록에 안 넣는다.
        _pages.append(
            st.Page(lambda: _run_with_error_notice("enroll", _run_enroll_page), title="관리자 등록", url_path="enroll")
        )
    # position="hidden" — 사이드바에 페이지 목록/링크를 노출하지 않는다. 관리자 페이지는
    # URL(?admin_key=<토큰>)을 직접 아는 사람만 접근해야 하므로, 링크로 존재를 드러내면 안 됨.
    st.navigation(_pages, position="hidden").run()
