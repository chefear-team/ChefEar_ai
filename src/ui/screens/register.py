"""ChefEar 신규 등록 플로우 화면(unclassified / register_dish_name → register_ingredients → register_steps → complete)."""
from __future__ import annotations

import streamlit as st

from theme import (
    ICON_CHECK_CIRCLE,
    ICON_QUESTION_CIRCLE,
    render_back_link,
    render_chips,
    render_dots,
    render_mic_bar,
    render_spacer,
)
from orchestration.db import get_client
from orchestration.registration import register_recipe
from ui.dispatch import fallback_buttons, is_home_word, reset_to_start
from ui.session import get_owner_id, goto
from ui.voice_io import _render_cached_speech, mic_is_playing, speak

_REGISTER_SAVED_MESSAGE = "저장이 완료됐어요!"


def screen_unclassified() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon warn">{ICON_QUESTION_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>잘 이해하지 못했어요</h1>'
        "<p>죄송해요, 다시 한번 말씀해주시겠어요? 안 될 때는 아래 버튼으로도 진행할 수 있어요.</p></div>",
        unsafe_allow_html=True,
    )
    chat_log = st.session_state.chat_log
    last_ai = next((m for role, m in reversed(chat_log) if role == "ai"), None)
    if last_ai is not None:
        # dispatch.py의 hidden=True speak()가 미리 캐싱해둔 문구를 여기서 다시 들려준다.
        _render_cached_speech(last_ai, nonce=st.session_state.get("_audio_replay_nonce", 0))
    render_spacer()
    render_mic_bar("다시 말씀해주세요", "또는 아래 버튼을 눌러주세요", listening=False)

    fallback_buttons("unclassified")

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 process_utterance()에 그대로
    # 넘긴다 — 이 화면은 별도 핸들러가 없다(위 파일 docstring 참고).


def screen_register_dish_name() -> None:
    """FR-06 1단계: 요리명 질문. 다른 경로(LLM wants_register 등)에서 넘어온
    추측값(pending_dish_name)을 그대로 쓰지 않고 사용자가 직접 확인/수정하게 한다.
    요리명 추출은 틀릴 수 있으므로, DB에 실제로 남는 등록 데이터는 검증 없이 넘기지 않는다.
    """
    if not st.session_state.get("current_user"):
        goto("login")
        return
    if render_back_link("처음 화면으로"):
        reset_to_start()
    st.markdown('<p class="ce-hint">새 레시피 등록 · 1 / 3 · 요리명</p>', unsafe_allow_html=True)
    render_dots(3, 1)
    st.markdown("**어떤 요리인가요?**")
    if st.session_state.pending_dish_name:
        st.caption(f'짐작한 이름: "{st.session_state.pending_dish_name}" — 맞으면 "네", 다르면 이름을 말씀해주세요')
    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        "요리 이름을 말씀해주세요",
        listening=_mic_ready,
    )

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 아래 handle_register_dish_name()에
    # 넘긴다(위 파일 docstring 참고).

    with st.container(key="register_dish_name_cancel_btn"):
        if st.button("취소", use_container_width=True):
            reset_to_start()


def handle_register_dish_name(text: str) -> None:
    """screen_register_dish_name()이 그려진 뒤 app.py가 잡아온 발화를 처리한다."""
    norm = text.strip().rstrip("?!. ")
    print(f"[REGISTER_DISH_NAME] text={text!r} norm={norm!r} pending={st.session_state.pending_dish_name!r}", flush=True)
    if is_home_word(norm):
        print(f"[REGISTER_DISH_NAME] 분기=처음/홈단어 -> reset_to_start()", flush=True)
        reset_to_start()
        return
    if norm in ("취소", "취소할래", "취소할래요", "취소해줘"):
        print(f"[REGISTER_DISH_NAME] 분기=취소 -> reset_to_start()", flush=True)
        reset_to_start()
        return
    if norm in ("네", "응", "맞아", "맞아요", "그래", "그래요", "좋아", "좋아요"):
        # 짐작한 이름이 있으면 그걸 확정, 없으면 요리명을 안 말한 것이므로 다시 묻는다
        # (예전엔 pending 없을 때 "네"가 그대로 요리명으로 등록됐다).
        if st.session_state.pending_dish_name:
            dish_name = st.session_state.pending_dish_name
            print(f"[REGISTER_DISH_NAME] 분기=확정(짐작값 사용) dish_name={dish_name!r}", flush=True)
        else:
            print(f"[REGISTER_DISH_NAME] 분기=확정단어인데 짐작값 없음 -> 다시 물음(rerun)", flush=True)
            st.rerun()
            return
    elif len(norm.replace(" ", "")) > 25:
        print(f"[REGISTER_DISH_NAME] 분기=25자 초과(문장으로 판단) -> 다시 물음(rerun)", flush=True)
        st.rerun()
        return
    else:
        dish_name = text.strip()
        print(f"[REGISTER_DISH_NAME] 분기=발화 전체를 요리명으로 -> dish_name={dish_name!r}", flush=True)
    register_recipe(st.session_state.pipeline_session, "dish_name", dish_name, client=get_client())
    print(f"[REGISTER_DISH_NAME] register_recipe(dish_name) 완료 -> register_ingredients", flush=True)
    goto("register_ingredients")


def screen_register_ingredients() -> None:
    reg = st.session_state.pipeline_session.get("registration")
    if not reg:
        goto("start")
        return

    if render_back_link("처음 화면으로"):
        reset_to_start()
    st.markdown(f'<p class="ce-hint">{reg["dish_name"]} · 2 / 3 · 재료</p>', unsafe_allow_html=True)
    render_dots(3, 2)
    st.markdown("**재료를 알려주세요**")
    render_chips([{"name": ing, "qty": "", "emoji": "✅"} for ing in reg["ingredients"]])


    _ing_turn = st.session_state.setdefault("reg_ing_turn", 0)
    new_item = st.text_input(
        "재료 추가(쉼표로 여러 개 가능)", key=f"reg_ing_new_{_ing_turn}", placeholder="예: 두부, 감자"
    )
    if st.button("추가") and new_item.strip():
        items = [x.strip() for x in new_item.split(",") if x.strip()]
        register_recipe(st.session_state.pipeline_session, "ingredients", items, client=get_client())
        print(f"[REGISTER_INGREDIENTS] 추가 버튼: items={items!r} -> 누적={reg['ingredients']!r}", flush=True)
        st.session_state.reg_ing_turn = _ing_turn + 1
        st.rerun()

    if reg["ingredients"] and st.button("네, 맞아요", type="primary", use_container_width=True):
        print(f"[REGISTER_INGREDIENTS] '네, 맞아요' 버튼 -> register_steps", flush=True)
        goto("register_steps")


def screen_register_steps() -> None:
    reg = st.session_state.pipeline_session.get("registration")
    if not reg:
        goto("start")
        return

    if render_back_link("처음 화면으로"):
        reset_to_start()
    st.markdown(f'<p class="ce-hint">{reg["dish_name"]} · 3 / 3 · 조리 순서</p>', unsafe_allow_html=True)
    render_dots(3, 3)
    st.markdown("**조리 순서를 알려주세요**")
    editing_idx = st.session_state.get("reg_step_editing_idx")
    for i, step_text in enumerate(reg["instructions"]):
        with st.container(key=f"reg_step_row_{i}"):
            if editing_idx == i:
                new_text = st.text_input(
                    "단계 수정", value=step_text, key=f"reg_step_edit_input_{i}", label_visibility="collapsed"
                )
                ec1, ec2 = st.columns(2)
                with ec1:
                    if st.button(
                        "저장", key=f"reg_step_edit_save_{i}", type="primary", use_container_width=True
                    ):
                        reg["instructions"][i] = new_text.strip()
                        st.session_state.reg_step_editing_idx = None
                        st.rerun()
                with ec2:
                    if st.button("취소", key=f"reg_step_edit_cancel_{i}", use_container_width=True):
                        st.session_state.reg_step_editing_idx = None
                        st.rerun()
            else:
                c1, c_actions = st.columns([5, 2])
                with c1:
                    st.markdown(
                        f'<div style="display:flex; align-items:center; gap:12px;">'
                        f'<span class="ce-step-num">{i + 1}</span>'
                        f'<p style="margin:0; font-size:14.5px; line-height:1.55; color:var(--text);">{step_text}</p>'
                        "</div>",
                        unsafe_allow_html=True,
                    )
                with c_actions:
                    with st.container(key=f"reg_step_actions_{i}"):
                        if st.button(":material/edit:", key=f"reg_step_edit_{i}", help="수정"):
                            st.session_state.reg_step_editing_idx = i
                            st.rerun()
                        if st.button(":material/delete:", key=f"reg_step_delete_{i}", help="삭제"):
                            reg["instructions"].pop(i)
                            st.rerun()


    # reg_ing_new와 같은 이유로 turn 카운터 기반 key를 써서 "단계 추가" 이후
    # 입력칸에 방금 텍스트가 남아있지 않게 한다.
    _step_turn = st.session_state.setdefault("reg_step_new_turn", 0)
    new_step = st.text_input("순서 추가", key=f"reg_step_new_{_step_turn}", placeholder="새 단계 추가")
    if st.button("단계 추가") and new_step.strip():
        register_recipe(st.session_state.pipeline_session, "instructions", [new_step.strip()], client=get_client())
        print(f"[REGISTER_STEPS] 단계 추가: {new_step.strip()!r} -> 누적={reg['instructions']!r}", flush=True)
        st.session_state.reg_step_new_turn = _step_turn + 1
        st.rerun()

    if reg["instructions"] and st.button("네, 저장할게요", type="primary", use_container_width=True):
        dish_name = reg["dish_name"]
        save_result = register_recipe(
            st.session_state.pipeline_session, "confirm", None, client=get_client(), owner_id=get_owner_id()
        )
        print(
            f"[REGISTER_STEPS] '네, 저장할게요' 버튼: dish_name={dish_name!r} "
            f"ingredients={reg['ingredients']!r} instructions={reg['instructions']!r} "
            f"save_result={save_result!r} -> complete",
            flush=True,
        )
        st.session_state.recipe_view = {"dish_name": dish_name}
        speak(_REGISTER_SAVED_MESSAGE, hidden=True)
        goto("complete")


def screen_complete() -> None:
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ce-center"><h1>저장이 완료됐어요!</h1>'
        f"<p>{dish_name}, 등록한 계정으로 바로 조회할 수 있어요.</p></div>",
        unsafe_allow_html=True,
    )
    _render_cached_speech(_REGISTER_SAVED_MESSAGE)
    # st.markdown(
    #     '<div style="text-align:center;">'
    #     f'<span class="ce-status-badge">{ICON_CHECK_SMALL} 심사 대기 중</span></div>',
    #     unsafe_allow_html=True,
    # )
    render_spacer()

    if st.button("처음 화면으로", type="primary", use_container_width=True):
        reset_to_start()

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 process_utterance()에 그대로
    # 넘긴다 — 이 화면은 별도 핸들러가 없다(위 파일 docstring 참고).
