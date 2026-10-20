"""ChefEar STT Runtime / Evaluation"""

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


# 후처리 함수는 stt/postprocess.py로 옮겼다(동작 변경 없음). 기존 import 경로를 유지하려고 다시 내보낸다.
from stt.postprocess import (  # noqa: E402,F401
    HIGH_RISK_INGREDIENTS,
    normalize_stt_text,
    normalize_ingredient_context,
    context_has_quantity,
    correct_high_risk_with_context,
    _HALLUCINATION_MARKERS,
    _looks_like_hallucination,
)


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
# 내부 음성 추론
# ============================================================

def _transcribe_audio(
    audio_path: Path,
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ] = None,
) -> str:
    """음성 파일 1개를 ChefEar STT로 인식합니다."""

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
# 배포용 단일 발화 추론 (faster-whisper, CTranslate2 int8) — docs/specs/stt_deploy.md
# ============================================================
#
# 위 load_stt_model()/_transcribe_audio()는 4bit(NF4) 학습 어댑터 경로라 배치 평가 전용이고,
# 배포는 faster-whisper(int8, GPU)를 쓴다. faster-whisper는 HF transformers 체크포인트를
# 직접 못 읽어서, src/stt/export_ct2.py로(LoRA 병합 → CTranslate2 int8 변환) 오프라인
# 변환해둔 결과물을 읽는다.

# 변환 결과물 우선순위: 0) .env의 STT_LOCAL_CACHE_DIR(로컬 디스크 사본, 아래 설명)
# 1) 로컬 models/stt_finetuned/ct2_int8/(export_ct2.py 산출물) 2) .env의 HF_STT_CT2_REPO
# (HF Hub에 올린 변환본 — 아직 업로드 여부 미정, Open Issue)
CT2_LOCAL_DIR = PROJECT_ROOT / "models" / "stt_finetuned" / "ct2_int8"
HF_STT_CT2_REPO = os.environ.get("HF_STT_CT2_REPO")

STT_LOCAL_CACHE_DIR = os.environ.get("STT_LOCAL_CACHE_DIR")

_ct2_model = None

_LOAD_LOCK = threading.Lock()


def _resolve_ct2_model_path() -> str:
    """CTranslate2 변환 모델의 경로/repo를 우선순위대로 결정한다.

    로컬에도 없고 HF_STT_CT2_REPO도 없으면, 조용히 다른 모델로 폴백하지 않고 바로
    에러를 던진다(EC-04, docs/specs/stt_deploy.md) — 잘못된 모델로 응답하는 게 더 위험하다.
    """
    if STT_LOCAL_CACHE_DIR:
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

        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
            )
        _ct2_model = WhisperModel(
            model_path, device="cuda", compute_type="int8", use_auth_token=os.environ.get("HF_TOKEN")
        )

        print(f"✅ ChefEar STT(faster-whisper, int8) 로드 완료: {model_path} (device=cuda)")

        return _ct2_model


def stt_transcribe(
    audio: "str | Path | np.ndarray",
    *,
    sample_rate: int | None = None,
    ingredient_context: Optional[Union[str, Sequence[str]]] = None,
    vad_filter: bool = True,
    session_id: str | None = None,
) -> str:
    """오디오 하나 -> 인식된 텍스트. faster-whisper(CTranslate2 int8, GPU) 기반 배포용 경로.

    파일 경로 또는 numpy 파형(sample_rate 필수, 16kHz가 아니면 리샘플링)을 받는다.
    ingredient_context가 있으면 조리 문맥 기반 고위험 숫자 보정까지 적용하고, 없으면 단위
    정규화만 적용한다. 호출부가 이미 VAD로 구간을 잘라 넘기면 vad_filter=False로 부른다.
    인식된 구간이 없으면 빈 문자열을 반환한다(예외 아님).
    """

    model = load_ct2_model()

    if isinstance(audio, np.ndarray):
        if sample_rate is None:
            raise ValueError("audio가 numpy 배열이면 sample_rate가 필수임")
        if sample_rate != 16000:
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)

    segments, _info = model.transcribe(audio, language="ko", vad_filter=vad_filter, beam_size=1)
    segments = list(segments)

    if segments:
        for seg in segments:
            print(
                f"[STT_CONF_DEBUG] sid={session_id} text={seg.text.strip()!r} "
                f"avg_logprob={seg.avg_logprob:.3f} no_speech_prob={seg.no_speech_prob:.3f}",
                flush=True,
            )

    text = " ".join(segment.text.strip() for segment in segments).strip()

    if text and segments:
        max_no_speech = max((s.no_speech_prob for s in segments), default=0.0)
        if max_no_speech > 0.85:
            print(
                f"[STT] sid={session_id} 환각 방어: no_speech_prob={max_no_speech:.3f} > 0.85 — 버림 text={text!r}",
                flush=True,
            )
            text = ""
    if text and _looks_like_hallucination(text):
        print(f"[STT] sid={session_id} 환각 방어: 상투구 매칭 — 버림 text={text!r}", flush=True)
        text = ""

    if not text:
        print(
            f"[STT_EMPTY_DEBUG] sid={session_id} segments={len(segments)} "
            f"language={_info.language} language_probability={_info.language_probability:.3f} "
            f"duration={_info.duration:.2f}s duration_after_vad="
            f"{getattr(_info, 'duration_after_vad', None)}",
            flush=True,
        )

    if not text:
        return text

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
    """배치 평가·오프라인 확인용 STT 함수입니다(4bit QLoRA + bitsandbytes, CUDA 전용)."""

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
    """기존 ChefEar STT 평가용 함수입니다."""

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

        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
            )
        _realtime_model = WhisperModel(REALTIME_MODEL_SIZE, device="cuda", compute_type="int8")
        print(f"[STT] 비교용 faster-whisper 모델 로드 완료: {REALTIME_MODEL_SIZE} (원본, 파인튜닝 아님, device=cuda)")
        return _realtime_model


def stt_transcribe_realtime_base(waveform, sample_rate: int = 16000) -> str:
    """오디오 배열 하나(예: VAD로 잘라낸 발화 한 구간) -> 인식된 텍스트 한 줄."""
    import numpy as np

    waveform = np.asarray(waveform, dtype=np.float32)
    if sample_rate != 16000:
        waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=16000)

    model = load_realtime_stt_model()
    segments, _ = model.transcribe(waveform, language="ko", task="transcribe")
    return "".join(segment.text for segment in segments).strip()