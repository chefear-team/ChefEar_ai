"""STT -> LLM(요리명 추출) -> Supabase 조회 파이프라인을 눈으로 확인하기 위한 수동 테스트 화면."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np
import soundfile as sf
import streamlit as st


def main() -> None:
    st.set_page_config(page_title="ChefEar STT→LLM→DB 테스트", page_icon="🧪")
    st.title("STT → LLM(요리명 추출) → Supabase 조회 테스트")
    st.caption("음성 파일을 업로드하면 각 단계 결과를 그대로 보여줍니다. 마이크 테스트는 다음 단계.")

    from stt.infer import load_ct2_model
    from llm.infer import load_llm
    from tts.infer import load_tts_model

    with st.spinner("STT 모델 준비 중... (최초 1회만, 몇 초 걸릴 수 있음)"):
        load_ct2_model()

    with st.spinner("LLM(EXAONE) 모델 준비 중... (최초 1회는 다운로드로 몇 분 걸릴 수 있음)"):
        load_llm()

    with st.spinner("TTS(Qwen3-TTS) 모델 준비 중... (약 17초, 최초 1회만)"):
        load_tts_model()

    audio_file = st.file_uploader("음성 파일 업로드 (wav/mp3/flac 등)")
    if audio_file is None:
        st.info("음성 파일을 올려주세요.")
        return

    st.audio(audio_file)

    # ============================================================
    # 1단계: STT
    # ============================================================
    st.header("1. STT")
    data, sample_rate = sf.read(audio_file)
    if data.ndim > 1:  # 스테레오면 모노로 (src/app.py의 listen()과 동일 처리)
        data = data.mean(axis=1)

    from stt.infer import stt_transcribe

    with st.spinner("STT 추론 중..."):
        text = stt_transcribe(data.astype(np.float32), sample_rate=sample_rate)

    if not text:
        st.error("STT가 텍스트를 못 뽑았어요(무음이거나 인식 실패, EC-01). 여기서 멈춥니다.")
        return
    st.success(f"STT 결과: {text!r}")

    # ============================================================
    # 2단계: LLM 요리명 추출
    # ============================================================
    st.header("2. LLM 요리명 추출 (EXAONE-3.5-2.4B-Instruct)")
    from orchestration.entity_extract_llm import extract_dish_name_llm

    with st.spinner("EXAONE 추론 중..."):  # 모델 로딩은 위 페이지 로드 시점 워밍업에서 이미 끝남
        dish_name = extract_dish_name_llm(text)

    if not dish_name:
        st.warning("LLM이 요리명을 찾지 못했어요(None) — 여기서 멈춥니다. 지어내지 않는 게 의도된 동작입니다.")
        return
    st.success(f"추출된 요리명: {dish_name!r}")

    # ============================================================
    # 3단계: Supabase 조회 (dish_name 매칭)
    # ============================================================
    st.header("3. Supabase 조회")
    from orchestration.db import get_client
    from orchestration.pipeline import get_precomputed_steps
    from orchestration.recipe_search import select_standard_recipe

    client = get_client()
    found = select_standard_recipe(dish_name, client=client)

    if not found:
        st.error(f"'{dish_name}'로 Supabase에서 못 찾았어요(표준 데이터 밖일 수 있음). 여기서 멈춥니다.")
        return
    st.success("매칭된 레시피")
    st.json(found)

    # ============================================================
    # 4단계: 조리순서 (recipe_steps)
    # ============================================================
    st.header("4. 조리순서 (recipe_steps)")
    steps_result = get_precomputed_steps(found["recipe_id"], client=client)
    if not steps_result.get("available"):
        st.warning(steps_result.get("message", "조리순서가 없어요."))
        return
    from orchestration.term_dict import resolve_for_display, resolve_for_tts

    for step in steps_result["steps"]:
        st.markdown(f"**{step['step_number']}.** {resolve_for_display(step['text'])}")

    # ============================================================
    # 5단계: TTS (1단계 안내를 음성으로) — src/app.py의 speak()와 동일한 호출 방식
    # ============================================================
    st.header("5. TTS 음성 출력")
    first_step_text = resolve_for_tts(steps_result["steps"][0]["text"])
    from tts.infer import tts_synthesize

    with st.spinner("TTS 합성 중..."):
        waveform, sample_rate = tts_synthesize(first_step_text)
    st.write(f"읽어주는 문장: {first_step_text!r}")
    st.audio(waveform, sample_rate=sample_rate)


if __name__ == "__main__":
    main()
