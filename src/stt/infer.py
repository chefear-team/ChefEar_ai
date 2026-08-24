"""
ChefEar STT Runtime / Evaluation

Base Model:
    openai/whisper-large-v3-turbo

QLoRA Adapter:
    leeony/chefear-stt-large-v3-turbo

핵심 처리 흐름
--------------
audio
→ Whisper STT
→ 단위 표기 정규화
→ 현재 레시피 재료 문맥이 있을 때만 고위험 패턴 조건부 보정
→ 최종 텍스트

중요
----
숫자를 무조건 변경하지 않습니다.

예:
    "소고기다짐 600그램"
        ↓

현재 레시피 재료에
    "소고기다짐육 100그램" 존재
그리고
    "소고기다짐육 600그램" 없음

위 조건을 모두 만족할 때만
    "소고기다짐육 100그램"
으로 보정합니다.
"""

from pathlib import Path
from typing import Optional, Sequence, Union

import os
import re
import threading

import librosa
import numpy as np
import pandas as pd
import torch

from jiwer import wer
from peft import PeftModel
from transformers import (
    BitsAndBytesConfig,
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

from orchestration.db import load_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# python-dotenv는 requirements-stt.txt(학습 전용)에만 있고 배포용 requirements.txt에는
# 없다 — src/tts/infer.py와 동일하게 orchestration.db.load_env()를 재사용해서 새 의존성
# 없이 .env를 읽는다(2026-08-19, tests/integration_issues_2026-08-18.md 이슈 #3 수정). 이
# import가 성립하려면 호출부가 미리 sys.path에 "src"를 넣어둬야 한다(tts/infer.py와 동일한
# 전제 — tests/conftest.py, tests/tts_stt_roundtrip_test.py가 이미 그렇게 하고 있음).
load_env()

# ============================================================
# 모델 설정
# ============================================================

MODEL_ID = "openai/whisper-large-v3-turbo"

HF_ADAPTER_ID = (
    os.environ.get("HF_STT_MODEL_REPO")
    or "leeony/chefear-stt-large-v3-turbo"
)


# 모델은 최초 1번만 로드하고 계속 재사용
_processor: Optional[WhisperProcessor] = None
_model = None
_input_dtype: Optional[torch.dtype] = None


# ============================================================
# 고위험 재료 사전
# ============================================================

# canonical:
# 실제 ChefEar에서 사용할 표준 재료명
#
# risky_patterns:
# STT 고위험군 테스트에서 실제 반복 확인된 표현
#
# 숫자는 여기에서 지정하지 않습니다.
# 숫자 보정 여부는 현재 레시피 문맥을 확인한 뒤 결정합니다.

HIGH_RISK_INGREDIENTS = {
    "소고기다짐육": [
        r"소고기\s*다짐육",
        r"소고기\s*다짐",
        r"소고기\s*다진",
    ],

    "돼지고기다짐육": [
        r"돼지고기\s*다짐육",
        r"돼지고기\s*다짐",
        r"돼지고기\s*다진",
    ],

    "한우다짐육": [
        r"한우\s*다짐육",
        r"한우\s*다짐",
        r"한우\s*다진",
    ],

    "다짐육": [
        r"(?<![가-힣])다짐육",
        r"(?<![가-힣])다짐",
    ],
}


# ============================================================
# 입력 dtype 확인
# ============================================================

def get_input_dtype(model) -> torch.dtype:
    """
    Whisper encoder 입력 dtype을 확인합니다.
    """

    for name, module in model.named_modules():

        if name.endswith("encoder.conv1"):

            if hasattr(module, "bias") and module.bias is not None:
                return module.bias.dtype

    return torch.float16


# ============================================================
# STT 모델 로드
# ============================================================

def load_stt_model():
    """
    Whisper Base + ChefEar QLoRA Adapter를 로드합니다.

    최초 1회만 로드하고 이후 호출에서는 재사용합니다.
    """

    global _processor
    global _model
    global _input_dtype

    # 이미 모델이 로드되어 있으면 재사용
    if _model is not None and _processor is not None:
        return _model, _processor

    # 4bit(NF4) 양자화는 bitsandbytes가 CUDA 전용으로 지원한다(GPU 없이는 로드 자체가
    # 안 됨) — 다른 파일들(tts/infer.py, llm/infer.py, 이 파일의 load_ct2_model()/
    # load_realtime_stt_model())과 같은 형태로 명확한 에러 메시지를 먼저 준다.
    if not torch.cuda.is_available():
        raise RuntimeError(
            "GPU(CUDA)가 필요합니다 — 4bit(NF4) 양자화는 bitsandbytes가 CUDA에서만 지원함."
        )

    # --------------------------------------------------------
    # Processor
    # --------------------------------------------------------

    try:

        _processor = WhisperProcessor.from_pretrained(
            HF_ADAPTER_ID
        )

        print(
            "✅ Processor: "
            "Hugging Face Adapter Repo에서 로드"
        )

    except Exception:

        _processor = WhisperProcessor.from_pretrained(
            MODEL_ID
        )

        print(
            "⚠ Processor: "
            "Base Model에서 로드"
        )


    # --------------------------------------------------------
    # 4bit QLoRA 설정
    # --------------------------------------------------------

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )


    # --------------------------------------------------------
    # Whisper Base Model
    # --------------------------------------------------------

    base_model = (
        WhisperForConditionalGeneration
        .from_pretrained(
            MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto",
        )
    )

    base_model.config.forced_decoder_ids = None

    base_model.generation_config.forced_decoder_ids = None


    # --------------------------------------------------------
    # ChefEar QLoRA Adapter 결합
    # --------------------------------------------------------

    _model = PeftModel.from_pretrained(
        base_model,
        HF_ADAPTER_ID,
    )

    _model.eval()

    _model.config.forced_decoder_ids = None

    _model.generation_config.forced_decoder_ids = None


    # --------------------------------------------------------
    # 입력 dtype 확인
    # --------------------------------------------------------

    _input_dtype = get_input_dtype(
        _model
    )

    print(
        "✅ ChefEar STT 모델 로드 완료"
    )

    print(
        "Input dtype:",
        _input_dtype
    )

    return _model, _processor


# ============================================================
# 1차 후처리
# 단위 표기 정규화
# ============================================================

def normalize_stt_text(text: str) -> str:
    """
    STT가 의미는 맞게 인식했지만
    단위를 영어로 출력한 경우 한글 표기로 통일합니다.

    이 함수에서는 숫자 값을 절대 변경하지 않습니다.

    예
    --
    100 g
        → 100그램

    1 kg
        → 1킬로그램

    200 ml
        → 200밀리리터

    1 L
        → 1리터
    """

    # kg → 킬로그램
    # g보다 먼저 처리
    text = re.sub(
        r"(\d+)\s*[kK][gG](?![A-Za-z])",
        r"\1킬로그램",
        text,
    )

    # ml → 밀리리터
    # l보다 먼저 처리
    text = re.sub(
        r"(\d+)\s*[mM][lL](?![A-Za-z])",
        r"\1밀리리터",
        text,
    )

    # g → 그램
    text = re.sub(
        r"(\d+)\s*[gG](?![A-Za-z])",
        r"\1그램",
        text,
    )

    # l / L → 리터
    text = re.sub(
        r"(\d+)\s*[lL](?![A-Za-z])",
        r"\1리터",
        text,
    )

    return text


# ============================================================
# 재료 문맥 정규화
# ============================================================

def normalize_ingredient_context(
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ],
) -> str:
    """
    현재 레시피의 재료 정보를
    비교하기 쉬운 하나의 문자열로 변환합니다.

    지원 입력
    --------
    문자열:
        "소고기다짐육 100g, 당근 20g"

    리스트:
        [
            "소고기다짐육 100g",
            "당근 20g",
        ]
    """

    if ingredient_context is None:
        return ""

    if isinstance(
        ingredient_context,
        (list, tuple, set),
    ):

        context = " ".join(
            str(item)
            for item in ingredient_context
        )

    else:

        context = str(
            ingredient_context
        )


    # 재료 DB의 g / kg / ml 등도
    # 같은 기준으로 맞춤
    context = normalize_stt_text(
        context
    )


    # 비교에 방해되는 연속 공백 정리
    context = re.sub(
        r"\s+",
        " ",
        context,
    ).strip()

    return context


# ============================================================
# 재료 문맥에서 수량 존재 여부 확인
# ============================================================

def context_has_quantity(
    context: str,
    ingredient: str,
    quantity: int,
) -> bool:
    """
    현재 레시피 재료 문맥에

        재료명 + 특정 그램 수

    가 존재하는지 확인합니다.

    예
    --
    소고기다짐육 100그램
    """

    # 비교 시 재료명 내부 공백 허용
    ingredient_pattern = (
        r"\s*".join(
            map(
                re.escape,
                ingredient,
            )
        )
    )

    pattern = (
        ingredient_pattern
        + rf"\s*{quantity}\s*그램"
    )

    return bool(
        re.search(
            pattern,
            context,
        )
    )


# ============================================================
# 2차 후처리
# 고위험 음향 경계 조건부 보정
# ============================================================

def correct_high_risk_with_context(
    text: str,
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ],
) -> str:
    """
    고위험군 테스트에서 반복 확인된
    '다짐육 + 백그램 → 다짐 + 육백그램'
    음향 경계 문제를 조건부로 보정합니다.

    매우 중요한 안전 조건
    ----------------------
    현재 레시피 재료 정보가 없으면
    아무것도 수정하지 않습니다.

    또한:

        현재 레시피 = 100그램
        현재 레시피 != 600그램

    이 두 조건을 모두 만족할 때만
    600 → 100 보정을 허용합니다.

    따라서 일반적인 600그램 발화를
    무조건 100그램으로 바꾸지 않습니다.
    """

    context = normalize_ingredient_context(
        ingredient_context
    )


    # --------------------------------------------------------
    # 재료 문맥이 없으면 숫자 보정 금지
    # --------------------------------------------------------

    if not context:
        return text


    corrected_text = text


    # ========================================================
    # 고위험 재료별 검사
    # ========================================================

    for canonical_name, risky_patterns in (
        HIGH_RISK_INGREDIENTS.items()
    ):

        # ----------------------------------------------------
        # 현재 레시피가 실제로 100그램인지 확인
        # ----------------------------------------------------

        has_100g = context_has_quantity(
            context,
            canonical_name,
            100,
        )


        # ----------------------------------------------------
        # 현재 레시피가 실제 600그램이면
        # 절대 100그램으로 바꾸지 않음
        # ----------------------------------------------------

        has_600g = context_has_quantity(
            context,
            canonical_name,
            600,
        )


        # 안전 조건
        if not has_100g:
            continue

        if has_600g:
            continue


        # ----------------------------------------------------
        # STT 결과에서
        # 고위험 표현 + 600그램 확인
        # ----------------------------------------------------

        for risky_pattern in risky_patterns:

            pattern = (
                rf"{risky_pattern}"
                rf"\s*600그램"
            )


            # ------------------------------------------------
            # 현재 레시피가 100그램이라고 확인된 경우에만
            # 표준 재료명 + 100그램으로 보정
            # ------------------------------------------------

            corrected_text = re.sub(
                pattern,
                f"{canonical_name} 100그램",
                corrected_text,
            )


    return corrected_text


# ============================================================
# 내부 음성 추론
# ============================================================

def _transcribe_audio(
    audio_path: Path,
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ] = None,
) -> str:
    """
    음성 파일 1개를 ChefEar STT로 인식합니다.

    Parameters
    ----------
    audio_path
        음성 파일 경로

    ingredient_context
        현재 레시피의 재료 정보.

        이 값이 있을 때만
        고위험 숫자 조건부 보정이 작동합니다.

    흐름
    ----
    audio
        ↓
    Whisper
        ↓
    raw_prediction
        ↓
    단위 표기 정규화
        ↓
    현재 재료 문맥 기반 조건부 보정
        ↓
    최종 prediction
    """

    model, processor = load_stt_model()


    # --------------------------------------------------------
    # 16kHz 로드
    # --------------------------------------------------------

    audio, _ = librosa.load(
        str(audio_path),
        sr=16000,
    )


    # --------------------------------------------------------
    # Whisper 입력 생성
    # --------------------------------------------------------

    inputs = processor(
        audio,
        sampling_rate=16000,
        return_tensors="pt",
        return_attention_mask=True,
    )


    input_dtype = (
        _input_dtype
        or get_input_dtype(model)
    )


    input_features = (
        inputs.input_features.to(
            device=model.device,
            dtype=input_dtype,
        )
    )


    attention_mask = (
        inputs.attention_mask.to(
            model.device
        )
    )


    # --------------------------------------------------------
    # STT 추론
    # --------------------------------------------------------

    with torch.inference_mode():

        generated_ids = model.generate(
            input_features=input_features,
            attention_mask=attention_mask,
            language="ko",
            task="transcribe",
        )


    # --------------------------------------------------------
    # Whisper 원본 출력
    # --------------------------------------------------------

    raw_prediction = (
        processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0].strip()
    )


    # --------------------------------------------------------
    # 1차: 단위 표기 정규화
    # --------------------------------------------------------

    prediction = normalize_stt_text(
        raw_prediction
    )


    # --------------------------------------------------------
    # 2차: 현재 레시피 문맥 기반 고위험 보정
    # --------------------------------------------------------

    prediction = correct_high_risk_with_context(
        prediction,
        ingredient_context,
    )


    return prediction


# ============================================================
# 배포용 단일 발화 추론 (faster-whisper, CPU) — docs/specs/stt_deploy.md
# ============================================================
#
# 위 load_stt_model()/_transcribe_audio()는 4bit(NF4) 양자화라 CUDA 전용이라(GPU 없는
# HF Spaces CPU Basic에서 로드 자체가 안 됨), 배포는 별도로 faster-whisper(int8, CPU)를 쓴다.
# faster-whisper는 HF transformers 체크포인트를 직접 못 읽어서, 먼저 src/stt/export_ct2.py로
# (LoRA 병합 → CTranslate2 int8 변환) 오프라인 변환해둔 결과물을 읽는다.

# 변환 결과물 우선순위: 0) .env의 STT_LOCAL_CACHE_DIR(로컬 디스크 사본, 아래 설명)
# 1) 로컬 models/stt_finetuned/ct2_int8/(export_ct2.py 산출물) 2) .env의 HF_STT_CT2_REPO
# (HF Hub에 올린 변환본 — 아직 업로드 여부 미정, Open Issue)
CT2_LOCAL_DIR = PROJECT_ROOT / "models" / "stt_finetuned" / "ct2_int8"
HF_STT_CT2_REPO = os.environ.get("HF_STT_CT2_REPO")

# 2026-08-20 실측: 이 프로젝트 폴더(PROJECT_ROOT, 곧 CT2_LOCAL_DIR)가 네트워크 공유
# 드라이브(CIFS, ~9MB/s)에 있는 환경에서는 model.bin(778MB) 하나 읽는 데만 87초 넘게
# 걸린다(GPU/CPU 사용률 0%, 순수 네트워크 I/O 대기 — CUDA 초기화가 아니었음). .env에
# STT_LOCAL_CACHE_DIR로 진짜 로컬 디스크 사본 경로를 지정하면 그걸 최우선으로 쓴다.
STT_LOCAL_CACHE_DIR = os.environ.get("STT_LOCAL_CACHE_DIR")

_ct2_model = None

# 2026-08-22 — src/tts/infer.py의 _LOAD_LOCK과 같은 이유("Cannot copy out of meta tensor;
# no data!" 실사용 보고, 유력한 원인은 _warm_up_models()가 화면(세션)이 뜰 때마다
# 호출되는데 로딩 자체엔 동시 진입 방지가 없어서 두 스레드가 거의 동시에 로딩을
# 시작하면 같은 GPU에 같은 모델을 두 번 올리려다 꼬이는 경합). load_ct2_model()과
# load_realtime_stt_model() 둘 다 이 하나의 락으로 로딩 시작 자체를 직렬화한다 —
# 둘이 동시에 로딩을 시작할 일은 거의 없지만(둘 다 _warm_up_models()가 순차 호출),
# 실제 서비스 경로(stt_transcribe())가 load_realtime_stt_model()을 호출하는 시점과
# 겹칠 수 있어 공유한다.
_LOAD_LOCK = threading.Lock()


def _resolve_ct2_model_path() -> str:
    """CTranslate2 변환 모델의 경로/repo를 우선순위대로 결정한다.

    로컬에도 없고 HF_STT_CT2_REPO도 없으면, 조용히 다른 모델로 폴백하지 않고 바로
    에러를 던진다(EC-04, docs/specs/stt_deploy.md) — 잘못된 모델로 응답하는 게 더 위험하다.
    """
    if STT_LOCAL_CACHE_DIR:
        # expanduser() 필수 — 이 값은 계정마다 다른 로컬 경로라 .env에 "~/..."로 적어두고
        # 계정별($HOME) 홈 디렉터리 기준으로 풀리게 한다(2026-08-21, 이 저장소 폴더를 여러
        # 계정이 공유해서 절대경로를 하드코딩하면 다른 계정 설정이 깨짐).
        local_cache = Path(STT_LOCAL_CACHE_DIR).expanduser()
        if local_cache.exists():
            return str(local_cache)
    if CT2_LOCAL_DIR.exists():
        return str(CT2_LOCAL_DIR)
    if HF_STT_CT2_REPO:
        return HF_STT_CT2_REPO
    raise FileNotFoundError(
        f"CTranslate2 변환 모델을 찾을 수 없음 — {CT2_LOCAL_DIR}도 없고 .env의 "
        "HF_STT_CT2_REPO도 안 설정됨. 먼저 `python src/stt/export_ct2.py`를 실행해서 "
        "변환본을 만들 것(docs/specs/stt_deploy.md 참고)."
    )


def load_ct2_model():
    """faster-whisper 모델을 최초 1번만 로드하고 이후 재사용한다."""

    global _ct2_model

    if _ct2_model is not None:
        return _ct2_model

    # _LOAD_LOCK 정의부 주석 참고 — 락을 기다리는 동안 다른 스레드가 이미 로딩을
    # 끝냈을 수 있으니, 락을 잡은 뒤에도 한 번 더 확인한다(이중 확인 잠금).
    with _LOAD_LOCK:
        if _ct2_model is not None:
            return _ct2_model

        from faster_whisper import WhisperModel

        model_path = _resolve_ct2_model_path()

        # 2026-08-19 팀 결정(docs/decisions.md #2): 배포를 GPU 데스크탑 상시 노출(Tailscale)로
        # 확정하면서 "HF Spaces CPU Basic" 배포 전제 자체가 없어졌다 — CPU 폴백 없이 GPU를
        # 필수로 요구한다. CPU 속도 실측이 다시 필요하면 tests/tts_cpu_inference_test.py처럼
        # 별도 벤치마크에서 device="cpu"를 명시해서 재현할 것(이 함수 자체는 항상 cuda).
        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
            )
        _ct2_model = WhisperModel(model_path, device="cuda", compute_type="int8")

        print(f"✅ ChefEar STT(faster-whisper, int8) 로드 완료: {model_path} (device=cuda)")

        return _ct2_model


def stt_transcribe(
    audio: "str | Path | np.ndarray",
    *,
    sample_rate: int | None = None,
    ingredient_context: Optional[Union[str, Sequence[str]]] = None,
) -> str:
    """오디오 하나 -> 인식된 텍스트. faster-whisper(int8) 기반, HF Spaces 배포용.

    app.py가 직접 호출할 곳 — orchestration.pipeline.handle_utterance()에 반환값을
    그대로 넘기면 된다.

    2026-08-21: 이 이름의 함수가 두 개(이 함수 + 아래 stt_transcribe_with_context())
    존재해서 파이썬이 나중 정의만 남기고 이 함수를 덮어써버린 게 실측으로 확인됨 —
    app.py는 여전히 이 시그니처(numpy 배열+sample_rate)로 호출하는데 실제로는 무거운
    4bit 모델 경로(stt_transcribe_with_context, CUDA 전용이라 HF Spaces CPU Basic에서
    로드 자체가 안 됨)가 대신 불려서 TypeError로 죽었다. 이름 충돌 해소하면서, 하주성님이
    stt_transcribe_with_context()에 만들어둔 문맥 기반 후처리(normalize_stt_text/
    correct_high_risk_with_context, 둘 다 순수 텍스트 함수라 모델과 무관)를 이 배포용
    경로에도 그대로 적용되게 옮겨왔다 — 기능은 잃지 않으면서 무거운 모델은 안 쓴다.

    Parameters
    ----------
    audio
        파일 경로(mp3/wav 등) 또는 numpy 파형 배열. 배열로 줄 경우 sample_rate가 필수이며,
        16kHz가 아니면 librosa로 16kHz 모노로 리샘플링한 뒤 넘긴다(EC-03).
    ingredient_context
        현재 레시피 재료 정보(문자열 또는 리스트). 있으면 고위험 숫자 보정까지 적용, 없으면
        단위 표기 정규화만 적용(둘 다 순수 텍스트 후처리라 모델 로딩과 무관).

    Returns
    -------
    str
        인식된 텍스트. 무음/너무 짧은 오디오 등으로 인식된 구간이 없으면 빈 문자열을
        반환한다(예외 아님, EC-01) — 호출부(app.py)가 "다시 말씀해주세요"로 안내할 수 있게.
    """

    model = load_ct2_model()

    if isinstance(audio, np.ndarray):
        if sample_rate is None:
            raise ValueError("audio가 numpy 배열이면 sample_rate가 필수임")
        if sample_rate != 16000:
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)

    # vad_filter=True: 무음 구간을 걸러내서, 순수 무음 입력에서 whisper 특유의 환각
    # (silence hallucination) 없이 자연스럽게 빈 결과가 나오게 한다(EC-01).
    #
    # beam_size=1(2026-08-24 수정) — "된장찌개"가 "된장찌"로, "소고기를 손질해주세요"가
    # "소고기 2."로 잘려나가는 문제 실측 확인(WEBRTC_DEBUG 로그 + 저장된 오디오로 재현).
    # faster-whisper 기본값(beam_size=5)으로 여러 개의 후보 문장을 동시에 탐색하다가,
    # 이 파인튜닝 모델에서는 종종 짧게 끝나는(조기 종료) 후보 쪽 누적 확률이 더 높게
    # 나와서 그쪽으로 수렴해버리는 것으로 보인다(faster-whisper의 세그먼트 타임스탬프가
    # 0.00~0.02초처럼 말도 안 되게 찍히는 것도 이 조기 종료의 증거). beam_size=1(그리디
    # 디코딩 — 매 순간 가장 그럴듯한 다음 토큰 하나만 따라감, 후보 경쟁 자체가 없음)로
    # 바꾸면 이 문제가 재현됐던 실제 녹음 파일들에서 전부 정상 문장으로 나온다(실측
    # 확인 — 여러 테스트 오디오로 회귀 없음도 같이 확인함, 사소한 단어 차이 한둘 정도만
    # 있고 그마저도 원래도 발음이 뭉개진 테스트 파일들이었음).
    segments, _info = model.transcribe(audio, language="ko", vad_filter=True, beam_size=1)

    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        return text

    # 2026-08-24 추가 — "김치볶음밥"이 화면/채팅창에 "김치볶�밥"처럼 깨져 나오는 문제
    # 실측 확인. beam_size(1이든 5든 동일 재현 — 그 파라미터 문제 아님)와 무관하게, 같은
    # 문장을 여러 번 녹음해도 그중 일부만 이렇게 깨진다 — CTranslate2가 서브워드 토큰을
    # 텍스트로 역토큰화(detokenize)하는 과정에서, 드물게 완전한 UTF-8 문자를 이루지 못하는
    # 토큰 경계가 선택되는 것으로 보인다(모델/토크나이저 수준 현상이라 이 함수에서 근본
    # 수정은 어려움). 이런 결과를 그대로 화면에 보여주거나 요리명 매칭에 넘기면 사용자
    # 혼란·오매칭으로 이어지므로, U+FFFD(깨진 문자 표시)가 하나라도 있으면 EC-01(인식
    # 실패)과 똑같이 빈 문자열로 취급한다 — 호출부가 "다시 말씀해주세요"로 안내한다.
    if "�" in text:
        return ""

    text = normalize_stt_text(text)
    text = correct_high_risk_with_context(text, ingredient_context)
    return text


# ============================================================
# 100개 음성 일괄 테스트
# 배치 평가(run_batch_test)/파일 경로 입력 전용 — 4bit 모델(load_stt_model) 사용
# ============================================================

def stt_transcribe_with_context(
    audio_path,
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ] = None,
) -> str:
    """
    배치 평가·오프라인 확인용 STT 함수입니다(4bit QLoRA + bitsandbytes, CUDA 전용).

    실시간 서비스 경로(app.py)는 이 함수가 아니라 위의 stt_transcribe()를 쓴다 — 이 함수는
    GPU 없는 HF Spaces CPU Basic에서 로드 자체가 안 되기 때문(위 load_stt_model() 참고).

    예
    --
    prediction = stt_transcribe_with_context(
        audio_path="user.wav",
        ingredient_context=[
            "소고기다짐육 100g",
            "당근 20g",
            "깻잎 3장",
        ],
    )

    ingredient_context가 None이면
    숫자 의미 보정은 수행하지 않습니다.
    """

    audio_path = Path(
        audio_path
    )


    if not audio_path.exists():

        raise FileNotFoundError(
            "오디오 파일을 찾을 수 없습니다: "
            f"{audio_path}"
        )


    return _transcribe_audio(
        audio_path,
        ingredient_context=ingredient_context,
    )


# ============================================================
# 음성 일괄 평가
# ============================================================

def run_batch_test(
    csv_path,
    audio_dir,
    result_path="ChefEar_STT_test100_result.csv",
):
    """
    기존 ChefEar STT 평가용 함수입니다.

    중요
    ----
    모델 평가에서는 reference를
    재료 문맥으로 사용하지 않습니다.

    그렇게 하면 정답을 미리 보고
    STT를 보정하는 셈이 되어
    평가 결과가 왜곡되기 때문입니다.

    따라서 run_batch_test에서는
    문맥 기반 숫자 보정을 사용하지 않습니다.
    """

    csv_path = Path(
        csv_path
    )

    audio_dir = Path(
        audio_dir
    )

    result_path = Path(
        result_path
    )


    # --------------------------------------------------------
    # 경로 확인
    # --------------------------------------------------------

    if not csv_path.exists():

        raise FileNotFoundError(
            "CSV 파일을 찾을 수 없습니다: "
            f"{csv_path}"
        )


    if not audio_dir.exists():

        raise FileNotFoundError(
            "오디오 폴더를 찾을 수 없습니다: "
            f"{audio_dir}"
        )


    # --------------------------------------------------------
    # CSV 읽기
    # --------------------------------------------------------

    df = pd.read_csv(
        csv_path
    )


    required_columns = [
        "test_id",
        "text",
    ]


    for column in required_columns:

        if column not in df.columns:

            raise ValueError(
                f"CSV에 '{column}' 컬럼이 없습니다."
            )


    print("=" * 60)

    print(
        "ChefEar STT 테스트 시작"
    )

    print(
        "CSV:",
        csv_path
    )

    print(
        "Audio:",
        audio_dir
    )

    print(
        "테스트 개수:",
        len(df)
    )

    print("=" * 60)


    # 모델 최초 1회 로드
    load_stt_model()


    results = []


    # ========================================================
    # 순차 추론
    # ========================================================

    for idx, row in df.iterrows():


        test_id = str(
            row["test_id"]
        ).strip()


        reference = str(
            row["text"]
        ).strip()


        audio_path = (
            audio_dir
            / f"{test_id}.mp3"
        )


        print(
            f"\n[{idx + 1}/{len(df)}] "
            f"{audio_path.name}"
        )


        # ----------------------------------------------------
        # 파일 확인
        # ----------------------------------------------------

        if not audio_path.exists():

            print(
                "❌ 오디오 파일 없음"
            )


            results.append({
                "test_id": test_id,
                "audio_file": audio_path.name,
                "reference": reference,
                "prediction": "",
                "wer": None,
                "status": "file_not_found",
            })


            continue


        # ----------------------------------------------------
        # STT
        # ----------------------------------------------------

        try:

            # 평가에서는 정답 문맥을 넣지 않음
            prediction = _transcribe_audio(
                audio_path,
                ingredient_context=None,
            )


            sentence_wer = wer(
                reference,
                prediction,
            )


            print(
                "정답 :",
                reference
            )


            print(
                "예측 :",
                prediction
            )


            print(
                f"WER  : "
                f"{sentence_wer:.4f}"
            )


            results.append({
                "test_id": test_id,
                "audio_file": audio_path.name,
                "reference": reference,
                "prediction": prediction,
                "wer": sentence_wer,
                "status": "success",
            })


        except Exception as error:


            print(
                "❌ 추론 오류:",
                error
            )


            results.append({
                "test_id": test_id,
                "audio_file": audio_path.name,
                "reference": reference,
                "prediction": "",
                "wer": None,
                "status": f"error: {error}",
            })


    # ========================================================
    # 결과 저장
    # ========================================================

    result_df = pd.DataFrame(
        results
    )


    result_df.to_csv(
        result_path,
        index=False,
        encoding="utf-8-sig",
    )


    # ========================================================
    # 전체 WER
    # ========================================================

    success_df = result_df[
        result_df["status"]
        == "success"
    ]


    if len(success_df) > 0:


        total_wer = wer(

            success_df[
                "reference"
            ].tolist(),

            success_df[
                "prediction"
            ].tolist(),
        )


        print(
            "\n"
            + "=" * 60
        )


        print(
            "✅ ChefEar STT 테스트 완료"
        )


        print(
            "성공:",
            len(success_df)
        )


        print(
            "실패:",
            len(result_df)
            - len(success_df)
        )


        print(
            f"전체 WER: "
            f"{total_wer:.4f}"
        )


        print(
            f"전체 WER(%): "
            f"{total_wer * 100:.2f}%"
        )


        print(
            "결과 CSV:",
            result_path
        )


        print("=" * 60)


    return result_df


# ============================================================
# 실시간 추론 원본 모델 비교용 (faster-whisper, 파인튜닝 전) — 2026-08-20 추가,
# 2026-08-23 이름 충돌 수정
# ============================================================
#
# 위 load_stt_model()/run_batch_test()는 파인튜닝된 4bit QLoRA Adapter를 쓰는데
# bitsandbytes 4bit 양자화가 GPU(CUDA) 전용이라, GPU 없는 환경(예: 이 저장소를
# 로컬 CPU에서 테스트할 때)에서는 아예 로드가 안 된다. 그리고 배포용으로 정해둔
# faster-whisper(requirements.txt)로 쓰려면 파인튜닝된 Adapter를 CTranslate2
# 포맷으로 변환해야 하는데, 이 변환은 위 README의 "faster-whisper/CTranslate2
# 기반 경량화 검토" 항목대로 아직 안 된 상태였다(2026-08-20 당시) — 그래서 이
# 아래 함수는 일단 파인튜닝 안 된 원본 openai/whisper-large-v3-turbo를
# faster-whisper로 돌려서 "마이크 → VAD → 텍스트 → 요리명 인식" 파이프라인
# 자체가 동작하는지만 먼저 확인하려던 용도였다(상시 마이크 테스트 화면 요청).
#
# 2026-08-23 리포트 — 그 후 CTranslate2 변환이 끝나서 위쪽에 "배포용" stt_transcribe()
# (line 769대, load_ct2_model() 사용, 진짜 파인튜닝된 어댑터)가 새로 생겼는데, 이 함수도
# 이름이 똑같이 stt_transcribe()였다. 같은 파일에 같은 이름의 함수가 두 번 정의되면
# 파이썬은 나중 정의(이 함수)로 조용히 덮어써버린다 — 그 결과 실서비스 경로
# (src/ui/voice_io.py의 listen())가 실제로는 이 함수(파인튜닝 안 된 원본 모델)를 호출하고
# 있었고, 위쪽 배포용 함수는 워밍업 때 GPU에 로드만 되고 실제 추론에는 전혀 안 쓰이는
# 죽은 코드였다(AppTest로 실측 확인 — `stt.infer.stt_transcribe`가 실제로 바인딩된 소스를
# 찍어보니 이 함수였음). 이름을 바꿔서 충돌을 없애고, 위쪽 배포용 함수가 진짜로
# 쓰이게 한다. 이 함수 자체는 파인튜닝 전/후 비교용으로 남겨둔다.
REALTIME_MODEL_SIZE = os.environ.get("HF_STT_REALTIME_MODEL") or "large-v3-turbo"

_realtime_model = None


def load_realtime_stt_model():
    """faster-whisper 모델을 최초 1번만 로드하고 이후 호출에서 재사용한다
    (tts.infer.load_tts_model()과 같은 지연 로딩·캐싱 패턴)."""
    global _realtime_model
    if _realtime_model is not None:
        return _realtime_model

    # _LOAD_LOCK 정의부 주석 참고 — 락을 기다리는 동안 다른 스레드가 이미 로딩을
    # 끝냈을 수 있으니, 락을 잡은 뒤에도 한 번 더 확인한다(이중 확인 잠금).
    with _LOAD_LOCK:
        if _realtime_model is not None:
            return _realtime_model

        from faster_whisper import WhisperModel

        # 2026-08-19 팀 결정(docs/decisions.md #2): 배포를 GPU 데스크탑 상시 노출로 확정 —
        # CPU 폴백 없이 GPU를 필수로 요구한다.
        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
            )
        _realtime_model = WhisperModel(REALTIME_MODEL_SIZE, device="cuda", compute_type="int8")
        print(f"[STT] 비교용 faster-whisper 모델 로드 완료: {REALTIME_MODEL_SIZE} (원본, 파인튜닝 아님, device=cuda)")
        return _realtime_model


def stt_transcribe_realtime_base(waveform, sample_rate: int = 16000) -> str:
    """오디오 배열 하나(예: VAD로 잘라낸 발화 한 구간) -> 인식된 텍스트 한 줄.

    파인튜닝 전 원본 모델(load_realtime_stt_model())로 인식한다 — 위 stt_transcribe()
    (파인튜닝된 어댑터, load_ct2_model())와 비교하고 싶을 때만 직접 불러 쓰는 함수다.
    실서비스 경로(app.py/voice_io.py)는 이 함수가 아니라 위 stt_transcribe()를 쓴다
    (2026-08-23 이름 충돌 수정 — 위 섹션 주석 참고).

    waveform은 float32 numpy 배열(모노)이어야 한다 — sample_rate가 16000이 아니면
    whisper가 기대하는 16kHz로 리샘플링한다(librosa는 이미 이 파일 상단에서 씀).
    """
    import numpy as np

    waveform = np.asarray(waveform, dtype=np.float32)
    if sample_rate != 16000:
        waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=16000)

    model = load_realtime_stt_model()
    segments, _ = model.transcribe(waveform, language="ko", task="transcribe")
    return "".join(segment.text for segment in segments).strip()