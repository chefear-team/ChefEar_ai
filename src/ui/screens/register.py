"""ChefEar 신규 등록 플로우 화면(register_dish_name -> ... -> complete) —
src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

register_recipe()가 돌려주는 prompt/summary는 대화 중간(재료·순서 누적)에만 있고,
화면 전환 시점의 고정 안내문(순서 질문 등)은 없다 — 그 화면 자신이 자신의 안내문을
"무슨 말을 했는지" 알아야 voice_io._render_cached_speech()로 같은 캐시를 다시 찾을 수
있어서, 전환 직전(호출부)과 도착 화면 양쪽이 똑같이 이 함수들을 불러 쓴다.

2026-09-02 — "표준 레시피에 없는 요리예요"라고 한 번 더 확인받던 register_intro
화면을 없앴다(사용자 요청 — 등록 의도가 이미 확정된 뒤에 다시 물어볼 필요가 없다는
판단, dispatch.py의 "등록"/wants_register 분기들과 register_dish_name 취소 버튼이
전부 이 화면 하나(register_dish_name)로 곧장 수렴한다).

2026-08-25 — listen()/listen_background_only() 호출은 이 파일의 화면 함수들이 아니라
app.py::main()이 화면별 key 컨테이너 *밖에서* 직접 부른다(cooking.py 상단 주석/app.py
주석 참고 — 화면 key 컨테이너가 바뀔 때마다 그 안의 webrtc 컴포넌트가 재마운트돼 마이크가
화면 전환마다 새로 연결되는 문제 대응). process_utterance()로 충분한 화면은 별도 핸들러가
없고, 문자열을 직접 비교하는 화면(register_dish_name)만 handle_*() 함수를 따로 둔다.
"""
from __future__ import annotations

import streamlit as st

from theme import (
    ICON_CHECK_CIRCLE,
    # ICON_CHECK_SMALL,  # 2026-09-02 — "심사 대기 중" 배지와 함께 주석 처리(screen_complete() 참고)
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
    # 2026-08-28 수정 — 마지막 ai 메시지 + nonce. (1) "다시" 등으로 뒤에 ("user",...)가
    # append되면 chat_log[-1]이 ai가 아니게 되는 경우 대비, (2) 같은 안내 문구가 연속으로
    # 오면(예: 조회 실패 반복) nonce가 없으면 브라우저가 autoplay를 재실행 안 함
    # (screen_recipe_confirm / dispatch 조회실패 분기와 같은 수정).
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
    추측값(pending_dish_name)을 그대로 쓰지 않고 사용자가 직접 확인/수정하게 한다 —
    규칙 기반 추출은 틀릴 수 있어서
    (entity_extract.py 참고) 등록처럼 DB에 실제로 남는 데이터는 검증 없이 넘기면 안 된다.

    2026-09-02 — docs/specs/private_recipe_visibility.md: 등록이 로그인 필수로
    바뀌면서 이 화면이 그 게이트 역할을 한다. "등록" 빠른 단어/LLM 등록의도/
    classify_intent()의 "등록" 분류 등 모든 등록 진입 경로가 결국 이 화면
    (register_dish_name)으로 수렴하므로(dispatch.py 참고 — register_intro 확인
    화면은 삭제됨, 파일 docstring 참고), 각 진입 경로마다 따로 확인할 필요 없이
    여기 한 곳만 지키면 된다 — ui/screens/my_recipes.py의 로그인 가드와 같은
    패턴(조용히 login으로 리다이렉트, 별도 안내 문구 없음)."""
    if not st.session_state.get("current_user"):
        goto("login")
        return
    # 2026-09-02 실측 리포트 — "재료 등록에서 처음으로 가면 마이크가 잠긴다" 원인:
    # 이 back-link가 reset_to_start()를 안 거치고 goto("start")만 불러서, 이전
    # 화면에서 걸려있던 _tts_mute_until(voice_io._mic_muted() 문서 참고)이 그대로
    # start까지 넘어가 마이크가 "듣고 있어요"로는 보이는데 프레임이 무음 처리되던
    # 문제와 같은 원인 — dispatch.reset_to_start()로 바꿔 다른 버튼들과 통일한다.
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

    # 2026-08-27 — 잔상 방지용 key. "취소"는 여러 화면이 같이 쓰는 흔한 문구라 텍스트
    # 마커로는 어느 화면 소속인지 특정할 수 없어서(theme.py::_STALE_CONTENT_MARKERS
    # 문서 참고, 오지우기 위험 때문에 원래부터 제외돼 있었음) 이 화면 전용 key로
    # 구조적으로 잡는다(recipe_confirm_other_recipe_btn과 같은 패턴).
    with st.container(key="register_dish_name_cancel_btn"):
        # 2026-09-02 요청 — 등록 취소 시 register_intro("표준 레시피에 없는
        # 요리예요" 확인 화면)로 갔었는데, 이 화면 자체를 없애고 처음 화면으로
        # 바로 돌아가게 바꾼다(app.py::main()의 SCREENS/디버그 점프 목록,
        # dispatch.py의 "등록" 분기도 같이 정리 — 그쪽 주석 참고).
        # reset_to_start()로 진행 중이던 pending_dish_name 등도 같이 비운다.
        if st.button("취소", use_container_width=True):
            reset_to_start()


def handle_register_dish_name(text: str) -> None:
    """screen_register_dish_name()이 그려진 뒤 app.py가 잡아온 발화를 처리한다."""
    norm = text.strip().rstrip("?!. ")
    print(f"[REGISTER_DISH_NAME] text={text!r} norm={norm!r} pending={st.session_state.pending_dish_name!r}", flush=True)
    if is_home_word(norm):
        # 2026-08-23 추가 — 이 체크가 없으면 "처음"이라고 말해도 요리명("처음")으로
        # 그대로 등록 시도돼버린다(아래가 "확정 단어 아니면 발화 전체를 요리명으로"
        # 라서). 등록 도중이니 reset_to_start()로 진행 중이던 값도 같이 비운다.
        print(f"[REGISTER_DISH_NAME] 분기=처음/홈단어 -> reset_to_start()", flush=True)
        reset_to_start()
        return
    if norm in ("취소", "취소할래", "취소할래요", "취소해줘"):
        # 2026-09-02 — register_intro 삭제(위 버튼 주석 참고)로 처음 화면으로 바로.
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
    # 2026-08-28 추가 — 이 화면은 확정어가 아닌 발화를 전부 요리명으로 받는데, STT
    # 오인식이나 "어 잘 모르겠는데 아 된장찌개" 같은 중얼거림까지 그대로 DB에 등록돼
    # 버린다(리뷰 지적, 되돌릴 방법도 전체 리셋뿐). 실제 요리명은 공백 제거 후에도
    # 25자를 거의 안 넘는다(compound도 "소고기무국" 수준) — 그보다 길면 문장을
    # 말한 것으로 보고 요리명으로 확정하지 않고 다시 묻는다(화면 유지 + rerun).
    elif len(norm.replace(" ", "")) > 25:
        print(f"[REGISTER_DISH_NAME] 분기=25자 초과(문장으로 판단) -> 다시 물음(rerun)", flush=True)
        st.rerun()
        return
    else:
        dish_name = text.strip()
        print(f"[REGISTER_DISH_NAME] 분기=발화 전체를 요리명으로 -> dish_name={dish_name!r}", flush=True)
    # 2026-08-21: 여기서 speak(result["prompt"])로 음성 합성을 하고 있었지만, 그
    # 재생 위젯은 바로 뒤 goto()의 st.rerun()에 지워지고, 도착 화면인
    # register_ingredients는 텍스트 입력 전용(마이크 바·재생바 없음)이라 이 안내문을
    # _render_cached_speech()로 다시 보여주지도 않는다. chat_log에도 남지만 등록
    # 화면들은 render_chat()을 안 써서 그것도 어차피 안 보인다 — 즉 매번 로컬 CPU로
    # 몇 분씩 걸리는 합성을 하고도 아무도 못 듣는 죽은 호출이라 제거했다.
    register_recipe(st.session_state.pipeline_session, "dish_name", dish_name, client=get_client())
    print(f"[REGISTER_DISH_NAME] register_recipe(dish_name) 완료 -> register_ingredients", flush=True)
    goto("register_ingredients")


def screen_register_ingredients() -> None:
    reg = st.session_state.pipeline_session.get("registration")
    if not reg:
        # 2026-09-02 — register_intro 삭제(요리명 화면 취소 버튼 주석 참고). 이 방어
        # 가드는 registration 데이터 없이(예: 새로고침) 이 화면에 바로 온 경우라
        # 처음부터 다시 시작해야 하므로 start로 보낸다.
        goto("start")
        return

    # 2026-09-02 — screen_register_dish_name() 위 주석과 같은 이유(마이크 잠김 버그).
    if render_back_link("처음 화면으로"):
        reset_to_start()
    st.markdown(f'<p class="ce-hint">{reg["dish_name"]} · 2 / 3 · 재료</p>', unsafe_allow_html=True)
    render_dots(3, 2)
    st.markdown("**재료를 알려주세요**")
    render_chips([{"name": ing, "qty": "", "emoji": "✅"} for ing in reg["ingredients"]])

    # 2026-08-21: 이 화면은 텍스트 입력 전용으로 되돌렸다 — STT/TTS(마이크 바·재생바·
    # listen())를 붙였던 버전 대신, 원래의 순수 텍스트 폼(요청받은 화면 그대로)을 쓴다.
    # 2026-08-23 — 다만 상시 마이크 연결 자체는 start 화면 말고는 안 끊겨야 해서, 재료
    # 입력용 텍스트 폼은 그대로 두고 "취소"/"처음"만 배경에서 듣는다(listen_background_only()
    # 주석 참고) — 재료 자유 발화가 그대로 등록되는 걸 막기 위해 그 외 단어는 무시한다.
    # 2026-08-25 — 그 listen_background_only() 호출 자체는 app.py::main()이 화면별 key
    # 컨테이너 밖에서 직접 부른다(위 파일 docstring 참고).

    # 2026-08-27 — "추가" 누른 뒤에도 입력칸에 방금 친 글자가 그대로 남아있다는 지적.
    # st.text_input()은 key가 고정이면 session_state[key]에 값을 계속 들고 있어서
    # rerun해도 안 비워진다 — Streamlit은 위젯이 그려진 뒤에 그 값을 코드로 직접 지울
    # 방법이 없어서(위젯 인스턴스화 후 session_state[key] 대입은 예외), voice_io.py의
    # listen()이 이미 쓰는 것과 같은 패턴(turn 카운터로 매번 새 key)을 그대로 가져온다 —
    # key가 바뀌면 완전히 새 위젯이라 이전 값이 안 남는다.
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
        # 2026-09-02 — 위 screen_register_ingredients()와 같은 이유.
        goto("start")
        return

    # 2026-09-02 — screen_register_dish_name() 위 주석과 같은 이유(마이크 잠김 버그).
    if render_back_link("처음 화면으로"):
        reset_to_start()
    st.markdown(f'<p class="ce-hint">{reg["dish_name"]} · 3 / 3 · 조리 순서</p>', unsafe_allow_html=True)
    render_dots(3, 3)
    st.markdown("**조리 순서를 알려주세요**")
    # 2026-08-22 요청 - 순서 각 줄에 수정/삭제 버튼을 붙인다. register_recipe()의 "confirm"
    # step(아래 "네, 저장할게요")이 그 시점의 reg["instructions"]를 그대로 읽어서
    # save_recipe()에 넘기므로(registration.py 참고), 여기서 이 리스트 자체를 고치면
    # 수정한 문장/삭제로 뺀 항목이 백엔드 저장에도 자동으로 그대로 반영된다 — 별도로
    # "제외 목록"을 만들어 나중에 필터링할 필요가 없다.
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
                    # my_recipes.py의 my_recipe_actions_와 같은 이유(2026-08-21) - st.columns로
                    # 나누면 칸이 넓어질수록 버튼 두 개가 같이 벌어져서, 세로 블록 하나에
                    # 담고 CSS로 가로 배치 + 오른쪽 붙임 처리한다(theme.py 참고).
                    with st.container(key=f"reg_step_actions_{i}"):
                        if st.button(":material/edit:", key=f"reg_step_edit_{i}", help="수정"):
                            st.session_state.reg_step_editing_idx = i
                            st.rerun()
                        if st.button(":material/delete:", key=f"reg_step_delete_{i}", help="삭제"):
                            reg["instructions"].pop(i)
                            st.rerun()

    # register_ingredients와 같은 이유로(2026-08-21) 텍스트 입력 전용으로 되돌렸다.
    # 2026-08-23 — register_ingredients와 같은 이유로 배경 마이크만 유지("취소"/"처음"만 반응).
    # 2026-08-25 — 그 listen_background_only() 호출 자체는 app.py::main()이 화면별 key
    # 컨테이너 밖에서 직접 부른다(위 파일 docstring 참고).

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
        # 2026-08-23 리포트(AppTest로 재현 확인) — register_recipe()의 "confirm" step은
        # session["current_recipe_id"]를 안 채우고 session["registration"]도 저장 직후
        # None으로 비운다(registration.py 참고). screen_complete()는 요리명을
        # st.session_state.recipe_view에서 읽는데(조회 때만 채워지는 값) 신규
        # 등록 플로우는 그걸 채운 적이 없어서, "저장이 완료됐어요!" 화면에 방금 등록한
        # 요리명 대신 기본값 "레시피"만 뜨는 버그가 있었다. register_recipe() 호출 전에
        # reg는 이미 dish_name을 들고 있는 지역 참조이므로(위 register_recipe() 호출이
        # session["registration"]을 None으로 바꿔도 reg 객체 자체는 그대로 살아있음),
        # 여기서 dish_name만 recipe_view에 최소한으로 채워 넘긴다 — recipe_id/steps 등
        # 나머지 필드가 없어도 screen_complete()는 dish_name만 읽으므로 안전하고, 이후
        # 실제 조회가 일어나면 refresh_recipe_view()가 이 임시 값을 통째로 덮어쓴다.
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
    # 2026-09-02 — docs/specs/private_recipe_visibility.md: 관리자 승인 대기 문구/배지를
    # 없앤다. 이제 저장 즉시 approved='Y'로 들어가고, 등록한 본인 계정으로는 바로
    # 조회된다(다른 사용자에게는 여전히 안 보임 — select_standard_recipe() 참고) —
    # "관리자 승인 후에 검색할 수 있어요"는 더 이상 사실이 아니라서 문구를 바꿨다.
    # 예전 배지(<span class="ce-status-badge">...심사 대기 중</span>)는 완전히 지우지
    # 않고 주석으로 남겨둔다(요청).
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
