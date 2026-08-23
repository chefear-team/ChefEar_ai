"""ChefEar 실제 서비스 엔트리포인트 (HF Spaces 배포 대상, `docs/specs/app_e2e.md`).

마이크 입력 -> STT(`stt.infer.stt_transcribe`) -> 오케스트레이션(`orchestration.pipeline.
handle_utterance`) -> TTS(`tts.infer.tts_synthesize`) 재생까지 한 화면 루프로 엮는다.
화면 컴포넌트(CSS/아이콘/카드 등)는 `ui/theme.py`를 그대로 재사용한다(PRD 3.3 "핵심 기능
완료 후 여유 시간에 다듬는다" — 화면 디자인은 새로 만들지 않음, Out of Scope).

`ui/streamlit_screens/*.py`(mock 프로토타입)는 그대로 재사용하지 않는다 — 그 화면들은
버튼마다 시나리오를 하드코딩해서 요리명/재료명 추출 문제를 우회했는데(예: "바지락 넣어도
돼?" 버튼이 requested_ingredient=["바지락"]을 코드에 미리 박아둠), 실제 자유발화는 그
우회가 불가능하다. 그래서 이 파일은 화면 흐름을 직접 다시 짜되, 시각 컴포넌트만 theme.py에서
가져다 쓴다.

2026-08-22: 화면 컴포넌트화 — 세션 상태/STT-TTS 연결/발화 디스패처/화면 함수들을
`src/ui/`(session.py, voice_io.py, recipe_view.py, dispatch.py, screens/*.py)로 옮기고
이 파일은 그것들을 조립하는 엔트리포인트만 남겼다. 주의: 이 `ui` 패키지(`src/ui/`, `src`가
sys.path에 있어서 `ui.session`처럼 import됨)는 아래에서 `sys.path.insert(0, .../"ui")`로
따로 얹는 최상위 `ui/`(theme.py 등, `from theme import ...`로 씀) 폴더와 이름은 같지만
서로 다른 경로다 — 각 화면 모듈의 상단 주석에도 같은 안내가 있다.

실행: streamlit run src/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "ui"))

import streamlit as st

from orchestration.db import load_env
from theme import inject_css, render_brand
from ui.screens.cooking import screen_cooking_complete, screen_cooking_step, screen_recipe_confirm, screen_start
from ui.screens.my_recipes import screen_edit_recipe, screen_login, screen_my_recipes
from ui.screens.register import (
    screen_complete,
    screen_no_match,
    screen_register_dish_name,
    screen_register_ingredients,
    screen_register_intro,
    screen_register_steps,
    screen_unclassified,
)
from ui.session import goto, init_state, restore_login_from_cookie

load_env()

SCREENS = {
    "start": screen_start,
    "recipe_confirm": screen_recipe_confirm,
    "cooking_step": screen_cooking_step,
    "cooking_complete": screen_cooking_complete,
    "no_match": screen_no_match,
    "unclassified": screen_unclassified,
    "register_intro": screen_register_intro,
    "register_dish_name": screen_register_dish_name,
    "register_ingredients": screen_register_ingredients,
    "register_steps": screen_register_steps,
    "complete": screen_complete,
    "login": screen_login,
    "my_recipes": screen_my_recipes,
    "edit_recipe": screen_edit_recipe,
}


def _warm_up_models() -> None:
    """STT/LLM/TTS 모델을 화면이 뜨는 시점에 미리 로드해둔다(`tests/test_ui.py`와 동일 패턴).

    셋 다 첫 로딩 비용이 있어서(원인은 서로 다름, 아래 참고) 미리 안 해두면 사용자가
    실제로 말을 걸거나("start" 화면 listen()) 첫 응답을 들을 때(speak()) 그 비용을
    그대로 보게 된다 — speak()/listen()/process_utterance()가 stt.infer.stt_transcribe,
    tts.infer.tts_synthesize, orchestration.entity_extract_llm.extract_dish_name_llm을
    그 자리에서 lazy import해서 쓰기 때문이다. load_ct2_model()/load_llm()/
    load_tts_model() 셋 다 전역 캐시라서(stt/infer.py의 _ct2_model, llm/infer.py의
    _model, tts/infer.py의 전역 캐시) 이미 로드됐으면 즉시 반환 — 매 rerun(사용자
    조작)마다 이 함수를 다시 호출해도 안전하고 빠르다.

    STT: 처음엔 "CUDA 초기화가 느리다"고 짐작했으나(2026-08-20), 실측해보니 GPU/CPU
    사용률이 로딩 내내 0%였다 — 프로젝트 폴더가 네트워크 공유 드라이브(CIFS, ~9MB/s)에
    있어서 model.bin(778MB) 읽기 자체가 87초 걸렸던 것. .env의 STT_LOCAL_CACHE_DIR로
    로컬 디스크 사본을 우선 읽게 고쳐서 1.2초로 줄었다(`src/stt/infer.py` 참고).
    LLM: EXAONE 가중치는 원래 ~/.cache/huggingface(로컬 디스크)에 캐시되므로 이 문제가
    없다 — 최초 1회 인터넷에서 받는 것만 느리고(수 분), 그다음부턴 13초 정도로 빠르다.
    TTS: LLM과 마찬가지로 ~/.cache/huggingface에서 읽어서 네트워크 드라이브 문제는
    없다 — 7.9GB 모델이라 로딩 자체에 17초 정도 걸리는 게 정상(실측).

    test_ui.py는 파일 하나짜리 수동 테스트 화면이라 로딩 실패 시 그냥 죽어도 되지만,
    이 파일(app.py)은 실제 서비스 화면 전체를 띄우는 진입점이다 — 세 모델 중 하나라도
    준비가 안 돼 있으면(예: 아직 `src/stt/export_ct2.py`로 변환 전이라 CT2 모델이 없는
    개발 환경) 여기서 예외가 그대로 올라가 화면 자체가 뜨지도 못하고 죽는다. speak()가
    이미 따르는 EC-05 원칙(화면 텍스트는 항상 남고, 음성 관련 실패만 사용자에게 알림)과
    똑같이 각 모델 로딩을 개별로 감싸서, 준비 안 된 모델이 있어도 앱은 계속 뜨고 나머지
    기능(텍스트 입력 흐름 등)은 그대로 쓸 수 있게 한다.
    """
    from llm.infer import load_llm
    from stt.infer import load_ct2_model
    from tts.infer import load_tts_model

    with st.spinner("STT 모델 준비 중... (최초 1회만, 몇 초 걸릴 수 있음)"):
        try:
            load_ct2_model()
        except Exception as exc:  # noqa: BLE001 — EC-05, 화면은 계속 뜨게 함
            st.warning(f"STT 모델을 준비하지 못했어요(음성 인식이 안 될 수 있어요, 텍스트 입력은 계속 됩니다): {exc}")

    with st.spinner("LLM(EXAONE) 모델 준비 중... (최초 1회는 다운로드로 몇 분 걸릴 수 있음)"):
        try:
            load_llm()
        except Exception as exc:  # noqa: BLE001
            st.warning(f"LLM 모델을 준비하지 못했어요(요리명 추출이 안 될 수 있어요): {exc}")

    with st.spinner("TTS(Qwen3-TTS) 모델 준비 중... (약 17초, 최초 1회만)"):
        try:
            load_tts_model()
        except Exception as exc:  # noqa: BLE001
            st.warning(f"TTS 모델을 준비하지 못했어요(음성 응답이 안 나올 수 있어요, 텍스트는 계속 표시돼요): {exc}")


def main() -> None:
    st.set_page_config(page_title="ChefEar", page_icon="🍲", layout="centered", initial_sidebar_state="collapsed")
    init_state()
    # voice_io.prefetch_remaining_steps_audio()의 백그라운드 스레드가 참조하는
    # "지금 활성 레시피" 표시를 매 rerun마다 최신 상태로 맞춘다(2026-08-22 요청) — 사용자가
    # 다른 레시피로 넘어가거나(재료대체 포함) 처음 화면으로 돌아가 pipeline_session이
    # 리셋되면, 이 값도 즉시 바뀌어서 버려진 레시피의 백그라운드 합성이 다음 단계
    # 진입 전에 스스로 멈춘다.
    st.session_state._active_recipe_box["recipe_id"] = st.session_state.pipeline_session.get("current_recipe_id")
    # 새로고침해도 로그인이 풀리지 않게, 저장해둔 로그인 쿠키로 세션을 복원한다
    # (2026-08-22 요청) - _warm_up_models()보다 먼저 해야 화면이 뜨자마자 바로
    # 로그인 상태로 보인다.
    restore_login_from_cookie()
    _warm_up_models()
    inject_css()
    # 로그인 아이콘은 start 화면에서만 "ChefEar" 제목과 나란히 보여준다(2026-08-21 요청).
    # 로그인 상태면 아이콘 대신 아이디를 보여주고, 누르면 로그인 화면 대신 마이
    # 레시피로 바로 간다(2026-08-22 요청).
    current_user = st.session_state.current_user
    if render_brand(show_login=(st.session_state.screen == "start"), username=(current_user or {}).get("username")):
        goto("my_recipes" if current_user else "login")
    SCREENS[st.session_state.screen]()


if __name__ == "__main__":
    main()
