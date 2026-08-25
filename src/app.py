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

import threading

import streamlit as st

from orchestration.db import load_env
from theme import inject_css, render_brand, render_screen_cleanup
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


def _start_model_warmup() -> None:
    """STT/LLM/TTS 모델을 백그라운드 스레드에서 미리 로드해둔다.

    2026-08-25 재작성(원래는 `_warm_up_models()`라는 이름으로 main() 안에서 동기/블로킹으로
    세 모델을 다 로드한 뒤에야 화면(마이크 포함)을 그렸다 — "마이크 붙는 속도가 느리다"는
    지적으로 재구성). 상시 마이크(webrtc_streamer())도 이 함수 *뒤에* 있는 화면 렌더링
    단계에서만 처음 호출되므로, 예전 구조에서는 마이크의 WebRTC 협상(SDP offer/answer,
    ICE)이 모델 로딩(콜드 스타트 시 최대 30초+, LLM 최초 다운로드 시엔 수 분)이 다 끝날
    때까지 아예 시작도 못 했다 — 첫 페이지 로드에서 마이크가 늦게 붙는 것처럼 보인
    실제 원인. load_ct2_model()/load_llm()/load_tts_model() 셋 다 이미 자기 안에 이중
    확인 잠금(`_LOAD_LOCK`)을 갖고 있어서(여러 스레드가 동시에 로딩을 시작해도 안전 —
    각 infer.py 파일의 `_LOAD_LOCK` 정의부 주석 참고) 백그라운드에서 미리 불러도, 나중에
    실제 발화 처리 스레드가 같은 함수를 또 불러도 안전하게 합쳐진다(먼저 끝난 쪽이 이김,
    뒤에 온 호출은 곧장 캐시를 돌려받음). 세션당 한 번만 스레드를 띄운다
    (`_warmup_thread_started` 플래그로 중복 시작 방지).

    st.spinner()/st.warning() 같은 st.* API는 ScriptRunContext가 있는 메인 스레드에서만
    안전해서(voice_io.py의 `_synthesize_and_cache()` 등 다른 백그라운드 스레드들과 같은
    이유) 이 함수는 그런 호출을 전혀 안 한다 — 로딩 실패는 print()로만 남기고 조용히
    넘어간다(EC-05 원칙과 같은 정신 — 실패해도 서비스는 계속 뜨고, 실제 그 모델이 필요한
    시점에 각 호출부(speak()/stt_transcribe() 등)가 이미 자기 실패 처리를 하고 있다).
    트레이드오프: 로딩 중이라는 "STT/LLM/TTS 모델 준비 중..." 스피너 문구가 이제 화면에
    안 뜬다 — 대신 화면들이 이미 갖고 있는 "마이크 연결 중..." 표시가 그 자리를 대신한다.
    """
    if st.session_state.get("_warmup_thread_started"):
        return
    st.session_state["_warmup_thread_started"] = True

    def _run() -> None:
        from llm.infer import load_llm
        from stt.infer import load_ct2_model
        from tts.infer import load_tts_model

        for name, loader in (("STT", load_ct2_model), ("LLM", load_llm), ("TTS", load_tts_model)):
            try:
                loader()
            except Exception as exc:  # noqa: BLE001 — 위 문서 참고, 조용히 넘어감
                print(f"[app] {name} 모델 백그라운드 워밍업 실패: {exc!r}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


def main() -> None:
    st.set_page_config(page_title="ChefEar", page_icon="🍲", layout="centered", initial_sidebar_state="collapsed")
    init_state()

    # 2026-08-25 임시 디버그 진입로 — 화면 전환 잔상을 음성 없이(버튼/URL만으로) 재현해
    # 보기 위해 넣음. URL에 ?debug_screen=cooking_complete 같은 쿼리 파라미터를 붙이면
    # start/recipe_confirm(음성 전용, 버튼도 텍스트 입력도 없어서 우회 불가)을 건너뛰고
    # 바로 그 화면으로 점프한다 — cooking_complete로 렌더링되는 데 필요한 최소한의
    # recipe_view/pipeline_session만 가짜로 채운다. 검증 끝나면 지울 것 — 실제 사용자는
    # 이 파라미터를 몰라도(안 붙이면) 평소와 완전히 동일하게 동작한다.
    _debug_screen = st.query_params.get("debug_screen")
    if _debug_screen and not st.session_state.get("_debug_jumped"):
        st.session_state["_debug_jumped"] = True
        st.session_state.screen = _debug_screen
        # recipe_id는 실제 UUID 형식이어야 한다 — "debug-recipe" 같은 임의 문자열을
        # 쓰면 manual_fallback()/advance_step()이 부르는 Supabase 쿼리가
        # "invalid input syntax for type uuid"로 그대로 크래시한다(2026-08-25 실측,
        # cooking_step에서 "다음" 버튼 클릭 시 재현). 존재하지 않는 UUID는 쿼리 자체는
        # 통과하고 결과만 없는(None) 정상 흐름으로 처리된다.
        st.session_state.recipe_view = {
            "recipe_id": "00000000-0000-0000-0000-000000000001",
            "dish_name": "디버그용 테스트 요리",
            "ingredients_raw": "테스트 재료 1개",
            "steps": [{"step_number": 1, "text": "테스트 1단계"}],
        }
        st.session_state.pipeline_session["current_recipe_id"] = "00000000-0000-0000-0000-000000000001"
        st.session_state.pipeline_session["step_number"] = 1
        # register_ingredients/register_steps는 pipeline_session["registration"]이 없으면
        # 곧장 register_intro로 튕겨나간다(screen_register_ingredients() 상단 가드) — 그
        # 화면으로 바로 점프해서 잔상을 테스트하려면 이것도 최소한으로 채워둬야 한다
        # (registration.py::register_recipe()가 만드는 것과 같은 구조).
        if _debug_screen in ("register_ingredients", "register_steps"):
            st.session_state.pipeline_session["registration"] = {
                "dish_name": "디버그용 테스트 요리",
                "ingredients": ["테스트 재료 1개"],
                "instructions": ["테스트 1단계"],
            }
        st.session_state.pending_dish_name = "디버그용 테스트 요리"

    # 2026-08-25 임시 디버그 음성 패널 — 처음엔 ?debug_voice=<파일명>을 URL에 붙이는
    # 방식으로 만들었는데, 페이지를 새로고침(URL 이동)할 때마다 마이크(WebRTC) 협상
    # 초기 몇 초 구간과 겹쳐서 웹소켓이 끊기는 문제가 실측 확인됐다(연결 이미 안정된
    # 뒤에도 화면이 브랜드 로고만 뜨고 빈 채로 멈춤, 콘솔에 "Cannot send rerun
    # backMessage when disconnected from server" 반복) — 새로고침 자체가 원인이라
    # ?debug_panel=1로 페이지 안에 버튼만 한 번 띄우고, 이후 주입은 그 버튼 클릭(=
    # 새로고침 없는 일반 rerun)으로만 하도록 바꿨다. ui/assets/_mic_debug_dumps/에
    # 발화 내용 그대로 이름 붙인 녹음 파일을 두면 그 파일명이 버튼 라벨이 된다 —
    # 실제 stt_transcribe()에 태워서 나온 텍스트를 이번 턴의 발화로 취급한다(마이크만
    # 안 쓸 뿐 STT/의도분류/화면전환까지 실제 파이프라인 그대로 탄다). 검증 끝나면
    # _debug_screen과 함께 지울 것.
    if st.query_params.get("debug_panel") == "1":
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

    # voice_io.prefetch_remaining_steps_audio()의 백그라운드 스레드가 참조하는
    # "지금 활성 레시피" 표시를 매 rerun마다 최신 상태로 맞춘다(2026-08-22 요청) — 사용자가
    # 다른 레시피로 넘어가거나(재료대체 포함) 처음 화면으로 돌아가 pipeline_session이
    # 리셋되면, 이 값도 즉시 바뀌어서 버려진 레시피의 백그라운드 합성이 다음 단계
    # 진입 전에 스스로 멈춘다.
    st.session_state._active_recipe_box["recipe_id"] = st.session_state.pipeline_session.get("current_recipe_id")
    # 새로고침해도 로그인이 풀리지 않게, 저장해둔 로그인 쿠키로 세션을 복원한다
    # (2026-08-22 요청) - _start_model_warmup()보다 먼저 해야 화면이 뜨자마자 바로
    # 로그인 상태로 보인다.
    restore_login_from_cookie()
    _start_model_warmup()
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

    # 2026-08-25 — 위 컨테이너 key 픽스로도 못 잡는 잔상(버튼/텍스트 잔상, 심지어
    # cooking_complete의 완료 멘트가 start로 넘어간 뒤에도 다시 재생되는 경우까지 실측
    # 확인)에 대한 최후 수단 — 브라우저에서 직접 이전 화면의 컨테이너를 찾아 지운다.
    # theme.py::render_screen_cleanup() 문서 참고. 마이크(webrtc_streamer)는 완전히
    # 격리된 별도 iframe에 살아서 이 스크립트가 절대 못 건드린다.
    render_screen_cleanup(screen)

    def _next_text(*args, **kwargs) -> str | None:
        pending = st.session_state.pop("_debug_voice_pending_text", None)
        if pending is not None:
            return pending
        return listen(*args, **kwargs)

    # 화면별로 원래 각 screen_*() 함수 안에서 하던 listen()/listen_background_only()
    # 호출과 그 결과 처리를 그대로 여기로 옮겼다 — 파라미터(show_mic/show_text_fallback/
    # key_prefix)와 처리 로직은 원래 화면 파일에 있던 것과 동일하다. login/my_recipes/
    # edit_recipe는 원래도 마이크를 안 썼던 화면이라 여기서도 아무것도 안 부른다(다른
    # 화면으로 넘어가면 다음 실행에서 다시 마이크가 붙는다).
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
    elif screen == "no_match":
        text = _next_text("no_match", show_mic=False)
        if text:
            process_utterance(text)
    elif screen == "unclassified":
        text = _next_text("unclassified")
        if text:
            process_utterance(text)
    elif screen == "register_intro":
        text = _next_text("register_intro", show_mic=False)
        if text:
            handle_register_intro(text)
    elif screen == "register_dish_name":
        text = _next_text("register_dish_name", show_mic=False)
        if text:
            handle_register_dish_name(text)
    elif screen == "register_ingredients":
        listen_background_only("register_ingredients", cancel_target="register_intro")
    elif screen == "register_steps":
        listen_background_only("register_steps", cancel_target="register_ingredients")
    elif screen == "complete":
        text = _next_text("complete", show_mic=False)
        if text:
            process_utterance(text)


if __name__ == "__main__":
    main()
