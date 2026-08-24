"""② 레시피 확인 화면 - FR-05: 조회수 1위 표준 레시피 자동 채택, 되묻지 않음."""
import streamlit as st

from mock_data import fresh_recipe
from nav import goto
from theme import render_back_link, render_badge, render_chips, render_mic_bar, render_section_title


def _dish_name_with_josa(dish_name: str) -> str:
    """"~(으)로 만들어볼까요?" 조사를 마지막 글자 받침 유무로 고른다(받침 없음/ㄹ받침 → "로",
    그 외 받침 → "으로" - 한국어 로/으로 조사 규칙)."""
    if not dish_name:
        return dish_name
    code = ord(dish_name[-1]) - 0xAC00
    if 0 <= code <= 11171:
        jong = code % 28
        particle = "로" if jong in (0, 8) else "으로"
    else:
        particle = "로"
    return f"{dish_name}{particle} 만들어볼까요?"


def _start_cooking(recipe: dict) -> None:
    """"응, 시작할게요 (테스트)" 버튼을 누르면 실행되는 실제 동작."""
    st.session_state.recipe = recipe
    st.session_state.step_number = 1
    st.session_state.substituted_ingredient = None
    st.session_state.chat_log = []
    st.session_state.pending_real_recipe = None  # 다 썼으니 정리(다음 진입 때 stale 값 방지)
    goto("cooking_step")


def render() -> None:
    if render_back_link("처음으로"):
        goto("start")

    # 2026-08-20: start.py의 텍스트 입력이 진짜 Supabase 조회에 성공하면 여기에
    # mock_data.fresh_recipe()와 같은 모양의 dict를 미리 채워둔다 — 있으면 그걸
    # 우선 쓰고(진짜 데이터), 없으면 기존처럼 힌트 카드용 mock_data를 쓴다.
    #
    # 여기서 바로 .pop()(꺼내면서 지우기)하면 안 된다 — st.button()을 누르면
    # Streamlit이 이 render() 전체를 처음부터 다시 실행하는데, 그 재실행 시점엔
    # 이미 위쪽 코드가 한 번 더 지나가면서 pending_real_recipe를 지워버린 뒤라
    # "응, 시작할게요"가 실제로 recipe에 담을 값이 사라져 있다(실측 확인,
    # 2026-08-20 — 그래서 대신 doenjang 기본 목업으로 넘어가버리는 버그가 있었음).
    # 그래서 여기선 그냥 읽기만(get) 하고, 실제로 다 쓴 시점(아래 버튼 클릭 안)에서만 지운다.
    recipe = st.session_state.get("pending_real_recipe")
    if recipe is None:
        recipe_key = st.session_state.get("pending_recipe_key") or "doenjang"
        recipe = fresh_recipe(recipe_key)

    render_badge("조회수 1위 표준 레시피 자동 선택 · 되묻지 않음 (FR-05)")

    # 2026-08-20: "나: ~ 어떻게 만들어? / ChefEar: ~ 레시피를 찾았어요. 이걸로
    # 시작할까요?" 대화 말풍선 구역을 없애고, 그 자리를 대신하던 "재료 미리보기" 위
    # 큰 제목에 "(으)로 만들어볼까요?" 문구를 합쳐서 한 곳에서 보여준다 — start.py
    # 제목과 같은 .ce-center h1 스타일을 그대로 재사용(새 CSS 추가 없음).
    st.markdown(
        f'<div class="ce-center"><h1>{_dish_name_with_josa(recipe["dish_name"])}</h1></div>',
        unsafe_allow_html=True,
    )

    render_section_title("재료 미리보기")
    render_chips(recipe.get("preview_ingredients", recipe["ingredients"]), show_qty=False)

    # 2026-08-20: "마이크로 말하기" 버튼을 눌러야 녹음이 시작되는 render_mic_bar_interactive()는
    # 안 쓴다 - 상시 마이크라면 버튼을 누르기 전부터 이미 "듣는 중"이어야 앞뒤가 맞는데,
    # 그 버튼이 있으면 오히려 평소엔 안 듣고 있다는 뜻이 돼버린다(사용자 지적). 실제 STT
    # 연결 전까지는 텍스트 입력 같은 대체 창구도 함께 없애고, 장식용 "듣는 중" 표시만 둔다.
    render_mic_bar("듣는 중", '"시작"이라고 말해보세요')

    # 아래 rc_footer_buttons가 하단에 고정(position:fixed)되면서 흐름에서 빠지는 만큼,
    # 마지막 콘텐츠(위 "듣는 중" 표시)가 그 밑에 가려지지 않도록 같은 높이의 여백을 미리 남겨둔다.
    st.markdown('<div style="height:130px;"></div>', unsafe_allow_html=True)

    with st.container(key="rc_footer_buttons"):
        if st.button("응, 시작할게요 (테스트)", type="primary", use_container_width=True):
            _start_cooking(recipe)

        if st.button("다른 레시피 찾을래요 (테스트)", use_container_width=True):
            st.session_state.pending_real_recipe = None
            goto("start")
