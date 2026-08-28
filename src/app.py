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
from ui.screens.register import (
    handle_register_dish_name,
    handle_register_intro,
    screen_complete,
    screen_register_dish_name,
    screen_register_ingredients,
    screen_register_intro,
    screen_register_steps,
    screen_unclassified,
)
from ui.session import goto, init_state
from ui.voice_io import listen

load_env()

SCREENS = {
    "start": screen_start,
    "recipe_confirm": screen_recipe_confirm,
    "cooking_step": screen_cooking_step,
    "cooking_complete": screen_cooking_complete,
    "unclassified": screen_unclassified,
    "register_intro": screen_register_intro,
    "register_dish_name": screen_register_dish_name,
    "register_ingredients": screen_register_ingredients,
    "register_steps": screen_register_steps,
    "complete": screen_complete,
}

# 음성 트리거로 관리자 페이지↔메인을 전환할 때 st.switch_page()에 넘길 st.Page 객체.
# __main__ 블록이 Page를 실제로 만들 때 여기에 채운다(main()/_exit_admin()은 읽기만).
_MAIN_PAGE = None
_ADMIN_PAGE = None


def _access_gate_ok() -> bool:
    """랜딩페이지(https://chefear-landingpage.vercel.app) 버튼을 거쳐 ?key=<토큰>이
    붙은 URL로 들어왔는지 확인한다(2026-08-26 요청 — Cloudflare Tunnel로 chefear.store를
    공개해둔 상태에서, 랜딩페이지 버튼을 거치지 않은 직접 URL 접근을 "토큰 붙은 URL"
    방식으로 약하게 막음. 완전한 보안 아님 — 대화 배경은 render_access_blocked() 문서
    참고).

    .env에 ACCESS_GATE_TOKEN이 비어 있으면 게이트 자체를 끈다(로컬 개발/토큰 미설정
    배포가 이것 때문에 막히지 않게 fail-open — orchestration/db.py::get_client()가
    Supabase 자격증명 미설정 시 mock으로 폴백하는 것과 같은 정신). 값이 설정된
    배포에서만 실제로 검사한다.
    """
    expected = os.environ.get("ACCESS_GATE_TOKEN", "").strip()
    if not expected:
        return True
    # 2026-08-28 — 한 번 ?key=로 통과한 세션은 계속 통과로 본다. st.switch_page()로
    # 관리자 페이지에 갔다 오면(음성 트리거/← 메인으로) URL의 ?key=가 떨어져 나가서,
    # 이 가드가 없으면 돌아온 메인 화면이 소개페이지 안내로 막히는 게 실측 확인됐다.
    # ?key= 게이트 자체가 "약한 접근 제한"이라, 세션 지속은 보안 성격을 안 바꾼다.
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

    def _load_dish_names() -> None:
        # 2026-08-26 추가 — "DB에 없는 메뉴를 말하면 로딩바가 엄청 오래 돈다" 리포트로
        # orchestration/db.py::get_client()를 프로세스당 client 하나만 재사용하도록
        # 고쳐서 recipe_search.py::_all_dish_names()/_decomposed_name_map()의
        # @lru_cache가 실제로 히트하게 됐지만(그 전엔 client 객체가 매번 새로 만들어져
        # 캐시가 항상 미스였음), 그래도 "이 프로세스에서 처음" 그 경로를 타는 발화는
        # 여전히 60,282건 전체를 페이지네이션으로 끌어오는 15~25초를 그 자리에서
        # 물고 있다(실측). 다른 모델들처럼 여기서 미리 한 번 데워두면, 실제 사용자가
        # 처음 "없는 메뉴"를 물어봐도 이미 캐시가 채워져 있어 안 기다린다.
        from orchestration.db import get_client
        from orchestration.recipe_search import _all_dish_names, _decomposed_name_map

        client = get_client()
        _all_dish_names(client)
        _decomposed_name_map(client)

    def _run() -> None:
        from llm.infer import load_llm
        from stt.infer import load_ct2_model
        from tts.infer import load_tts_model

        # 2026-08-28 — 로드 순서를 STT -> TTS -> LLM -> 요리명 목록으로 조정("Queue
        # overflow" 대응 C). 해피패스(조회 성공)에서 speak()의 첫 TTS 합성은 사용자가
        # 첫 발화를 마치는 시점에 필요한데, 예전 순서(TTS가 3번째, 그것도 15~25초
        # 걸리는 "요리명 목록" 앞)로는 첫 조회 때 TTS 모델(약 4GB)이 아직 로딩 중이라
        # speak()가 그 콜드 로드를 백그라운드 스레드에서 물게 되고, 그동안 _drain_mic_while()
        # 이 GIL을 제때 못 얻어 마이크 큐가 넘쳤다. TTS를 STT 바로 뒤로 당겨 첫 발화
        # 전에 데워둔다. LLM(extract_intent_llm)은 조회 경로에서 TTS보다 먼저 쓰이지만
        # 그 구간은 _compute()가 _drain_mic_while() 우산 안에서 돌려서 콜드 로드가
        # overflow를 안 만든다 — 그래서 TTS 다음으로 뒀다. "요리명 목록"은 미등록/
        # 퍼지 매칭 경로에서만 쓰여 해피패스 지연과 무관하고 제일 느려서 맨 뒤.
        for name, loader in (
            ("STT", load_ct2_model),
            ("TTS", load_tts_model),
            ("LLM", load_llm),
            ("요리명 목록", _load_dish_names),
        ):
            try:
                loader()
            except Exception as exc:  # noqa: BLE001 — 위 문서 참고, 조용히 넘어감
                print(f"[app] {name} 모델 백그라운드 워밍업 실패: {exc!r}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


def main() -> None:
    # 2026-08-27 — st.set_page_config()는 st.navigation()으로 멀티페이지 구조가 되면서
    # 스크립트 진입점(`if __name__ == "__main__":` 블록)으로 옮겼다 — Streamlit은 이
    # 호출이 스크립트당(페이지별이 아니라) 딱 한 번, 다른 st.* 호출보다 먼저 와야 한다.

    # 2026-08-26 요청 — 랜딩페이지 버튼을 거치지 않은 직접 URL 접근 차단(토큰 붙은 URL
    # 방식, _access_gate_ok()/render_access_blocked() 문서 참고). init_state()보다
    # 먼저 검사해서, 막힌 방문자는 세션 초기화/모델 워밍업/DB 연결을 전혀 안 타고
    # 곧장 안내 화면만 보고 끝난다.
    if not _access_gate_ok():
        inject_css()
        render_access_blocked()
        st.stop()

    # 2026-08-28 — 음성 트리거("관리자 페이지 접근할게요", dispatch._is_admin_trigger())로
    # 세운 플래그. 이 rerun에서 __main__이 관리자 st.Page를 nav에 등록했을 테니, 여기서
    # 그 페이지로 전환한다(옵션 A — 이동만, 실제 인증은 도착 화면 챌린지). 인증까지
    # 끝났으면 반복 전환 안 함.
    if (
        st.session_state.get("_admin_via_voice")
        and not st.session_state.get("_admin_verified")
        and _ADMIN_PAGE is not None
    ):
        st.switch_page(_ADMIN_PAGE)

    init_state()

    # 2026-08-28 — 디버그 진입로(?debug_screen / ?debug_panel)는 .env의 CHEFEAR_DEBUG가
    # 설정된 경우에만 활성화한다. 예전엔 프로덕션에서도 항상 켜져 있어서(접근 게이트만
    # 통과하면) 임의 화면 점프 + 가짜 recipe_view 주입이 가능했다(리뷰 지적). 배포
    # .env엔 이 변수를 넣지 않는다 — 로컬 개발/QA에서만 켠다.
    _debug_enabled = bool(os.environ.get("CHEFEAR_DEBUG"))

    # 2026-08-25 임시 디버그 진입로 — 화면 전환 잔상을 음성 없이(버튼/URL만으로) 재현해
    # 보기 위해 넣음. URL에 ?debug_screen=cooking_complete 같은 쿼리 파라미터를 붙이면
    # start/recipe_confirm(음성 전용, 버튼도 텍스트 입력도 없어서 우회 불가)을 건너뛰고
    # 바로 그 화면으로 점프한다 — cooking_complete로 렌더링되는 데 필요한 최소한의
    # recipe_view/pipeline_session만 가짜로 채운다.
    _debug_screen = st.query_params.get("debug_screen") if _debug_enabled else None
    # 2026-08-26 — /code-review 발견: SCREENS에 없는 값(오타 등)을 검증 없이 그대로
    # session_state.screen에 넣으면, 아래 SCREENS[screen]() 호출이 KeyError로 죽는다.
    # 게다가 바로 다음 줄에서 _debug_jumped를 이미 True로 찍어놔서, 다음 rerun부터는
    # 이 if 블록 자체를 다시 안 타 — 잘못된 screen 값이 세션에 영구히 박힌 채 매번
    # KeyError로 죽는 상태에 갇힌다(브라우저 탭을 새로 열어야만 벗어날 수 있었음).
    # SCREENS에 있는 값일 때만 점프하도록 막는다.
    if _debug_screen and _debug_screen not in SCREENS and not st.session_state.get("_debug_jumped"):
        print(f"[app] 잘못된 ?debug_screen={_debug_screen!r} 무시(SCREENS에 없음)", flush=True)
    elif _debug_screen and not st.session_state.get("_debug_jumped"):
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

    # voice_io.prefetch_remaining_steps_audio()의 백그라운드 스레드가 참조하는
    # "지금 활성 레시피" 표시를 매 rerun마다 최신 상태로 맞춘다(2026-08-22 요청) — 사용자가
    # 처음 화면으로 돌아가 pipeline_session이 리셋되면, 이 값도 즉시 바뀌어서 버려진
    # 레시피의 백그라운드 합성이 다음 단계 진입 전에 스스로 멈춘다.
    st.session_state._active_recipe_box["recipe_id"] = st.session_state.pipeline_session.get("current_recipe_id")
    _start_model_warmup()
    inject_css()
    # 2026-08-27 — 일반 사용자 로그인/회원가입/마이레시피를 전부 없앴다(계정 시스템
    # 제거 결정). 로그인 버튼도 같이 없앤다 — 관리자 접근은 별도 게이트(admin_recipe_
    # approval.md)로 이동.
    render_brand()

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
    elif screen == "register_intro":
        text = _next_text("register_intro", show_mic=False)
        if text:
            handle_register_intro(text)
    elif screen == "register_dish_name":
        text = _next_text("register_dish_name", show_mic=False)
        if text:
            handle_register_dish_name(text)
    elif screen == "register_ingredients":
        # 2026-08-26 재요청 — 민감/집중 입력 화면이라 음성 오인식으로 갑자기 화면이
        # 바뀌는 걸 원치 않아서 "처음"/"취소"까지 포함해 음성에 완전히 반응 안 하게 했다.
        # 2026-08-28 요청 — 그동안은 listen()을 일반 모드로 불러서 마이크로 계속 듣고
        # STT까지 돌린 뒤 반환값만 버렸는데(GPU 낭비 + "Queue overflow"), 이 화면은
        # 애초에 음성으로 처리할 게 없다. listen_for_speech=False로 webrtc 연결(상시
        # 마이크)은 그대로 살려두되(마이크 재협상은 절대 유발하지 않음) VAD/STT 루프만
        # 건너뛴다 — 프레임은 계속 드레인해서 큐는 안 넘친다.
        listen("register_ingredients", listen_for_speech=False, show_text_fallback=False)
    elif screen == "register_steps":
        # 2026-08-27 재요청 — register_ingredients와 같은 이유로 "처음"/"취소"까지
        # 포함해서 완전히 무시하도록 통일(기존엔 listen_background_only()로 그 두
        # 단어만 반응했음). listen()은 그대로 불러서 마이크 연결은 살려두고(안 그러면
        # orphan-reset, register_ingredients 위 주석 참고) 반환값만 버린다.
        listen("register_steps", show_text_fallback=False)
    elif screen == "complete":
        text = _next_text("complete", show_mic=False)
        if text:
            process_utterance(text)


def _run_with_error_notice(label: str, fn) -> None:
    """2026-08-26 요청 — "예방 차원으로 다른 에러들에 대해서도 셋팅"(오늘 밤 RTCPeerConnection
    브라우저 예외에 이어, 파이썬 쪽에서 예상 못한 예외가 나는 경우까지 포함). main()/admin
    화면 안 곳곳의 개별 try/except(TTS 합성 실패, DB 조회 실패 등, speak() 등 각자
    st.warning() 문구를 이미 갖고 있음)는 그대로 두고 건드리지 않는다 — 저것들은 그
    자리에서 뭐가 실패했는지 알려주는 게 사용자에게 더 유용하다. 이건 그 어디서도 안
    잡힌 완전히 예상 못한 예외(코드 버그, 새 화면 추가 시 놓친 분기 등)의 최후
    방어선 — Streamlit 기본 동작(빨간 트레이스백을 화면에 그대로 노출)을 대신해서
    render_error_notice()로 사용자에게는 "잠시 후 재시도 해주시길 바랍니다."만
    보여주고, 실제 예외는 서버 콘솔에만 남긴다(EC-05와 같은 정신).
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
        # 2026-08-28 요청 — "← 메인으로"를 누르면 접근 URL 그대로,
        # 즉 https://chefear.store/?key=<ACCESS_GATE_TOKEN> 로 돌아가야 한다.
        # st.switch_page()는 기본적으로 모든 쿼리파라미터를 지우는데(query_params=None),
        # 그러면 복귀한 메인 URL에 ?key=가 없어서 그 상태로 새로고침하면 세션 플래그
        # (_access_ok)까지 날아가 소개페이지 안내로 막힌다(_access_gate_ok() 참고).
        # 토큰을 다시 붙여 넘긴다 — 토큰 미설정 배포는 게이트가 fail-open이라 안 붙인다.
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
    st.caption(f"관리자: {st.session_state['_admin_verified']}")
    render_admin()


def _run_enroll_page() -> None:
    from ui.screens.admin_enroll import render_admin_enroll

    inject_css()
    render_admin_enroll()


if __name__ == "__main__":
    # 2026-08-27 — 관리자 페이지(docs/specs/admin_recipe_approval.md)를 독립 Streamlit
    # 페이지로 분리했다. st.set_page_config()는 st.navigation()보다 먼저, 스크립트당
    # 한 번만 불러야 한다.
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
