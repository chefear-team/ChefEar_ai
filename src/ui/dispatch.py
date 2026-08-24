"""ChefEar 발화 처리(핵심 디스패처) — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

start/cooking_step/unclassified 화면이 공유한다.
"""
from __future__ import annotations

import threading

import streamlit as st

from orchestration.db import get_client
from orchestration.entity_extract import extract_substitution_ingredients
from orchestration.entity_extract_llm import extract_intent_llm
from orchestration.pipeline import handle_utterance, manual_fallback
from ui.recipe_view import refresh_recipe_view
from ui.session import _DEFAULT_PIPELINE_SESSION, get_owner_id, goto
from ui.voice_io import _drain_mic_while, speak

# cooking_step에서 "다음"으로 마지막 단계를 넘어가면(advance_step()이 step=None을
# 돌려줌, orchestration/pipeline.py 참고) 안내만 하고 같은 화면에 머무르는 대신 별도
# 완료 화면(cooking_complete)으로 보낸다(2026-08-22 요청 — "요리가 완성됐어요!" 화면).
# screens/cooking.py의 screen_cooking_complete()가 _render_cached_speech()로 이
# 문구를 다시 찾아 들려줘야 해서 문구 자체를 여기(더 아래 계층)에 두고 화면 쪽에서
# import해 쓴다(screens -> dispatch 의존 방향, ui/README.md 참고).
COOKING_COMPLETE_MESSAGE = "요리가 완성됐어요! 수고하셨어요."

# 2026-08-23 추가 — 상시 마이크가 초기 화면(start) 말고는 어디서도 안 끊기게 되면서
# ("처음으로 돌아가고 싶다"는 요청도 화면을 안 옮긴 채 음성만으로 처리해야 함), "처음"류
# 발화를 classify_intent()/LLM 파이프라인에 태우지 않고 바로 잡아낸다 — 이 파이프라인은
# "조회/진행/재료대체/취소/등록" 같은 요리 도메인 의도만 다루도록 만들어져 있어서 "처음"을
# 넣어봐야 미분류나 엉뚱한 의도로 샐 위험이 있고, "처음으로 돌아가기"는 애초에 의도 분류가
# 필요 없을 만큼 명확한 명령이라 굳이 그 비용(임베딩 유사도 계산 + LLM 호출)을 들일
# 필요도 없다. 화면마다 있던 "처음 화면으로" 버튼(cooking.py screen_cooking_complete 등)과
# 똑같이 pipeline_session/chat_log/recipe_view/pending_dish_name을 초기화한다.
_HOME_WORDS = {"처음", "처음으로", "처음화면", "처음 화면", "처음 화면으로", "메인", "메인 화면", "홈"}


def is_home_word(text: str) -> bool:
    """recipe_confirm/register_intro/register_dish_name처럼 classify_intent()를 안 거치고
    자기 화면 안에서 직접 몇 단어만 확인하는 화면들도 이걸로 "처음" 발화를 똑같이 잡아낼
    수 있게 공개 함수로 둔다.

    2026-08-24 수정 — "처음으로"라고 말했는데 main이 아니라 등록 페이지로 가버리는
    버그 실측 확인. 예전엔 정규화한 발화 전체가 _HOME_WORDS 중 하나와 "정확히" 같아야만
    인정했는데, STT 결과엔 조사/군더더기가 자주 붙는다("어 처음으로 가주세요" 등) — 그러면
    이 함수가 False를 돌려줘서 process_utterance() 맨 위의 조기 처리를 놓치고, 그 발화가
    그대로 classify_intent()/LLM 파이프라인까지 흘러간다. "처음"은 그 파이프라인이 아는
    의도가 아니라서 대개 "미분류"로 떨어지고, dispatch.py의 미분류 분기가 등록 유도
    화면(register_intro)으로 보내버려서 정확히 이 증상(처음으로 말했는데 등록 화면으로
    이동)이 나온다. recipe_confirm 화면의 "처음"/"다시" 로컬 처리가 이미 포함(in) 방식으로
    바뀐 것과 똑같이, 여기도 전체 일치 대신 포함 여부로 완화한다.
    """
    norm = text.strip().rstrip("?!. ")
    return any(word in norm for word in _HOME_WORDS)


def reset_to_start() -> None:
    """"처음 화면으로" 버튼들(cooking.py/register.py)과 동일한 초기화 — 진행 중이던
    레시피/등록/대화 기록을 전부 비우고 start로 보낸다."""
    st.session_state.pipeline_session = dict(_DEFAULT_PIPELINE_SESSION)
    st.session_state.chat_log = []
    st.session_state.recipe_view = None
    st.session_state.pending_dish_name = None
    goto("start")


def listen_background_only(key_prefix: str, *, cancel_target: str) -> None:
    """register_ingredients/register_steps처럼 이미 목적이 뚜렷한 텍스트 폼(재료/순서
    추가칸)을 쓰는 화면용(2026-08-23 추가) — 상시 마이크 연결은 계속 유지하되("start
    화면 말고는 안 끊기게 해달라"는 요청) 자유 발화를 그대로 재료/순서 항목으로 등록해버리면
    안 되므로, "취소"/"처음" 같은 소수의 안전한 단어에만 반응하고 나머지는 무시한다 —
    이 화면들의 진짜 입력 수단은 여전히 화면 자체의 텍스트 폼이다."""
    from ui.voice_io import listen

    text = listen(key_prefix, show_text_fallback=False)
    if not text:
        return
    norm = text.strip().rstrip("?!. ")
    if is_home_word(norm):
        reset_to_start()
    elif norm in ("취소", "취소할래요", "취소해줘"):
        goto(cancel_target)


def process_utterance(text: str) -> None:
    if is_home_word(text):
        reset_to_start()
        return

    st.session_state.chat_log.append(("user", text))

    session = st.session_state.pipeline_session
    client = get_client()

    # 2026-08-23 — extract_intent_llm()/handle_utterance()를 배경 스레드로 돌리고, 메인
    # 스레드는 그동안 voice_io._drain_mic_while()로 마이크 큐를 계속 비운다. speak()의
    # TTS 합성 구간만 이렇게 고쳤을 땐 재현이 계속됐는데(그 요청은 TTS가 이미 캐싱돼 있어
    # 합성 자체를 안 탄 경우였음), 실측(WEBRTC_DEBUG 로그)해보니 이 구간 — classify_intent()가
    # 쓰는 sentence-transformers 임베딩 모델의 최초 GPU 로딩(세션당 1회, 몇 초) + Supabase
    # DB 조회(순차 HTTP 요청 여러 번) — 도 TTS만큼 길게 아무도 안 비우는 블로킹 구간이라
    # 브라우저가 똑같이 연결을 끊었다("DTLS shutdown by remote party"). extract_intent_llm/
    # handle_utterance/extract_substitution_ingredients 셋 다 st.* API를 안 써서(순수 함수,
    # DB client는 인자로 받음) 배경 스레드에서 안전하게 돌릴 수 있다 — session_state
    # 쓰기/goto()(st.rerun())는 이 함수가 결과를 받은 뒤 메인 스레드에서 그대로 처리한다.
    job: dict = {
        "done": False,
        "llm_result": None,
        "requested": None,
        "excluded": None,
        "result": None,
        "value_error": False,
    }

    def _compute(job=job) -> None:
        try:
            job["llm_result"] = extract_intent_llm(text)
            job["requested"], job["excluded"] = extract_substitution_ingredients(text)
            if job["llm_result"]["wants_register"]:
                return
            try:
                job["result"] = handle_utterance(
                    session,
                    text,
                    dish_name=job["llm_result"]["dish_name"],
                    requested_ingredient=job["requested"],
                    excluded_ingredient=job["excluded"],
                    client=client,
                )
            except ValueError:
                job["value_error"] = True
        finally:
            job["done"] = True

    threading.Thread(target=_compute, daemon=True).start()
    _drain_mic_while(job)

    llm_result = job["llm_result"]
    dish_name_guess = llm_result["dish_name"]

    if llm_result["wants_register"]:
        # 2026-08-22 추가 — classify_intent()(임베딩 유사도)가 "등록" 같은 짧은 단일
        # 발화를 "진행"/"이전"과 헷갈려 margin 미충족으로 미분류 처리하는 사례가 실측
        # 확인됐다(기준예문.csv 보강으로 그 구체 사례는 고쳤지만, 임베딩 분류기가 커버
        # 못하는 새 표현은 또 나올 수 있음). classify_intent()를 거치지 않고, LLM이 이미
        # "등록하고 싶다"를 명확히 확인해줬으면 바로 등록으로 보낸다.
        #
        # register_intro(표준 레시피에 없어서 짐작으로 등록을 유도하는 확인 화면)는 안
        # 거친다(2026-08-22 요청) — "등록"이라고 직접 말한 건 시스템의 짐작이 아니라
        # 사용자의 확정된 요청이라 다시 확인받을 필요가 없으므로, register_dish_name
        # (새 레시피 등록 1/3 요리명)으로 바로 보낸다. register_intro의 버튼들이 하던
        # get_owner_id() 호출도 여기서 대신 해줘야 한다(registration.py::register_recipe()가
        # session["owner_id"]를 참조하므로 register_dish_name 진입 전에 채워둬야 함).
        st.session_state.pending_dish_name = dish_name_guess
        get_owner_id()
        goto("register_dish_name")
        return

    if job["value_error"]:
        # 위 배경 스레드의 _compute() 안에서 handle_utterance()가 ValueError를 던진 경우 —
        # "등록"/"정정" 의도인데 registration_step 없이 자유발화로 들어온 경우 등. 서비스를
        # 죽이는 대신 신규 등록으로 안전하게 보낸다. classify_intent()가 이미 "등록"으로
        # 확정 분류한 경우라 위 wants_register 분기와 같은 이유로 register_intro(확인
        # 화면)는 안 거치고 바로 register_dish_name으로 보낸다.
        st.session_state.pending_dish_name = dish_name_guess
        get_owner_id()
        goto("register_dish_name")
        return

    result = job["result"]
    intent = result.get("intent")

    if intent == "미분류":
        # 문장 패턴 분류(classify_intent)가 "조회"로 못 알아들은 경우 전부 여기로 온다 —
        # "분홍코끼리 어떻게 만들어?"처럼 LLM이 요리명을 뽑아낸 경우뿐 아니라, "111"처럼
        # LLM조차 요리명으로 확신 못 해 dish_name_guess가 None인 경우도 포함한다.
        # "잘 이해하지 못했어요"로 되묻고 끝내는 대신, 표준 데이터에 없는 요리일
        # 가능성으로 보고 항상 등록 유도 화면으로 보낸다(2026-08-21 요청) — 등록
        # 화면 자체가 "이 이름 맞아요?"로 다시 확인/수정을 받으므로, 여기서 추측이
        # 틀려도 안전하다. LLM이 아무것도 못 뽑았으면 발화 원문을 그대로 짐작값으로 쓴다.
        st.session_state.pending_dish_name = dish_name_guess or text.strip()
        goto("register_intro")
        return

    if intent == "조회":
        if "message" in result:  # DISH_NOT_FOUND_MESSAGE — 표준 데이터 밖(시나리오 D)
            st.session_state.pending_dish_name = dish_name_guess
            # 2026-08-22 리포트 — 여기서 그리는 재생바가 goto()의 rerun에 곧장 지워져
            # "이전 화면 하단에 떴다 사라짐" 깜빡임만 남긴다(recipe_confirm과 같은 문제).
            # 도착 화면(no_match)이 chat_log의 마지막 ai 메시지를 _render_cached_speech()로
            # 다시 찾아 들려주므로 hidden=True로 화면 없는 자동재생만 한다.
            speak(result["message"], hidden=True)
            goto("no_match")
            return
        refresh_recipe_view(force=True)
        # 위와 같은 이유 — 도착 화면(recipe_confirm)이 chat_log의 마지막 ai 메시지를
        # _render_cached_speech()로 다시 들려준다.
        speak(f'{result["dish_name"]}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?', hidden=True)
        goto("recipe_confirm")
        return

    if intent in ("진행", "재청취", "이전"):
        step = result.get("step")
        if result.get("no_previous"):
            speak("1단계예요, 이전 단계가 없어요.")
            goto("cooking_step")
        elif step is None:
            # 마지막 단계에서 "다음" -> advance_step()이 더 이상 존재하지 않는 단계를
            # 찾다 step=None을 돌려준 경우(2026-08-22 요청) — 안내만 하고 cooking_step에
            # 머무르는 대신 완료 화면으로 보낸다. screen_cooking_complete()가 이 문구를
            # _render_cached_speech()로 다시 찾아 들려주므로 여기서는 hidden=True로 화면
            # 없는 자동재생만 하고, 실제로 들리는 소리는 도착 화면 쪽에 맡긴다(recipe_confirm/
            # register_steps와 같은 패턴).
            speak(COOKING_COMPLETE_MESSAGE, hidden=True)
            goto("cooking_complete")
        else:
            # "다시"는 같은 파일을 다시 재생하는 거라 오디오 콘텐츠 자체가 안 바뀌어서
            # nonce 없이는 iframe이 안 바뀐 걸로 보고 autoplay가 재실행되지 않는다. "다음"/
            # "이전"도 이전에 방문했던 단계로 돌아갈 때(예: 2단계->1단계->2단계) 같은 문제가
            # 재현될 수 있어 실제 단계 오디오를 다시 들려줄 때만 nonce를 올려 항상 새로
            # 로드되게 한다(theme.py render_audio_player() 참고).
            #
            # 2026-08-22 리포트: 이 nonce 증가를 "1단계예요..."/"마지막 단계까지..." 안내
            # 분기 앞에서 공통으로 하고 있었는데, 그 두 경우엔 현재 화면의 단계 번호가
            # 안 바뀐다 — 그런데도 nonce를 올리면 goto()의 rerun 직후 screen_cooking_step()이
            # 화면에 그대로 남아있는 그 단계 카드의 캐시 오디오를 "새로 로드된 것"으로 보고
            # 다시 자동재생해서, 방금 speak()로 들려준 안내 음성과 동시에 겹쳐 들렸다. 실제
            # 단계 오디오를 다시 보여주는 이 분기에서만 nonce를 올려서 막는다.
            #
            # 2026-08-22 추가 리포트: 여기서 그리는 speak()의 재생바도 recipe_confirm과
            # 같은 이유로 goto()의 rerun에 곧장 지워져 "떴다 사라짐" 깜빡임만 남긴다 —
            # 도착 화면(cooking_step)이 render_step_card()로 같은 단계 오디오를 캐시에서
            # 다시 찾아 들려주므로 hidden=True로 화면 없는 자동재생만 한다.
            st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
            speak(
                step["text"],
                recipe_id=session.get("current_recipe_id"),
                step_number=step.get("step_number"),
                hidden=True,
            )
            goto("cooking_step")
        return

    if intent == "재료대체":
        if result.get("match_type") == "none":
            # 위 조회/DISH_NOT_FOUND 분기와 같은 이유(2026-08-22) — no_match가 chat_log의
            # 마지막 ai 메시지를 다시 들려주므로 hidden=True.
            speak(result["message"], hidden=True)
            goto("no_match")
            return
        refresh_recipe_view(force=True)
        speak(f'네, {result["result_dish_name"]}로 바꿔드렸어요. "취소해줘"라고 하면 원래대로 되돌려드려요.')
        goto("cooking_step")
        return

    if intent == "취소":
        if result.get("rolled_back"):
            refresh_recipe_view(force=True)
            speak(f'네, {result["dish_name"]}로 되돌렸어요.')
        else:
            speak("지금은 되돌릴 대체가 없어요.")
        goto("cooking_step")
        return

    if intent in ("등록", "정정"):
        prompt = result.get("prompt") or result.get("summary") or result.get("message")
        if prompt:
            speak(prompt)
        goto("register_intro")
        return

    # 알 수 없는 intent(방어적 처리) — 서비스가 죽는 대신 fallback으로.
    # 위와 같은 이유(2026-08-22) — unclassified가 chat_log의 마지막 ai 메시지를 다시
    # 들려주므로 hidden=True.
    speak("죄송해요, 잘 처리하지 못했어요. 다시 한 번 말씀해주시겠어요?", hidden=True)
    goto("unclassified")


def fallback_buttons(key_prefix: str) -> None:
    """FR-16 — 음성 인식/의도분류 실패 시 수동 [이전][다시][다음]. 항상 노출한다."""
    session = st.session_state.pipeline_session
    if not session.get("current_recipe_id"):
        return
    st.caption("음성이 잘 안 될 땐 아래 버튼으로도 진행할 수 있어요.")
    c1, c2, c3 = st.columns(3)
    client = get_client()
    for col, button in ((c1, "이전"), (c2, "다시"), (c3, "다음")):
        with col:
            if st.button(button, key=f"{key_prefix}_{button}", use_container_width=True):
                result = manual_fallback(session, button, client=client)
                if result.get("no_previous"):
                    speak("1단계예요, 이전 단계가 없어요.")
                    goto("cooking_step")
                elif result.get("step") is None:
                    # process_utterance()의 같은 분기와 동일한 이유(2026-08-22) — 마지막
                    # 단계에서 "다음" 버튼을 누르면 완료 화면으로 보낸다.
                    speak(COOKING_COMPLETE_MESSAGE, hidden=True)
                    goto("cooking_complete")
                else:
                    # process_utterance()의 같은 분기와 동일한 이유(2026-08-22) — 실제 단계
                    # 오디오를 다시 보여줄 때만 nonce를 올린다. "1단계예요..." 안내는 화면의
                    # 단계가 안 바뀌는데 nonce만 올리면, rerun 후 그 자리에 남아있는 단계
                    # 카드의 캐시 오디오가 다시 자동재생되면서 방금 들려준 안내 음성과
                    # 겹쳐 들린다. speak() 자체도 hidden=True — 도착 화면(cooking_step)이
                    # render_step_card()로 같은 오디오를 캐시에서 다시 들려주므로, 여기서
                    # 그리는 재생바는 rerun에 곧장 지워지는 "떴다 사라짐" 깜빡임만 남긴다.
                    st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                    speak(
                        result["step"]["text"],
                        recipe_id=session.get("current_recipe_id"),
                        step_number=result["step"].get("step_number"),
                        hidden=True,
                    )
                    goto("cooking_step")
