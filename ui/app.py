"""ChefEar 화면 프로토타입 - Streamlit 진입점.

실행: streamlit run ui/app.py

src/app.py(진짜 배포 엔트리포인트)는 orchestration.pipeline·stt/infer.py·tts/infer.py가
갖춰져야 실제로 동작한다(아직 미완성, src/ui/README.md 참고). 이 파일은 그 세 조각을
기다리지 않고 화면 흐름과 상태 전이(FR-03 다음/다시/이전, FR-04 재료 대체, FR-06 신규 등록)를
mock_data.py의 가짜 데이터로 먼저 보여주기 위한 별도의 화면 프로토타입이다.
"""
import sys
import time
from pathlib import Path

import streamlit as st

# stt_tts_test.py 화면 하나만 예외로 orchestration.pipeline(진짜 백엔드)을 그대로 쓴다
# (다른 화면들은 전부 mock_data.py). src/를 import 경로에 추가해야
# `from orchestration.db import get_client` 같은 import가 풀린다 —
# load_data.py/tests/conftest.py와 동일한 패턴.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from streamlit_screens import (
    complete,
    cooking_step,
    no_match,
    recipe_confirm,
    register_dish_name,
    register_ingredients,
    register_intro,
    register_steps,
    start,
    stt_tts_test,
    substitution_confirm,
    unclassified,
)
from nav import goto
from theme import inject_css, render_brand, render_loading_screen

SCREENS = {
    "start": start.render,
    "recipe_confirm": recipe_confirm.render,
    "cooking_step": cooking_step.render,
    "substitution_confirm": substitution_confirm.render,
    "no_match": no_match.render,
    "register_intro": register_intro.render,
    "register_dish_name": register_dish_name.render,
    "register_ingredients": register_ingredients.render,
    "register_steps": register_steps.render,
    "complete": complete.render,
    "unclassified": unclassified.render,
    "stt_tts_test": stt_tts_test.render,
}

DEFAULT_STATE = {
    "screen": "start",
    "recipe": None,
    "step_number": 1,
    "chat_log": [],
    "substituted_ingredient": None,
    "pending_recipe_key": None,
    "register_data": None,
}


def init_state() -> None:
    for key, value in DEFAULT_STATE.items():
        st.session_state.setdefault(key, value)


def main() -> None:
    st.set_page_config(
        page_title="ChefEar", page_icon="🍲", layout="centered", initial_sidebar_state="collapsed"
    )
    init_state()
    inject_css()
    render_brand()

    screen_name = st.session_state.screen

    # goto()가 화면을 바꾸며 켜둔 신호를 여기서 소비(pop)한다 - 이번 rerun에서는 실제
    # 화면 대신 스피너만 잠깐 보여주고, 눈에 보일 만큼(0.5초) 대기한 뒤 다시 rerun해서
    # 그 다음 rerun에는 신호가 꺼져 있으니 실제 화면이 정상적으로 그려진다(2026-08-20,
    # "화면마다 로딩화면" 요청 - 특히 진짜 백엔드 호출로 전환이 느려질 때 빈 화면처럼
    # 안 보이게 함).
    if st.session_state.pop("_screen_loading", False):
        render_loading_screen()
        time.sleep(0.5)
        st.rerun()
        return

    SCREENS[screen_name]()

    with st.sidebar:
        st.markdown("**화면 바로가기 (개발용)**")
        for name in SCREENS:
            if st.button(name, key=f"jump_{name}", use_container_width=True):
                goto(name)


if __name__ == "__main__":
    main()
