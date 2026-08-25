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
from ui.dispatch import listen_background_only, process_utterance
from ui.screens.cooking import (
    handle_recipe_confirm,
    screen_cooking_complete,
    screen_cooking_step,
    screen_recipe_confirm,
    screen_start,
)
from ui.screens.my_recipes import screen_edit_recipe, screen_login, screen_my_recipes
from ui.screens.register import (
    handle_register_dish_name,
    handle_register_intro,
    screen_complete,
    screen_no_match,
    screen_register_dish_name,
    screen_register_ingredients,
    screen_register_intro,
    screen_register_steps,
    screen_unclassified,
)
from ui.session import goto, init_state, restore_login_from_cookie
from ui.voice_io import listen

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

    # 2026-08-25 — GitHub streamlit/streamlit#14404("BUG: Stale widgets from previous
    # page runs are not removed when a spinner is later invoked", 1.55.0 기준 아직 미해결)
    # 조사 결과 추가 — 이 함수는 매 rerun(사용자 조작마다)마다 호출되는데, 안의
    # load_*_model() 세 개가 이미 로드된 뒤엔 즉시 반환하더라도 st.spinner() 자체는
    # 매번 새로 mount/unmount됐다. 이 이슈가 정확히 "스피너가 열렸다 닫히는 것" 자체가
    # 같은 위치의 다른 엘리먼트를 정리 못 하게 만드는 패턴이라(재현 조건: 위젯 변경 후
    # 스피너가 있는 화면으로 복귀), 화면 전환마다 반복되는 "화면 전환 잔상" 리포트와
    # 메커니즘이 겹칠 가능성이 있다. 최초 1회(진짜 로딩이 필요할 때)만 스피너를 열고,
    # 이미 로드된 뒤의 재실행에서는 스피너 컨텍스트 자체를 아예 안 만든다 — 함수 호출은
    # 그대로 해서(즉시 반환) 캐시 재사용 안전성은 안 건드린다.
    already_warmed = st.session_state.get("_models_warmed", False)

    def _load_with_optional_spinner(label: str, loader, warn_prefix: str) -> None:
        if already_warmed:
            try:
                loader()
            except Exception as exc:  # noqa: BLE001 — EC-05, 화면은 계속 뜨게 함
                st.warning(f"{warn_prefix}: {exc}")
            return
        with st.spinner(label):
            try:
                loader()
            except Exception as exc:  # noqa: BLE001
                st.warning(f"{warn_prefix}: {exc}")

    _load_with_optional_spinner(
        "STT 모델 준비 중... (최초 1회만, 몇 초 걸릴 수 있음)",
        load_ct2_model,
        "STT 모델을 준비하지 못했어요(음성 인식이 안 될 수 있어요, 텍스트 입력은 계속 됩니다)",
    )
    _load_with_optional_spinner(
        "LLM(EXAONE) 모델 준비 중... (최초 1회는 다운로드로 몇 분 걸릴 수 있음)",
        load_llm,
        "LLM 모델을 준비하지 못했어요(요리명 추출이 안 될 수 있어요)",
    )
    _load_with_optional_spinner(
        "TTS(Qwen3-TTS) 모델 준비 중... (약 17초, 최초 1회만)",
        load_tts_model,
        "TTS 모델을 준비하지 못했어요(음성 응답이 안 나올 수 있어요, 텍스트는 계속 표시돼요)",
    )
    st.session_state["_models_warmed"] = True


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

    # 2026-08-24 — "화면 전체를 st.empty() 슬롯 하나로 감싸서 매번 통째로 교체" 시도는
    # 되돌림(실측: "된장찌개 레시피 알려줘" 인식 후 무반응/회색 화면으로 멈추는 새 증상
    # 재현). 상시 마이크(webrtc_streamer, _run_mic_loop() 내부)가 이 SCREENS[...]() 호출
    # 트리 안에서 그려지는데, 그 부모 컨테이너가 매 rerun마다 새로 생성되는 st.empty()로
    # 바뀌면서 프론트엔드 쪽 컴포넌트 정체성(=WebRTC 연결)이 흔들린 것으로 보인다 —
    # 잔상보다 마이크 연결이 더 심각한 문제라 이 방향은 포기.

    # 2026-08-24 — "화면 전환 잔상"(예: register_intro에서 "처음으로" 발화 후 시작
    # 화면과 겹쳐 보임, 여러 화면을 거칠수록 계속 쌓이는 전반적인 문제) 리포트 조사 결과,
    # 이 프로젝트만의 버그가 아니라 Streamlit 자체의 확인된 미해결 버그였다(GitHub
    # streamlit/streamlit#8360 "Stale widgets fill screen after script reruns", P2로
    # Streamlit 팀이 직접 확인). 원인: 스크립트 재실행이 직전 실행보다 이 위치(BlockNode)의
    # 엘리먼트 개수가 "줄어들면", 프론트엔드가 위젯 ID를 재사용하면서 React key가
    # 충돌하고(`Block.tsx`의 getElementWidgetID 기반 key 할당 방식이 원인), 그 결과 직전
    # 실행의 "남는" 엘리먼트가 안 지워지고 화면에 그대로 남는다.
    #
    # 첫 시도(고정 개수 st.empty() 패딩)는 실측으로 효과가 없었다 — SCREENS[...]() 뒤에
    # 매번 같은 개수(60개)를 더해봐야, 화면마다 원래 그리는 엘리먼트 개수 자체가 다르므로
    # (예: no_match는 채팅 카드+캡션+버튼 2개+입력칸, start는 제목+마이크뿐) 두 화면
    # 총합의 "차이"는 그대로 남는다 — 상수를 양쪽에 똑같이 더해도 그 차이가 없어지지
    # 않는다("된장찌개" -> "처음" 재현으로 실측 확인, no_match 잔상 그대로 남음).
    #
    # 대신 화면마다 다른 key의 st.container()로 감싼다 — 화면이 바뀌면 완전히 다른
    # key(다른 프론트엔드 엘리먼트 트리 네임스페이스)가 되므로, 애초에 이전 화면 위젯과
    # 같은 자리를 두고 ID를 재사용/충돌시킬 일 자체가 없어진다(위 "엘리먼트 개수가
    # 줄어드는" 조건 자체를 회피).
    #
    # 2026-08-25 실측 리포트 — 처음엔 "상시 마이크는 이 컨테이너 밖에서 그려지니 무관하다"고
    # 적어뒀는데 틀렸다. 실제로는 각 screen_*() 함수가 자기 본문 끝에서 listen()을 직접
    # 불렀고, 그 listen()이(= webrtc_streamer()가) 바로 이 컨테이너 *안에서* 그려지고
    # 있었다 — 그래서 화면이 바뀔 때마다(=컨테이너 key가 바뀔 때마다) 마이크 컴포넌트까지
    # 통째로 재마운트되면서 매번 새로 연결됐다(WRTCDBG 로그로 chefear_mic_0 -> _7까지
    # 세대가 계속 올라가는 것 확인, "Queue overflow" 반복 + 그 직후 발화가 씹히는 리포트로
    # 이어짐). 그래서 listen()/listen_background_only() 호출 자체를 각 screen_*() 함수
    # 밖으로 빼서, 이 컨테이너가 닫힌 *뒤에* 화면과 무관하게 항상 같은 자리에서 부르도록
    # 옮겼다(각 screen_*() 함수 상단 주석 참고) — 이제서야 진짜로 이 컨테이너 변경과
    # 무관해졌다.
    screen = st.session_state.screen
    with st.container(key=f"screen_{screen}"):
        SCREENS[screen]()

    # 화면별로 원래 각 screen_*() 함수 안에서 하던 listen()/listen_background_only()
    # 호출과 그 결과 처리를 그대로 여기로 옮겼다 — 파라미터(show_mic/show_text_fallback/
    # key_prefix)와 처리 로직은 원래 화면 파일에 있던 것과 동일하다. login/my_recipes/
    # edit_recipe는 원래도 마이크를 안 썼던 화면이라 여기서도 아무것도 안 부른다(다른
    # 화면으로 넘어가면 다음 실행에서 다시 마이크가 붙는다).
    if screen == "start":
        text = listen("start", show_mic=False, show_text_fallback=False)
        if text:
            process_utterance(text)
    elif screen == "recipe_confirm":
        text = listen("recipe_confirm", show_mic=False, show_text_fallback=False)
        if text:
            handle_recipe_confirm(text)
    elif screen == "cooking_step":
        text = listen("cooking_step", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "cooking_complete":
        text = listen("cooking_complete", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "no_match":
        text = listen("no_match", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "unclassified":
        text = listen("unclassified")
        if text:
            process_utterance(text)
    elif screen == "register_intro":
        text = listen("register_intro", show_mic=False)
        if text:
            handle_register_intro(text)
    elif screen == "register_dish_name":
        text = listen("register_dish_name", show_mic=False)
        if text:
            handle_register_dish_name(text)
    elif screen == "register_ingredients":
        listen_background_only("register_ingredients", cancel_target="register_intro")
    elif screen == "register_steps":
        listen_background_only("register_steps", cancel_target="register_ingredients")
    elif screen == "complete":
        text = listen("complete", show_mic=False)
        if text:
            process_utterance(text)


if __name__ == "__main__":
    main()
