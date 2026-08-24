"""① 시작 화면 - FR-01: 숫자 메뉴 없이 자유발화 유도.

ui/html/01_start.html과 문구·구성 순서를 그대로 맞췄다(브랜드 → 여백 → 인사말+예시 문장
→ 큰 마이크 버튼 → "눌러서 말씀해주세요" → 힌트 카드 2개 → 여백). 힌트 카드의 "된장찌개
어떻게 만들어?" 부분처럼 글자색 일부만 다르게 주는 건 st.button 라벨(순수 텍스트만 지원)로는
불가능해서, 서식 있는 st.markdown으로 글씨를 그리고 그 위에 투명한 st.button을 정확히
겹쳐 클릭만 받는 방식을 쓴다(자세한 이유는 theme.py의 [class*="st-key-hint_chip"] 주석 참고).
"""
import re

import streamlit as st

from nav import goto
from theme import ICON_BASKET_SM, render_big_mic, render_spacer

TEXT_UTTERANCE_PLACEHOLDER = "예: 부대찌개 어떻게 만들어?"

HINT_CHIPS = [
    (
        "hint_chip_doenjang",
        '이렇게 말해보세요 — <span class="quote">“된장찌개 어떻게 만들어?”</span>',
        "이렇게 말해보세요 — 된장찌개 어떻게 만들어?",
        "doenjang",
        "된장찌개 어떻게 만들어?",
    ),
    (
        "hint_chip_budaejjigae",
        '실제 TTS 음성 데모 — <span class="quote">“부대찌개 어떻게 만들어?”</span>',
        "실제 TTS 음성 데모 — 부대찌개 어떻게 만들어?",
        "budaejjigae",
        "부대찌개 어떻게 만들어?",
    ),
    (
        "hint_chip_register",
        '등록된 레시피가 없는 경우 예시 — <span class="quote">“문어초무침 어떻게 만들어?”</span>',
        "등록된 레시피가 없는 경우 예시 — 문어초무침 어떻게 만들어?",
        None,
        "문어초무침 어떻게 만들어?",
    ),
]


def _ingredients_text_to_chips(raw_text: str) -> list[dict]:
    """DB 원문 재료 텍스트("[재료] 김치 1/4밥공기(1줌)| 비엔나 20개| ... [양념] 된장...")를
    render_chips()가 기대하는 [{"name":, "emoji":}, ...] 형태로 최대한 단순하게 바꾼다.

    수량을 이름에서 분리해내는 정교한 파싱은 하지 않는다 — 재료가 "[재료] 이름 수량|
    이름 수량..." 처럼 자유 형식 텍스트로만 저장돼 있어서(6.1/6.2, 원문 그대로 저장하기로
    한 팀 결정), 이름/수량을 확실하게 나누려면 별도 파서가 필요하다. 지금은 "|"로 나눈
    한 덩어리를 그대로 하나의 chip 이름으로 보여준다("[재료]"/"[양념]" 같은 대괄호 구간
    표시도 그냥 짧은 chip 하나로 같이 보여짐 — 정보 손실 없이 원문 그대로 노출하는 셈).
    """
    segments = [s.strip() for s in re.split(r"\|", raw_text) if s.strip()]
    return [{"name": segment, "emoji": ICON_BASKET_SM} for segment in segments]


def _handle_start_text_utterance(utterance: str) -> None:
    """실제 마이크(STT) 대신, 텍스트 입력을 STT가 인식한 결과인 것처럼 그대로
    orchestration.pipeline.handle_utterance()에 넣는다(2026-08-20, STT/TTS 텍스트
    테스트 화면과 같은 방식). 조회에 성공하면 recipe_confirm 화면이 기대하는
    모양(mock_data.fresh_recipe()와 같은 키)으로 바꿔서 pending_real_recipe에 담고
    이동한다 — recipe_confirm.py/cooking_step.py를 그대로 재사용하기 위해서다.
    """
    from orchestration.db import get_client  # 지연 import, stt_tts_test.py와 같은 이유
    from orchestration.pipeline import get_precomputed_steps, handle_utterance

    if "real_client" not in st.session_state:
        st.session_state.real_client = get_client()
    client = st.session_state.real_client

    result = handle_utterance({}, utterance, client=client)

    if result.get("intent") != "조회" or "recipe_id" not in result:
        st.session_state.start_utterance_error = result.get("message") or "이해하지 못했어요. 다시 말씀해주세요."
        return

    steps_result = get_precomputed_steps(result["recipe_id"], client=client)
    if not steps_result.get("available"):
        st.session_state.start_utterance_error = steps_result.get("message") or "조리순서를 찾을 수 없어요."
        return

    st.session_state.pending_real_recipe = {
        "id": result["recipe_id"],
        "dish_name": result["dish_name"],
        "view_count": result.get("view_count", 0),
        "intro": f"'{result['dish_name']}' 레시피를 찾았어요.",
        "ingredients": _ingredients_text_to_chips(result.get("ingredients", "")),
        "steps": [{"text": s["text"]} for s in steps_result["steps"]],
        "source": "supabase",
    }
    st.session_state.chat_log = [("user", utterance)]
    st.session_state.start_utterance_error = None
    goto("recipe_confirm")


def render() -> None:
    render_spacer()

    st.markdown(
        '<div class="ce-center">'
        "<h1>무엇을 만들고 싶으세요?</h1>"
        "<p>숫자 메뉴 없이, 하고 싶은 말을 편하게 그대로 말씀해주세요.</p>"
        '<p style="color:var(--text-faint); font-size:13.5px;">예: “된장찌개 어떻게 만들어?”</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    audio = render_big_mic()
    if audio is not None:
        st.info("녹음을 받았어요. STT 연결은 아직 준비 중이라 실제 음성 인식은 안 돼요 (src/ui/README.md 참고).")

    # 마이크(STT)가 아직 실시간으로 안 붙어있어서, 텍스트 입력이 발화를 대신한다
    # (2026-08-20). 여기서 조회에 성공하면 진짜 Supabase 데이터로 recipe_confirm ->
    # cooking_step까지 그대로 이어진다 — 아래 힌트 카드(mock_data)와는 별개 경로.
    with st.form("start_text_utterance_form", clear_on_submit=True):
        text_utterance = st.text_input(
            "텍스트로 말씀해주세요", placeholder=TEXT_UTTERANCE_PLACEHOLDER, label_visibility="collapsed"
        )
        text_submitted = st.form_submit_button("전송", use_container_width=True)
    if text_submitted and text_utterance.strip():
        _handle_start_text_utterance(text_utterance.strip())
    if st.session_state.get("start_utterance_error"):
        st.warning(st.session_state.start_utterance_error)
        st.session_state.start_utterance_error = None

    for key, styled_html, accessible_label, recipe_key, utterance in HINT_CHIPS:
        with st.container(key=key):
            st.markdown(f'<div class="ce-hint-chip">{styled_html}</div>', unsafe_allow_html=True)
            if st.button(accessible_label, use_container_width=True):
                st.session_state.chat_log = [("user", utterance)]
                if recipe_key:
                    st.session_state.pending_recipe_key = recipe_key
                    goto("recipe_confirm")
                else:
                    goto("register_intro")

    render_spacer()
    st.divider()
    st.caption("아래는 mock_data가 아니라 진짜 Supabase 백엔드에 연결된 개발용 테스트 화면입니다.")
    if st.button("🧪 텍스트로 STT/TTS 테스트하기", use_container_width=True):
        goto("stt_tts_test")
