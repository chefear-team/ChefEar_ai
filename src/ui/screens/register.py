"""ChefEar 신규 등록 플로우 화면(no_match -> register_intro -> ... -> complete) —
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
    ICON_X_CIRCLE,
    render_back_link,
    render_badge,
    render_chat,
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


def screen_no_match() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon warn">{ICON_X_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>이 조합의 레시피는 없어요</h1>'
        "<p>요리명과 재료 내용, 두 가지 기준으로 모두 찾아봤지만 없어서 정직하게 말씀드려요.</p></div>",
        unsafe_allow_html=True,
    )
    chat_log = st.session_state.chat_log
    if chat_log and chat_log[-1][0] == "ai":
        # dispatch.py가 이 화면으로 넘어오기 직전 speak(..., hidden=True)로 미리 합성/캐싱만
        # 해둔 문구를 여기서 다시 찾아 들려준다(2026-08-22 리포트 — 화면 전환 중 재생바가
        # "떴다 사라짐" 깜빡이는 문제, recipe_confirm과 같은 패턴).
        _render_cached_speech(chat_log[-1][1])
    render_chat(st.session_state.chat_log[-2:])
    st.caption("실데이터 검색만으로 판단해요 — 없는 레시피를 지어내지 않아요 (1.5 원칙).")
    render_spacer()

    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.pipeline_session.get("current_recipe_id") and st.button(
            "원래 레시피로 계속하기", type="primary", use_container_width=True
        ):
            goto("cooking_step")
    with c2:
        # 2026-08-25 요청 — 등록은 owner_id가 있어야 "내가 등록한 레시피"로 걸러지는
        # 로그인 계정 기준 기능이라(get_owner_id() 문서 참고), 로그인 안 한 상태에서
        # 버튼을 눌러 register_intro까지 갔다가 결국 등록 자체가 익명으로만 처리되는
        # 혼란을 막기 위해 로그인 여부로 버튼을 활성/비활성화한다.
        is_logged_in = st.session_state.current_user is not None
        if st.button("새 레시피로 등록할래요", use_container_width=True, disabled=not is_logged_in):
            goto("register_intro")
    if not is_logged_in:
        # 2026-08-25 요청 — st.caption()은 회색 잔글씨라 눈에 잘 안 띈다는 지적으로,
        # "조회수 1위 표준 레시피 자동 선택" 등에 이미 쓰는 강조 배지(.ce-badge, 은은한
        # 강조색 알약 모양)로 바꿔서 눈에 띄게 한다.
        render_badge("로그인을 하시면 레시피를 등록할 수 있어요.")

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 아래 handle_no_match()에 넘긴다.


def handle_no_match(text: str) -> None:
    """screen_no_match()가 그려진 뒤 app.py가 잡아온 발화를 처리한다.

    2026-08-25 추가 — 원래는 다른 화면들처럼 process_utterance()(classify_intent()
    전체 파이프라인)를 그대로 써서, 이 화면에서 아무 말이나 해도 배경 스레드(LLM/DB
    조회)가 돌면서 로딩 팝업("다음으로 넘어가고 있어요...")이 뜨고, 심지어 "다른
    레시피 알려줘"처럼 재조회 시도로 이어질 수도 있었다. 이 화면은 요리명+재료 둘
    다로 이미 못 찾은 상태라 여기서 또 조회를 시도할 필요가 없다는 요청(2026-08-25)으로,
    아주 좁은 키워드 몇 개만 문자열로 직접 비교하는 구조로 바꿨다 — recipe_confirm/
    register_intro와 같은 패턴. 아래 네 가지 외의 모든 발화는 배경 작업을 전혀 안
    띄우므로(=process_utterance() 자체를 안 부름) 로딩 팝업도 안 뜨고, DB 조회도
    전혀 안 일어난다.
    """
    norm = text.strip().rstrip("?!.,~ ")
    # 2026-08-25 재요청 — "다른 레시피 알려줘"류(is_lookup_like()) 인식 분기를 없애고
    # "초기"/"등록" 두 키워드만 반응하도록 더 좁혔다(다른 발화는 전부 무시). "등록"은
    # 로그인 계정이 있을 때만 실제로 이동시킨다 — "새 레시피로 등록할래요" 버튼이
    # 로그인 여부로 활성/비활성화되는 것과 음성 경로를 똑같이 맞춘다(screen_no_match()
    # 참고, 안 그러면 버튼은 막혀있는데 음성으로는 뚫리는 불일치가 생김).
    if is_home_word(norm) or "처음" in norm:
        # is_home_word()의 _HOME_WORDS(dispatch.py)에 "초기"/"초기화면"/"초기 화면"/
        # "초기화"가 이미 다 들어있어서(2026-08-25 이전에 추가됨) "초기"는 이 한 줄로
        # 이미 잡힌다 — 별도 분기 불필요.
        reset_to_start()
    elif "등록" in norm:
        if st.session_state.current_user is not None:
            goto("register_intro")
        else:
            # 로그인 안 한 상태의 "등록" 발화는 무시(로그인하라고 화면에 이미 캡션으로
            # 안내돼 있음, screen_no_match() 참고) — 아래 else와 같은 이유로 rerun만.
            st.rerun()
    else:
        # dispatch.py의 "미분류" 분기와 같은 이유(그쪽 주석 참고) — 화면은 그대로 두고
        # rerun만 걸어서 마이크 드레인 루프가 끊기지 않게 한다. 이 분기는 애초에
        # process_utterance()를 부른 적이 없어서 로딩 팝업이 뜬 적도 없다.
        st.rerun()


def screen_unclassified() -> None:
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon warn">{ICON_QUESTION_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>잘 이해하지 못했어요</h1>'
        "<p>죄송해요, 다시 한번 말씀해주시겠어요? 안 될 때는 아래 버튼으로도 진행할 수 있어요.</p></div>",
        unsafe_allow_html=True,
    )
    chat_log = st.session_state.chat_log
    if chat_log and chat_log[-1][0] == "ai":
        # screen_no_match()와 같은 이유(2026-08-22) — dispatch.py의 hidden=True speak()가
        # 미리 캐싱해둔 문구를 여기서 다시 들려준다.
        _render_cached_speech(chat_log[-1][1])
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
            get_owner_id()
            goto("register_dish_name")
    with c2:
        if st.button("괜찮아요", use_container_width=True):
            goto("start")


def handle_register_intro(text: str) -> None:
    """screen_register_intro()가 그려진 뒤 app.py가 잡아온 발화를 처리한다."""
    norm = text.strip().rstrip("?!. ")
    if norm in ("네", "응", "좋아", "좋아요", "그래", "그래요", "등록", "등록할래요", "네, 등록할래요"):
        get_owner_id()
        goto("register_dish_name")
    elif is_home_word(norm) or norm in ("아니", "아니요", "괜찮아", "괜찮아요", "취소"):
        # 2026-08-23 — "처음"류는 reset_to_start()(진행 중이던 값 전부 초기화)로,
        # 기존 "아니/취소"는 원래 하던 대로 단순 이동만(이 화면은 아직 등록 자체를
        # 시작 전이라 초기화할 진행 상태가 없음).
        if is_home_word(norm):
            reset_to_start()
        else:
            goto("start")
    else:
        # 2026-08-25 추가 — dispatch.py의 "미분류" 분기와 같은 이유(그쪽 주석 참고).
        # 위 두 분기 다 goto()로 화면을 다시 그리며 listen()을 재호출해 마이크 드레인
        # 루프를 이어가는데, 이 무시 케이스만 rerun 없이 끝나서 그 순간부터 프레임이
        # 안 비워져 "Queue overflow"로 이어졌다.
        st.rerun()


def screen_register_dish_name() -> None:
    """FR-06 1단계: 요리명 질문. no_match에서 넘어온 추측값(pending_dish_name)을
    그대로 쓰지 않고 사용자가 직접 확인/수정하게 한다 — 규칙 기반 추출은 틀릴 수 있어서
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
    if norm in ("네", "응", "맞아", "맞아요", "그래", "그래요") and st.session_state.pending_dish_name:
        dish_name = st.session_state.pending_dish_name
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

    new_item = st.text_input("재료 추가(쉼표로 여러 개 가능)", key="reg_ing_new", placeholder="예: 두부, 감자")
    if st.button("추가") and new_item.strip():
        items = [x.strip() for x in new_item.split(",") if x.strip()]
        register_recipe(st.session_state.pipeline_session, "ingredients", items, client=get_client())
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

    new_step = st.text_input("순서 추가", key="reg_step_new", placeholder="새 단계 추가")
    if st.button("단계 추가") and new_step.strip():
        register_recipe(st.session_state.pipeline_session, "instructions", [new_step.strip()], client=get_client())
        st.rerun()

    if reg["instructions"] and st.button("네, 저장할게요", type="primary", use_container_width=True):
        # 2026-08-23 리포트(AppTest로 재현 확인) — register_recipe()의 "confirm" step은
        # session["current_recipe_id"]를 안 채우고 session["registration"]도 저장 직후
        # None으로 비운다(registration.py 참고). screen_complete()는 요리명을
        # st.session_state.recipe_view에서 읽는데(조회/재료대체 때만 채워지는 값) 신규
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
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ce-center"><h1>저장이 완료됐어요!</h1>'
        f"<p>{dish_name}, 다음에 다시 찾으면 회원님 버전으로 먼저 안내해드릴게요.</p></div>",
        unsafe_allow_html=True,
    )
    _render_cached_speech(_REGISTER_SAVED_MESSAGE)
    st.markdown(
        '<div style="text-align:center;">'
        f'<span class="ce-status-badge">{ICON_CHECK_SMALL} 나만의 레시피로 저장됨</span></div>',
        unsafe_allow_html=True,
    )
    render_spacer()

    if st.button("처음 화면으로", type="primary", use_container_width=True):
        reset_to_start()

    # 발화 처리는 app.py가 listen()으로 잡은 텍스트를 process_utterance()에 그대로
    # 넘긴다 — 이 화면은 별도 핸들러가 없다(위 파일 docstring 참고).
