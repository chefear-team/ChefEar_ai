"""③ 조리 진행 화면 (메인) - PRD 3.3 화면 구성, FR-02/FR-03/FR-04/FR-16을 실제로 동작시킨다.

전달받은 목업 이미지(된장찌개 3/5단계)를 기준으로 하되, [이전]/[다시]/[다음] 버튼은
docs/ChefEar_PRD_SDD_v0.8.md 7.1.1 상태 전이 규칙을 그대로 구현했다(정적 HTML 프로토타입과의
차이점 - 여기서는 st.session_state.step_number가 실제로 바뀐다).
"""
from pathlib import Path

import streamlit as st

from mock_data import fresh_recipe
from nav import goto
from theme import (
    render_badge,
    render_chips,
    render_mic_bar_interactive,
    render_section_title,
    render_step_card,
)

# 실제 음성이 있는 레시피(부대찌개, ui/assets/audio/budaejjigae/)는 render_step_card()에
# audio_path를 넘겨서 카드 안에 진짜 재생바(theme.render_audio_player(), .ce-player와
# 같은 모양의 커스텀 위젯)를 넣는다 — st.audio()는 브라우저 기본 재생바가 그대로 노출돼
# 앱 디자인과 안 맞아서 안 쓴다. 오디오가 없는 레시피는 장식용 정지 파형만 보여준다.
_AUDIO_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"


def _ensure_recipe() -> dict:
    if st.session_state.get("recipe") is None:
        st.session_state.recipe = fresh_recipe("doenjang")
        st.session_state.step_number = 1
    return st.session_state.recipe


def render() -> None:
    recipe = _ensure_recipe()
    steps = recipe["steps"]
    total = len(steps)
    step_number = min(st.session_state.step_number, total)
    current = steps[step_number - 1]

    render_badge(f'{recipe["dish_name"]} · {step_number} / {total} 단계')

    audio_file = current.get("audio")
    audio_path = _AUDIO_DIR / recipe["id"] / audio_file if audio_file else None
    has_prebaked_audio = audio_path is not None and audio_path.exists()

    # 2026-08-20: 진짜 Supabase 레시피(source="supabase", start.py의 텍스트 입력 경로로
    # 들어온 것)는 부대찌개처럼 미리 만들어둔 wav가 없다 — 대신 여기서 그때그때 합성해서
    # 같은 ui/assets/audio/<recipe id>/ 폴더에 캐싱한다(파일명만 "0N.wav" 대신
    # "{step_number:02d}.wav"). 한 번 만들면 다음에 이 단계로 돌아왔을 때 다시 안 만든다.
    is_supabase_recipe = recipe.get("source") == "supabase"
    realtime_audio_path = _AUDIO_DIR / str(recipe["id"]) / f"{step_number:02d}.wav" if is_supabase_recipe else None
    has_realtime_audio = realtime_audio_path is not None and realtime_audio_path.exists()

    if is_supabase_recipe and not has_prebaked_audio and not has_realtime_audio:
        # 부대찌개(미리 만들어둔 wav)처럼 버튼 없이 바로 재생바에 얹히길 원해서(2026-08-20),
        # 이 단계에 처음 들어온 시점에 곧바로 합성한다 — 로컬 CPU 기준 문장당 최대 몇 분
        # 걸릴 수 있어(2026-08-20 실측 239초/문장) 그 사이 스피너로 대기 안내만 해준다.
        # 한 번 만들면 realtime_audio_path에 캐싱돼서 이 단계로 다시 돌아왔을 때는 안 만든다.
        from tts.infer import tts_synthesize  # 지연 import — stt_tts_test.py와 같은 이유

        with st.spinner("음성 합성 중이에요... 로컬 CPU라 오래 걸릴 수 있어요(최대 몇 분). 잠시만 기다려주세요."):
            waveform, sample_rate = tts_synthesize(current["text"])
        import soundfile as sf

        realtime_audio_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(realtime_audio_path, waveform, sample_rate)
        has_realtime_audio = True

    if has_prebaked_audio:
        render_step_card(total, step_number, current["text"], audio_path=audio_path)
    elif has_realtime_audio:
        render_step_card(total, step_number, current["text"], audio_path=realtime_audio_path)
    else:
        render_step_card(total, step_number, current["text"], show_player=not is_supabase_recipe)

    if audio_file and not has_prebaked_audio:
        st.caption(f"⚠️ 음성 파일 없음: {audio_path.relative_to(_AUDIO_DIR.parent.parent)}")

    render_section_title("오늘의 재료")
    render_chips(recipe["ingredients"], substituted_name=st.session_state.get("substituted_ingredient"))

    audio_input = render_mic_bar_interactive('"다음" · "다시" · "재료 바꾸기"')
    if audio_input is not None:
        st.info("녹음을 받았어요. STT 연결은 아직 준비 중이라 실제 음성 인식은 안 돼요 (src/ui/README.md 참고).")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("이전", use_container_width=True):
            if step_number == 1:
                st.info("1단계예요, 이전 단계가 없어요 (AC-08).")
            else:
                st.session_state.step_number = step_number - 1
                st.session_state.chat_log = []
                goto("cooking_step")
    with c2:
        if st.button("다시", use_container_width=True):
            st.session_state.chat_log = []
            goto("cooking_step")
    with c3:
        if st.button("다음", use_container_width=True):
            if step_number < total:
                st.session_state.step_number = step_number + 1
                st.session_state.chat_log = []
                goto("cooking_step")
            else:
                goto("complete")

    st.divider()
    st.caption("아래 버튼들은 재료 대체·예외 상황 화면으로 이어지는 데모용 예시 발화입니다.")

    with st.container(key="cs_demo_buttons"):
        if recipe["id"] == "doenjang" and st.session_state.get("substituted_ingredient") != "양파":
            if st.button('🎙️ "감자 대신 양파 넣어도 돼?" (같은 레시피 안에서 1:1 대체)'):
                st.session_state.substituted_ingredient = "양파"
                st.session_state.chat_log = [("user", "감자 대신 양파 넣어도 돼?"), ("ai", "네, 양파로 대체했어요.")]
                goto("cooking_step")

        if st.button("🎙️ “바지락 넣어도 돼?” (다른 레시피로 교체 제안 예시)"):
            goto("substitution_confirm")

        if st.button("🎙️ “문어랑 성게 같이 넣어도 돼?” (매칭 실패 예시)"):
            goto("no_match")

        if st.button("음성 인식 실패 Fallback 예시 보기"):
            goto("unclassified")
