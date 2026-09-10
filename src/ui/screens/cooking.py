"""ChefEar 조리 흐름 화면(start / recipe_confirm / cooking_step / cooking_complete)."""
from __future__ import annotations

import streamlit as st

from theme import (
    ICON_CHECK_CIRCLE,
    render_back_link,
    render_badge,
    render_big_mic,
    render_chat,
    render_chips,
    render_mic_bar,
    render_spacer,
    render_step_card,
)
from orchestration.term_dict import resolve_for_display, resolve_for_tts
from ui.dispatch import COOKING_COMPLETE_MESSAGE, fallback_buttons, is_home_word, reset_to_start
from ui.recipe_view import _ingredients_to_chips, refresh_recipe_view
from ui.session import goto
from ui.voice_io import _AUDIO_DIR, _render_cached_speech, mic_is_playing, prefetch_remaining_steps_audio, speak


def screen_start() -> None:
    render_spacer()
    st.markdown('<div style="height:100px;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>무엇을 만들고 싶으세요?</h1>'
        "<p>숫자 메뉴 없이, 하고 싶은 말을 편하게 그대로 말씀해주세요.</p>"
        '<p style="color:var(--text-faint); font-size:13.5px;">예: "된장찌개 어떻게 만들어?"</p></div>',
        unsafe_allow_html=True,
    )
    chat_log = st.session_state.chat_log
    if chat_log and chat_log[-1][0] == "ai":
        _render_cached_speech(chat_log[-1][1], nonce=st.session_state.get("_audio_replay_nonce", 0))
        st.session_state.chat_log = []
    render_big_mic(ready=mic_is_playing())


    render_spacer()


def screen_recipe_confirm() -> None:
    view = st.session_state.recipe_view
    if not view:
        print("[GUARD] screen_recipe_confirm: recipe_view 비어있음 -> start로", flush=True)
        goto("start")
        return

    render_badge("조회수 1위 표준 레시피")
    chat_log = st.session_state.chat_log
    last_ai = next((m for role, m in reversed(chat_log) if role == "ai"), None)
    if last_ai is not None:
        _render_cached_speech(last_ai, nonce=st.session_state.get("_audio_replay_nonce", 0))
    if chat_log:
        render_chat(chat_log)

    st.markdown("**재료 미리보기**")
    render_chips(_ingredients_to_chips(view["ingredients_raw"]))

    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"응" 또는 다른 요청을 말씀해주세요',
        listening=_mic_ready,
    )


    with st.container(key="recipe_confirm_other_recipe_btn"):
        if st.button("다른 레시피 찾을래요", use_container_width=True):
            goto("start")


def handle_recipe_confirm(text: str) -> None:
    """screen_recipe_confirm()이 그려진 뒤 app.py가 잡아온 발화를 처리한다."""
    view = st.session_state.recipe_view
    if not view:
        print(f"[GUARD] handle_recipe_confirm: recipe_view 비어있음, text={text!r} -> 무시", flush=True)
        return  # 화면 본문이 이미 goto("start")로 넘어갔을 상황 — 방어적으로만 남김

    norm = text.strip().rstrip("?!. ")
    print(f"[RECIPE_CONFIRM] text={text!r} norm={norm!r}", flush=True)
    if is_home_word(norm) or "처음" in norm:
        print(f"[RECIPE_CONFIRM] 분기=처음/홈단어 -> reset_to_start()", flush=True)
        st.session_state.chat_log.append(("user", text))
        reset_to_start()
    elif "다시" in norm:
        print(f"[RECIPE_CONFIRM] 분기=다시 -> 같은 화면 재생", flush=True)
        st.session_state.chat_log.append(("user", text))
        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
        st.rerun()
    elif any(word in norm for word in ("아니", "싫", "말고", "별로", "취소", "안 좋", "안좋", "안 할", "안할", "안 해", "안해", "안 돼", "안돼")):
        print(f"[RECIPE_CONFIRM] 분기=부정어 -> reset_to_start()", flush=True)
        st.session_state.chat_log.append(("user", text))
        reset_to_start()
    elif "등록" in norm:
        print(f"[RECIPE_CONFIRM] 분기=등록 -> register_dish_name", flush=True)
        # "이거 말고 등록할래" 등 — 현재 뜬 레시피가 아니라 새 레시피 등록 의도.
        # dispatch.py::process_utterance()의 _REGISTER_WORD 처리와 같은 목적지.
        st.session_state.chat_log.append(("user", "등록"))
        st.session_state.pending_dish_name = None
        goto("register_dish_name")
    elif (
        any(word in norm for word in ("응", "네", "좋", "다음", "그래", "시작", "진행", "할래"))
        or norm.lower() == "next"
    ):
        print(f"[RECIPE_CONFIRM] 분기=확정단어 -> cooking_step (step 1)", flush=True)
        st.session_state.chat_log.append(("user", text))
        st.session_state.pipeline_session["step_number"] = 1
        if view["steps"]:
            first_step = view["steps"][0]
            speak(
                resolve_for_tts(first_step["text"]),
                recipe_id=view["recipe_id"],
                step_number=first_step.get("step_number", 1),
                hidden=True,
            )
        else:
            speak("1단계 정보를 찾지 못했어요.", hidden=True)
        goto("cooking_step")
    else:
        print(f"[RECIPE_CONFIRM] 분기=무시(아무 단어도 매칭 안 됨) -> 화면 그대로, rerun만", flush=True)
        st.rerun()


def screen_cooking_step() -> None:
    refresh_recipe_view()
    view = st.session_state.recipe_view
    session = st.session_state.pipeline_session
    if not view or not view["steps"]:
        goto("start")
        return

    total = len(view["steps"])
    step_number = min(session.get("step_number", 1), total)
    current = view["steps"][step_number - 1]

    prefetch_remaining_steps_audio(view, step_number)

    render_badge(f'{view["dish_name"]} · {step_number} / {total} 단계')

    with st.container(key="cs_notice_audio_slot"):
        chat_log = st.session_state.chat_log
        if chat_log and chat_log[-1][0] == "ai":
            _render_cached_speech(chat_log[-1][1], nonce=st.session_state.get("_cooking_notice_nonce", 0))

    cached_audio_path = _AUDIO_DIR / str(view["recipe_id"]) / f"{step_number:02d}.wav"
    display_text = resolve_for_display(current["text"])
    if cached_audio_path.exists():
        nav_target = render_step_card(
            total,
            step_number,
            display_text,
            audio_path=cached_audio_path,
            audio_nonce=st.session_state.get("_audio_replay_nonce", 0),
        )
    else:
        nav_target = render_step_card(total, step_number, display_text)

    if nav_target is not None:
        if nav_target > total:
            speak(COOKING_COMPLETE_MESSAGE, hidden=True)
            goto("cooking_complete")
            return
        session["step_number"] = nav_target
        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
        target_step = view["steps"][nav_target - 1]
        speak(
            resolve_for_tts(target_step["text"]),
            recipe_id=view["recipe_id"],
            step_number=target_step.get("step_number", nav_target),
            hidden=True,
        )
        goto("cooking_step")

    st.markdown("**오늘의 재료**")
    render_chips(_ingredients_to_chips(view["ingredients_raw"]))

    if st.session_state.chat_log:
        render_chat(st.session_state.chat_log)

    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"이전" · "다시" · "다음"',
        listening=_mic_ready,
    )

    fallback_buttons("cooking_step")


def screen_cooking_complete() -> None:
    """마지막 단계까지 다 왔을 때 보여주는 완료 화면 — 이전엔 "마지막
    단계까지 다 왔어요"를 음성으로만 안내하고 cooking_step 화면에 그대로 머물러서, 요리가
    끝났다는 게 화면으로는 드러나지 않았다. register_steps -> screen_complete와 같은
    패턴: 전환 직전(dispatch.py)에서 COOKING_COMPLETE_MESSAGE를 hidden=True로 미리
    합성/캐싱해두고, 여기서 _render_cached_speech로 같은 캐시를 다시 찾아 들려준다.
    """
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    if render_back_link("처음으로"):
        reset_to_start()

    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ce-center"><h1>요리가 완성됐어요!</h1>'
        f"<p>{dish_name}, 수고하셨어요.</p></div>",
        unsafe_allow_html=True,
    )
    if not st.session_state.get("_cooking_complete_audio_played"):
        _render_cached_speech(COOKING_COMPLETE_MESSAGE)
        st.session_state["_cooking_complete_audio_played"] = True
    render_spacer()

    if st.button("처음 화면으로", type="primary", use_container_width=True):
        reset_to_start()
