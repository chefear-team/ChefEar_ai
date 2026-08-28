"""ChefEar 신규 등록 플로우 화면(register_intro -> ... -> complete) —
src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

register_recipe()가 돌려주는 prompt/summary는 대화 중간(재료·순서 누적)에만 있고,
화면 전환 시점의 고정 안내문(인트로/순서 질문 등)은 없다 — 그 화면 자신이 자신의
안내문을 "무슨 말을 했는지" 알아야 voice_io._render_cached_speech()로 같은 캐시를
다시 찾을 수 있어서, 전환 직전(호출부)과 도착 화면 양쪽이 똑같이 이 함수들을 불러 쓴다.
(register_intro 자체는 2026-08-21부터 음성 안내를 뺐다 — 아래 screen_register_intro()
참고.)

2026-08-25 — listen()/listen_background_only() 호출은 이 파일의 화면 함수들이 아니라
app.py::main()이 화면별 key 컨테이너 *밖에서* 직접 부른다(cooking.py 상단 주석/app.py
주석 참고 — 화면 key 컨테이너가 바뀔 때마다 그 안의 webrtc 컴포넌트가 재마운트돼 마이크가
화면 전환마다 새로 연결되는 문제 대응). process_utterance()로 충분한 화면은 별도 핸들러가
없고, 문자열을 직접 비교하는 화면(register_intro/register_dish_name)만 handle_*() 함수를
따로 둔다.
"""
from __future__ import annotations

import streamlit as st

from theme import (
    ICON_CHECK_CIRCLE,
    ICON_CHECK_SMALL,
    ICON_QUESTION_CIRCLE,
    ICON_SPARKLE,
    render_back_link,
    render_chips,
    render_dots,
    render_mic_bar,
    render_spacer,
)
from orchestration.db import get_client
from orchestration.registration import register_recipe
from ui.dispatch import fallback_buttons, is_home_word, reset_to_start
from ui.session import goto
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


def screen_register_intro() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon neutral">{ICON_SPARKLE}</div>', unsafe_allow_html=True)
    dish_hint = st.session_state.pending_dish_name or "그 요리"
    st.markdown(
        '<div class="ce-center"><h1>표준 레시피에 없는 요리예요</h1>'
        f"<p>{dish_hint}는 표준 레시피 안에는 없지만, 직접 알려주시면 회원님 레시피로 등록해드릴게요.</p></div>",
        unsafe_allow_html=True,
    )
    render_spacer()
    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"네" 또는 "등록할래요"라고 말해보세요',
        listening=_mic_ready,
    )

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 아래 handle_register_intro()에
    # 넘긴다(위 파일 docstring 참고). 텍스트로 "네, 등록할래요"/"괜찮아요"를 입력하는
    # 대체 경로는 그대로 남아있다.

    c1, c2 = st.columns(2)
    with c1:
        if st.button("네, 등록할래요", type="primary", use_container_width=True):
            goto("register_dish_name")
    with c2:
        if st.button("괜찮아요", use_container_width=True):
            goto("start")


def handle_register_intro(text: str) -> None:
    """screen_register_intro()가 그려진 뒤 app.py가 잡아온 발화를 처리한다.

    2026-08-27 수정 — "네"/"좋아"/"응"/"등록"이라고 말해도 등록 페이지로 안 넘어간다는
    실측 리포트. 원인: `norm in (...)` 완전일치 조건이라, STT가 조사/어미를 붙여
    돌려주면(실측 로그: "등록할래.", "등록한다고.", "둘록한다니까?" 등) 후보 목록
    어느 것과도 정확히 안 맞아 전부 else(무시)로 빠졌다. dispatch.py의 `_REGISTER_WORD
    in text`(등록은 단어 포함이면 무조건)와 같은 방식으로 포함 여부 검사로 완화한다.
    부정(아니/괜찮아/취소/처음) 쪽을 먼저 검사해서, "아니 등록 안 할래"처럼 부정과
    긍정 단어가 한 문장에 같이 들어간 경우 부정이 우선하게 한다 — 순서를 반대로 하면
    "등록"이 먼저 걸려 거절 의사를 등록 확정으로 잘못 처리할 위험이 있다.

    "좋"(어간, "좋아"의 활용형 전부 포함) 단독 포함 검사는 cooking.py::handle_recipe_confirm()이
    이미 쓰는 것과 같은 트레이드오프다 — "좋다고?"처럼 STT가 변형해 돌려줘도 잡히게
    하려는 목적인데, 이 화면 문맥과 무관한 발화("날씨 좋다" 등)에 우연히 "좋"이 들어
    있어도 등록으로 오인식될 이론적 여지가 있다. 이 화면은 "등록할지" 확인 직후에만
    잠깐 나타나는 좁은 화면이라 실사용상 위험은 낮다고 보고 기존 관례를 그대로 따른다.
    """
    norm = text.strip().rstrip("?!. ")
    if is_home_word(norm) or any(word in norm for word in ("아니", "괜찮아", "취소")):
        # 2026-08-23 — "처음"류는 reset_to_start()(진행 중이던 값 전부 초기화)로,
        # 기존 "아니/취소"는 원래 하던 대로 단순 이동만(이 화면은 아직 등록 자체를
        # 시작 전이라 초기화할 진행 상태가 없음).
        if is_home_word(norm):
            reset_to_start()
        else:
            goto("start")
    elif any(word in norm for word in ("네", "응", "좋", "그래", "등록")):
        goto("register_dish_name")
    else:
        # 2026-08-25 추가 — dispatch.py의 "미분류" 분기와 같은 이유(그쪽 주석 참고).
        # 위 두 분기 다 goto()로 화면을 다시 그리며 listen()을 재호출해 마이크 드레인
        # 루프를 이어가는데, 이 무시 케이스만 rerun 없이 끝나서 그 순간부터 프레임이
        # 안 비워져 "Queue overflow"로 이어졌다.
        st.rerun()


def screen_register_dish_name() -> None:
    """FR-06 1단계: 요리명 질문. 다른 경로(LLM wants_register 등)에서 넘어온
    추측값(pending_dish_name)을 그대로 쓰지 않고 사용자가 직접 확인/수정하게 한다 —
    규칙 기반 추출은 틀릴 수 있어서
    (entity_extract.py 참고) 등록처럼 DB에 실제로 남는 데이터는 검증 없이 넘기면 안 된다."""
    if render_back_link("처음 화면으로"):
        goto("start")
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
        if st.button("취소", use_container_width=True):
            goto("register_intro")


def handle_register_dish_name(text: str) -> None:
    """screen_register_dish_name()이 그려진 뒤 app.py가 잡아온 발화를 처리한다."""
    norm = text.strip().rstrip("?!. ")
    if is_home_word(norm):
        # 2026-08-23 추가 — 이 체크가 없으면 "처음"이라고 말해도 요리명("처음")으로
        # 그대로 등록 시도돼버린다(아래가 "확정 단어 아니면 발화 전체를 요리명으로"
        # 라서). 등록 도중이니 reset_to_start()로 진행 중이던 값도 같이 비운다.
        reset_to_start()
        return
    if norm in ("취소", "취소할래", "취소할래요", "취소해줘"):
        goto("register_intro")
        return
    if norm in ("네", "응", "맞아", "맞아요", "그래", "그래요", "좋아", "좋아요"):
        # 짐작한 이름이 있으면 그걸 확정, 없으면 요리명을 안 말한 것이므로 다시 묻는다
        # (예전엔 pending 없을 때 "네"가 그대로 요리명으로 등록됐다).
        if st.session_state.pending_dish_name:
            dish_name = st.session_state.pending_dish_name
        else:
            st.rerun()
            return
    # 2026-08-28 추가 — 이 화면은 확정어가 아닌 발화를 전부 요리명으로 받는데, STT
    # 오인식이나 "어 잘 모르겠는데 아 된장찌개" 같은 중얼거림까지 그대로 DB에 등록돼
    # 버린다(리뷰 지적, 되돌릴 방법도 전체 리셋뿐). 실제 요리명은 공백 제거 후에도
    # 25자를 거의 안 넘는다(compound도 "소고기무국" 수준) — 그보다 길면 문장을
    # 말한 것으로 보고 요리명으로 확정하지 않고 다시 묻는다(화면 유지 + rerun).
    elif len(norm.replace(" ", "")) > 25:
        st.rerun()
        return
    else:
        dish_name = text.strip()
    # 2026-08-21: 여기서 speak(result["prompt"])로 음성 합성을 하고 있었지만, 그
    # 재생 위젯은 바로 뒤 goto()의 st.rerun()에 지워지고, 도착 화면인
    # register_ingredients는 텍스트 입력 전용(마이크 바·재생바 없음)이라 이 안내문을
    # _render_cached_speech()로 다시 보여주지도 않는다. chat_log에도 남지만 등록
    # 화면들은 render_chat()을 안 써서 그것도 어차피 안 보인다 — 즉 매번 로컬 CPU로
    # 몇 분씩 걸리는 합성을 하고도 아무도 못 듣는 죽은 호출이라 제거했다.
    register_recipe(st.session_state.pipeline_session, "dish_name", dish_name, client=get_client())
    goto("register_ingredients")


def screen_register_ingredients() -> None:
    reg = st.session_state.pipeline_session.get("registration")
    if not reg:
        goto("register_intro")
        return

    if render_back_link("처음 화면으로"):
        goto("start")
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
        st.session_state.reg_ing_turn = _ing_turn + 1
        st.rerun()

    if reg["ingredients"] and st.button("네, 맞아요", type="primary", use_container_width=True):
        goto("register_steps")


def screen_register_steps() -> None:
    reg = st.session_state.pipeline_session.get("registration")
    if not reg:
        goto("register_intro")
        return

    if render_back_link("처음 화면으로"):
        goto("start")
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
        register_recipe(st.session_state.pipeline_session, "confirm", None, client=get_client())
        st.session_state.recipe_view = {"dish_name": dish_name}
        speak(_REGISTER_SAVED_MESSAGE, hidden=True)
        goto("complete")


def screen_complete() -> None:
    # 2026-08-27 — 관리자 승인(Y/N) 워크플로우 도입으로 문구 갱신. 예전엔 owner_id
    # 기반 개인화("회원님 버전으로 먼저 안내") + 즉시 조회 가능을 전제로 한 문구였는데,
    # 이제 신규 등록은 관리자가 승인하기 전까진 아무도(등록한 사람 포함) 조회할 수
    # 없다(admin_recipe_approval.md 참고) — 그 사실을 정직하게 안내한다.
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    render_spacer()
    # 2026-08-28 — 화면 본문 전체를 화면 전용 key 컨테이너로 감싼다. "처음으로" 발화로
    # start로 넘어갈 때, 이 화면의 아이콘·제목·배지·오디오가 st.button("처음 화면으로")
    # (유일하게 _STALE_CONTENT_MARKERS로 잡히는 요소, 그런데 맨 마지막이라 "꼬리 제거"가
    # 자기 자신만 지움)보다 앞에 그려져서 잔상으로 남았다(Streamlit #8360). theme.py의
    # _SINGLE_OWNER_WIDGET_KEYS("complete_card": "complete")에 등록해 ruleSingleOwnerWidgets()
    # 가 이 컨테이너 전체를 구조적으로(텍스트 무관) 숨기게 한다. render_spacer()는 수직
    # 중앙정렬(flex:1)을 유지하려고 래퍼 밖에 둔다. cooking_complete도 동일 패턴.
    with st.container(key="complete_card"):
        st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="ce-center"><h1>저장이 완료됐어요!</h1>'
            f"<p>{dish_name}, 관리자 승인 후에 검색할 수 있어요.</p></div>",
            unsafe_allow_html=True,
        )
        _render_cached_speech(_REGISTER_SAVED_MESSAGE)
        st.markdown(
            '<div style="text-align:center;">'
            f'<span class="ce-status-badge">{ICON_CHECK_SMALL} 심사 대기 중</span></div>',
            unsafe_allow_html=True,
        )
        if st.button("처음 화면으로", type="primary", use_container_width=True):
            reset_to_start()
    render_spacer()

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 process_utterance()에 그대로
    # 넘긴다 — 이 화면은 별도 핸들러가 없다(위 파일 docstring 참고).
