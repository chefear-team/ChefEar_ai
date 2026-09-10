"""ChefEar 발화 디스패처 — 인식된 문장을 의도별로 처리하고 화면을 전환한다(`process_utterance`)."""
from __future__ import annotations

import re
import threading
import time

import streamlit as st

from orchestration import gpu_worker_pool
from orchestration.db import get_client
from orchestration.pipeline import manual_fallback
from orchestration.term_dict import resolve_for_tts
from ui.recipe_view import _fetch_recipe_view, _view_cache_fresh, refresh_recipe_view
from ui.session import _DEFAULT_PIPELINE_SESSION, get_owner_id, goto
from ui.voice_io import _close_loading_overlay, _drain_mic_while, speak

COOKING_COMPLETE_MESSAGE = "요리가 완성됐어요! 수고하셨어요."

_HOME_WORDS = {
    "처음", "처음으로", "처음화면", "처음 화면", "처음 화면으로",
    "메인", "메인 화면", "홈",
    "초기", "초기화면", "초기 화면", "초기화",
}

_REGISTER_WORD = "등록"

_LOOKUP_CACHE_TTL_S = 300

_INTENT_DISPLAY_LABEL = {"진행": "다음", "재청취": "다시", "이전": "이전", "등록": "등록"}


def _normalize_for_lookup(text: str) -> str:
    """세션 요리명 조회 캐시(_recipe_lookup_cache)의 키 정규화 — extract_intent_llm()이
    LLM에 넣기 전 하는 것과 같은 처리(끝 문장부호 제거 + 공백 전부 제거)에 소문자화만
    더했다. "된장찌개", "된장찌개?", "된장 찌개 " 가 같은 키가 되게 해서, 같은 메뉴를
    표현만 살짝 바꿔 다시 말해도 캐시에 맞게 한다. 자유발화 문장 전체("된장찌개 어떻게
    만들어")는 여기서 요리명만 뽑지 않으므로 그 형태 그대로가 키가 된다 — 그래도
    사용자가 시연 중 같은 문장을 반복하는 흔한 패턴은 그대로 캐시된다."""
    return re.sub(r"\s+", "", text.strip().rstrip("?!.,~ ").lower())


def is_home_word(text: str) -> bool:
    """recipe_confirm/register_dish_name처럼 classify_intent()를 안 거치고
    자기 화면 안에서 직접 몇 단어만 확인하는 화면들도 이걸로 "처음" 발화를 똑같이 잡아낼
    수 있게 공개 함수로 둔다.
    """
    norm = text.strip().rstrip("?!. ")
    return any(word in norm for word in _HOME_WORDS)


def reset_to_start() -> None:
    """"처음 화면으로" 버튼들(cooking.py/register.py)과 동일한 초기화 — 진행 중이던
    레시피/등록/대화 기록을 전부 비우고 start로 보낸다.
    """
    st.session_state.pipeline_session = dict(_DEFAULT_PIPELINE_SESSION)
    st.session_state.chat_log = []
    st.session_state.recipe_view = None
    st.session_state.pending_dish_name = None
    st.session_state["_tts_mute_until"] = 0.0
    goto("start")


def listen_background_only(key_prefix: str, *, cancel_target: str) -> None:
    """register_ingredients/register_steps처럼 이미 목적이 뚜렷한 텍스트 폼(재료/순서
    추가칸)을 쓰는 화면용 — 상시 마이크 연결은 계속 유지하되("start
    화면 말고는 안 끊기게 해달라"는 요청) 자유 발화를 그대로 재료/순서 항목으로 등록해버리면
    안 되므로, "취소"/"처음" 같은 소수의 안전한 단어에만 반응하고 나머지는 무시한다 —
    이 화면들의 진짜 입력 수단은 여전히 화면 자체의 텍스트 폼이다.
    """
    from ui.voice_io import listen

    text = listen(key_prefix, show_text_fallback=False)
    if not text:
        return
    norm = text.strip().rstrip("?!. ")
    if is_home_word(norm):
        reset_to_start()
    elif norm in ("취소", "취소할래요", "취소해줘"):
        goto(cancel_target)
    else:
        st.rerun()


def _is_admin_trigger(text: str) -> bool:
    """"관리자 페이지 접근할게요" 류 발화 감지 — 관리자 페이지로 이동만 시키는 트리거
    (docs/specs/admin_voice_2fa.md 옵션 A). 실제 인증은 도착한 관리자 페이지의 랜덤
    단어 챌린지 + 화자검증이 한다 — 이 문구 자체는 아무 권한도 안 주므로 노출/복제돼도
    무방하다. is_home_word()처럼 조사/군더더기에 강하게 "포함" 매칭한다."""
    norm = re.sub(r"\s+", "", text.strip())
    if "관리자" not in norm:
        return False
    return any(k in norm for k in ("페이지", "화면", "권한", "모드", "콘솔", "접근"))


def process_utterance(text: str) -> None:
    print(
        f"[DISPATCH] process_utterance 진입: sid={st.session_state.get('_sid')} "
        f"text={text!r} screen={st.session_state.get('screen')!r}",
        flush=True,
    )
    if is_home_word(text):
        print(f"[DISPATCH] 분기=is_home_word -> reset_to_start()", flush=True)
        reset_to_start()
        return

    if _is_admin_trigger(text):
        print(f"[DISPATCH] 분기=admin_trigger -> 관리자 페이지 전환", flush=True)
        st.session_state["_admin_via_voice"] = True
        st.rerun()
        return


    if _REGISTER_WORD in text and not st.session_state.pipeline_session.get("current_recipe_id"):
        print(f"[DISPATCH] 분기=등록단어(빠른경로) -> register_dish_name", flush=True)
        st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL["등록"]))
        st.session_state.pending_dish_name = None
        goto("register_dish_name")
        return

    session = st.session_state.pipeline_session
    client = get_client()
    owner_id = get_owner_id()

    lookup_key = f"{owner_id}:{_normalize_for_lookup(text)}"
    lookup_cache = st.session_state.setdefault("_recipe_lookup_cache", {})
    _hit = lookup_cache.get(lookup_key)
    _hit_fresh = _hit is not None and (time.monotonic() - _hit.get("_ts", 0.0)) < _LOOKUP_CACHE_TTL_S
    # [PERF] — 이 캐시는 "조리 중 아님" + "같은 발화를 이 세션에서 이미 조회한 적
    # 있음" 두 조건이 다 맞을 때만 히트한다(위 문서 참고) — 처음 묻는 요리명이나
    # 진행/재청취 명령("다시"/"다음")은 이 캐시 자체를 안 타는 게 정상 설계다.
    print(
        f"[PERF] recipe_lookup_cache "
        f"{'HIT' if (_hit_fresh and not session.get('current_recipe_id')) else 'MISS'} key={lookup_key!r}",
        flush=True,
    )
    if not session.get("current_recipe_id") and _hit_fresh:
        hit = _hit
        print(f"[DISPATCH] 분기=조회(캐시히트) dish_name={hit['dish_name']!r} -> recipe_confirm", flush=True)
        st.session_state.chat_log.append(("user", hit["dish_name"]))
        session["current_recipe_id"] = hit["recipe_id"]
        session["step_number"] = 1
        refresh_recipe_view(force=True)  # _recipe_view_cache가 DB 왕복을 막아준다
        speak(
            f'{hit["dish_name"]}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?',
            hidden=True,
        )
        goto("recipe_confirm")
        return

    view = st.session_state.get("recipe_view")
    steps_cache = (
        view["steps"]
        if view and view.get("recipe_id") == session.get("current_recipe_id") and view.get("steps")
        else None
    )
    view_cache = st.session_state.setdefault("_recipe_view_cache", {})

    job: dict = {
        "done": False,
        "llm_result": None,
        "result": None,
        "value_error": False,
        "network_error": False,
        "recipe_view": None,
        "recipe_view_id": None,
    }

    def _compute(job=job) -> None:
        try:
            if session.get("current_recipe_id"):
                # 조리 중이면 이 결과가 뭐가 나오든 안 쓰이니(위 문서 참고) 호출 자체를
                # 건너뛴다 — 아래 나머지 로직(handle_utterance() 호출과 그 예외 처리)은
                # 그대로 다 거친다, 이 값만 안전한 기본값으로 채운다.
                job["llm_result"] = {"dish_name": None, "wants_register": False}
            else:
                try:
                    _llm_t0 = time.monotonic()
                    job["llm_result"] = gpu_worker_pool.submit_llm_extract(text).result()
                    print(f"[PERF] LLM(extract) {time.monotonic() - _llm_t0:.2f}s", flush=True)
                except Exception as exc:  # noqa: BLE001 — 아래 이유로 여기서만 넓게 잡음
                    print(f"[dispatch] extract_intent_llm 실패, 안전한 기본값으로 폴백: {exc!r}")
                    job["llm_result"] = {"dish_name": None, "wants_register": False}
            if job["llm_result"]["wants_register"]:
                return
            try:
                _hu_t0 = time.monotonic()
                job["result"] = gpu_worker_pool.submit_handle_utterance(
                    session,
                    text,
                    dish_name=job["llm_result"]["dish_name"],
                    steps=steps_cache,
                    owner_id=owner_id,
                ).result()
                print(f"[PERF] handle_utterance(intent+DB) {time.monotonic() - _hu_t0:.2f}s", flush=True)
            except ValueError:
                job["value_error"] = True
            except Exception as exc:
                # handle_utterance() 내부의 Supabase 조회(client.table(...).execute())가
                # 던지는 네트워크/HTTP 오류(APIError, 타임아웃, 연결 끊김 등, 4xx/5xx 포함)
                # 는 ValueError가 아니라서 위 except가 못 잡았다 — 그러면 이 background
                # 스레드가 여기서 조용히 죽고(daemon 스레드라 프로세스는 안 죽지만 이
                # job["result"]는 None으로 남는다), 메인 스레드가 잠시 뒤 result.get(...)
                # 에서 AttributeError로 크래시한 뒤에야 app.py의 최상위 catch-all이 겨우
                # 받아내는 지저분한 경로였다(실측 확인 — "40x/50x 에러 다 잡고 있나?"
                # 질문 계기). extract_intent_llm()과 같은 패턴(넓게 잡고 안전한 값으로
                # 폴백)으로 여기도 명시적으로 처리한다 — 무슨 예외인지도 콘솔에 남긴다.
                print(f"[dispatch] handle_utterance 실패(네트워크/서버 오류 추정): {exc!r}")
                job["network_error"] = True

            res = job["result"]
            if res and res.get("intent") == "조회" and res.get("recipe_id") and "message" not in res:
                rid = res["recipe_id"]
                try:
                    _cv = view_cache.get(rid)
                    job["recipe_view"] = _cv if _view_cache_fresh(_cv) else _fetch_recipe_view(rid, client)
                    job["recipe_view_id"] = rid
                except Exception as exc:  # noqa: BLE001 — 못 가져오면 메인이 refresh_recipe_view()로 폴백
                    print(f"[dispatch] recipe_view 배경 조회 실패(메인에서 재시도): {exc!r}")
        finally:
            job["done"] = True

    threading.Thread(target=_compute, daemon=True).start()
    overlay = _drain_mic_while(job, close=False)

    try:
        llm_result = job["llm_result"]
        dish_name_guess = llm_result["dish_name"]

        print(f"[DISPATCH] LLM 추출 결과: dish_name={dish_name_guess!r} wants_register={llm_result['wants_register']!r}", flush=True)
        if llm_result["wants_register"] and not session.get("current_recipe_id"):
            print(f"[DISPATCH] 분기=wants_register(LLM) -> register_dish_name", flush=True)
            st.session_state.pending_dish_name = dish_name_guess
            _close_loading_overlay(overlay)
            goto("register_dish_name")
            return
        # intent_classifier.py의 "등록"(임베딩 매칭)은 context_recipe_id가 있으면(=이미
        # 조리 중) 무시하도록 이미 고쳤는데, 이 LLM 경로(wants_register)는 완전히 별개
        # 판정이라 그 보호를 못 받고 있었다 — 위 if 조건에 `and not session.get("current_recipe_id")`를
        # 추가해서 조리 중엔 이 경로 자체를 안 타게 막았다 — 여기로 떨어지면(조리 중에
        # wants_register가 True) 그냥 무시하고 원래 화면에 머무른다("등록은 첫 페이지 아니면
        # 의미없는 문구다" 원칙, classify_intent() 쪽과 동일).
        elif llm_result["wants_register"]:
            print(f"[DISPATCH] 분기=wants_register(조리중이라 무시) -> 화면 그대로, rerun만", flush=True)
            _close_loading_overlay(overlay)
            st.rerun()
            return

        if job["network_error"]:
            print(f"[DISPATCH] 분기=network_error -> unclassified", flush=True)
            speak("일시적인 오류가 발생했어요. 잠시 후 다시 이용해 주세요.", hidden=True, _loading_overlay=overlay)
            goto("unclassified")
            return

        if job["value_error"]:
            print(f"[DISPATCH] 분기=value_error(등록 의도인데 registration_step 없음) -> register_dish_name", flush=True)
            # 위 배경 스레드의 _compute() 안에서 handle_utterance()가 ValueError를 던진 경우 —
            # "등록" 의도인데 registration_step 없이 자유발화로 들어온 경우 등. 서비스를
            # 죽이는 대신 신규 등록으로 안전하게 보낸다. classify_intent()가 이미 "등록"으로
            # 확정 분류한 경우라 위 wants_register 분기와 같은 이유로 register_intro(확인
            # 화면)는 안 거치고 바로 register_dish_name으로 보낸다.
            st.session_state.pending_dish_name = dish_name_guess
            _close_loading_overlay(overlay)
            goto("register_dish_name")
            return

        result = job["result"]
        intent = result.get("intent")
        print(f"[DISPATCH] classify_intent 결과: intent={intent!r} result={result!r}", flush=True)

        if intent == "미분류" or intent == "감탄사":
            print(f"[DISPATCH] 분기=미분류/감탄사 -> 무시(화면 그대로, rerun만)", flush=True)
            _close_loading_overlay(overlay)
            st.rerun()
            return


        if intent == "조회":
            if "message" in result:  # DISH_NOT_FOUND_MESSAGE 또는 PENDING_MESSAGE
                print(f"[DISPATCH] 분기=조회(실패) message={result['message']!r} -> 현재 화면 유지, rerun만", flush=True)
                st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                # hidden=True — 도착 화면(현재 화면 그대로, 대개 start)이 _render_cached_speech()로
                # 재생을 맡는다. 여기서 render_audio_player()를 그리면 바로 뒤 st.rerun()에 곧장
                # 지워지는 "떴다 사라짐" 깜빡임만 남는다(이 파일 다른 분기들과 동일 패턴).
                speak(result["message"], hidden=True, _loading_overlay=overlay)
                st.rerun()
                return
            print(f"[DISPATCH] 분기=조회(성공) dish_name={result['dish_name']!r} recipe_id={result['recipe_id']!r} -> recipe_confirm", flush=True)
            st.session_state.chat_log.append(("user", result["dish_name"]))
            session["current_recipe_id"] = result["recipe_id"]
            session["step_number"] = 1
            lookup_cache[lookup_key] = {
                "recipe_id": result["recipe_id"],
                "dish_name": result["dish_name"],
                "_ts": time.monotonic(),
            }
            if job["recipe_view"] is not None:
                st.session_state.recipe_view = job["recipe_view"]
                view_cache[job["recipe_view_id"]] = job["recipe_view"]
            else:
                refresh_recipe_view(force=True)
            # 위와 같은 이유 — 도착 화면(recipe_confirm)이 chat_log의 마지막 ai 메시지를
            # _render_cached_speech()로 다시 들려준다.
            speak(
                f'{result["dish_name"]}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?',
                hidden=True,
                _loading_overlay=overlay,
            )
            goto("recipe_confirm")
            return

        if intent in ("진행", "재청취", "이전"):
            session["step_number"] = result["step_number"]
            step = result.get("step")
            print(
                f"[DISPATCH] 분기={intent} step_number(반영후)={session['step_number']!r} "
                f"no_previous={result.get('no_previous')!r} step_is_none={step is None!r}",
                flush=True,
            )
            if result.get("no_previous"):
                print(f"[DISPATCH]   -> no_previous 안내, cooking_step 유지", flush=True)
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                st.session_state["_cooking_notice_nonce"] = st.session_state.get("_cooking_notice_nonce", 0) + 1
                speak("1단계예요, 이전 단계가 없어요.", hidden=True, _loading_overlay=overlay)
                goto("cooking_step")
            elif step is None:
                print(f"[DISPATCH]   -> 마지막 단계 이후 -> cooking_complete", flush=True)
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                st.session_state["_cooking_complete_audio_played"] = False
                speak(COOKING_COMPLETE_MESSAGE, hidden=True, _loading_overlay=overlay)
                goto("cooking_complete")
            else:
                print(f"[DISPATCH]   -> 정상 진행, step_number={step.get('step_number')!r} -> cooking_step", flush=True)
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                speak(
                    resolve_for_tts(step["text"]),
                    recipe_id=session.get("current_recipe_id"),
                    step_number=step.get("step_number"),
                    hidden=True,
                    _loading_overlay=overlay,
                )
                goto("cooking_step")
            return

        if intent == "등록":
            print(f"[DISPATCH] 분기=등록(분류) -> register_dish_name", flush=True)
            st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
            prompt = result.get("prompt") or result.get("summary") or result.get("message")
            st.session_state.pending_dish_name = result.get("dish_name")
            if prompt:
                speak(prompt, _loading_overlay=overlay)
            else:
                _close_loading_overlay(overlay)
            goto("register_dish_name")
            return

        # 알 수 없는 intent(방어적 처리) — 서비스가 죽는 대신 fallback으로.
        print(f"[DISPATCH] 분기=알수없는intent({intent!r}, 방어적처리) -> unclassified", flush=True)
        st.session_state.chat_log.append(("user", text))
        speak("죄송해요, 잘 처리하지 못했어요. 다시 한 번 말씀해주시겠어요?", hidden=True, _loading_overlay=overlay)
        goto("unclassified")
    finally:
        _close_loading_overlay(overlay)


def fallback_buttons(key_prefix: str) -> None:
    """FR-16 — 음성 인식/의도분류 실패 시 수동 [이전][다시][다음]. 항상 노출한다."""
    session = st.session_state.pipeline_session
    if not session.get("current_recipe_id"):
        return
    client = get_client()
    view = st.session_state.get("recipe_view")
    steps_cache = (
        view["steps"]
        if view and view.get("recipe_id") == session.get("current_recipe_id") and view.get("steps")
        else None
    )
    with st.container(key=f"{key_prefix}_fallback"):
        st.caption("음성이 잘 안 될 땐 아래 버튼으로도 진행할 수 있어요.")
        c1, c2, c3 = st.columns(3)
        for col, button in ((c1, "이전"), (c2, "다시"), (c3, "다음")):
            with col:
                if st.button(button, key=f"{key_prefix}_{button}", use_container_width=True):
                    result = manual_fallback(session, button, client=client, steps=steps_cache)
                    print(
                        f"[DISPATCH] fallback_buttons: button={button!r} -> "
                        f"step_number={session.get('step_number')!r} result={result!r}",
                        flush=True,
                    )
                    if result.get("no_previous"):
                        st.session_state["_cooking_notice_nonce"] = (
                            st.session_state.get("_cooking_notice_nonce", 0) + 1
                        )
                        speak("1단계예요, 이전 단계가 없어요.", hidden=True)
                        goto("cooking_step")
                    elif result.get("step") is None:
                        st.session_state["_cooking_complete_audio_played"] = False
                        speak(COOKING_COMPLETE_MESSAGE, hidden=True)
                        goto("cooking_complete")
                    else:
                        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                        speak(
                            resolve_for_tts(result["step"]["text"]),
                            recipe_id=session.get("current_recipe_id"),
                            step_number=result["step"].get("step_number"),
                            hidden=True,
                        )
                        goto("cooking_step")
