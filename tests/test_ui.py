"""STT -> LLM(요리명 추출) -> Supabase 조회 파이프라인을 눈으로 확인하기 위한 수동 테스트 화면.

pytest의 `test_*.py` 수집 규칙과 파일명이 겹치지만 이건 자동화 테스트가 아니다 — 아래 UI
빌드 코드는 `if __name__ == "__main__":` 가드 안에 있어서(`src/app.py`와 같은 패턴) pytest가
이 파일을 모듈로 import해도 아무 것도 실행하지 않고 그냥 지나간다(수집되는 test_ 함수 없음).

실행: streamlit run tests/test_ui.py

지금은 마이크가 아니라 "파일 업로드"로만 확인한다(요청대로 사람 목소리 마이크 테스트는
다음 단계). STT(업로드된 WAV) -> LLM(요리명 추출) -> DB 조회(dish_name 매칭 + 조리순서)
-> TTS(1단계 안내 음성 출력)까지 전체 사이클을 5단계로 나눠 화면에 그대로 보여줘서
어디서 끊기는지 바로 보이게 하는 게 목적이라, `src/app.py`처럼 화면을 다듬지 않고 각
단계를 순서대로 노출한다. Supabase 자격증명이 `.env`에 없으면 `db.get_client()`가
자동으로 mock 클라이언트로 동작한다(3단계부터는 mock 데이터 기준으로 확인하게 됨).
"""
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

    # STT/LLM 워밍업 — 둘 다 첫 로딩 비용이 있어서(원인은 서로 다름, 아래 참고) 파일
    # 업로드를 기다렸다가 그때 로딩을 시작하면 사용자가 업로드 직후 그 비용을 그대로
    # 보게 된다. 그래서 페이지가 뜨는 시점(스크립트 최초 실행)에 미리 로딩해둔다.
    # load_ct2_model()/load_llm() 둘 다 전역 캐시라서(stt/infer.py의 _ct2_model,
    # llm/infer.py의 _model) 이미 로드됐으면 즉시 반환 — 매 rerun(사용자 조작)마다
    # 이 줄을 다시 실행해도 안전하고 빠르다.
    #
    # STT: 처음엔 "CUDA 초기화가 느리다"고 짐작했으나(2026-08-20), 실측해보니 GPU/CPU
    # 사용률이 로딩 내내 0%였다 — 프로젝트 폴더가 네트워크 공유 드라이브(CIFS, ~9MB/s)에
    # 있어서 model.bin(778MB) 읽기 자체가 87초 걸렸던 것. .env의 STT_LOCAL_CACHE_DIR로
    # 로컬 디스크 사본을 우선 읽게 고쳐서 1.2초로 줄었다(`src/stt/infer.py` 참고).
    # LLM: EXAONE 가중치는 원래 ~/.cache/huggingface(로컬 디스크)에 캐시되므로 이 문제가
    # 없다 — 최초 1회 인터넷에서 받는 것만 느리고(수 분), 그다음부턴 13초 정도로 빠르다.
    # TTS: LLM과 마찬가지로 ~/.cache/huggingface에서 읽어서 네트워크 드라이브 문제는
    # 없다 — 7.9GB 모델이라 로딩 자체에 17초 정도 걸리는 게 정상(실측), 미리 안 해두면
    # 5단계(TTS 출력)에서 사용자가 그 17초를 그대로 기다리게 된다.
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
    for step in steps_result["steps"]:
        st.markdown(f"**{step['step_number']}.** {step['text']}")

    # ============================================================
    # 5단계: TTS (1단계 안내를 음성으로) — src/app.py의 speak()와 동일한 호출 방식
    # ============================================================
    st.header("5. TTS 음성 출력")
    first_step_text = steps_result["steps"][0]["text"]
    from tts.infer import tts_synthesize

    with st.spinner("TTS 합성 중..."):
        waveform, sample_rate = tts_synthesize(first_step_text)
    st.write(f"읽어주는 문장: {first_step_text!r}")
    st.audio(waveform, sample_rate=sample_rate)


if __name__ == "__main__":
    main()
