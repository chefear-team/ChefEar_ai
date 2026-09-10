"""ChefEar TTS - 런타임 음성 합성 (조리 단계 안내 문장 등을 음성으로)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import torch

from orchestration.db import load_env
from tts.pronunciation import apply_pronunciation_fixes

# db.py의 get_client()와 동일한 방식 — python-dotenv 없이 .env를 os.environ에 채워 넣는다.
# 아래 MODEL_ID가 이 시점의 os.environ을 바로 읽으므로, HF_TOKEN을 쓰는 load_tts_model()보다
# 먼저(모듈 import 시점에) 호출해야 한다.
load_env()

# ============================================================
# 모델 설정
# ============================================================

# .env의 HF_TTS_MODEL_REPO로 덮어쓸 수 있게 하되(.env.example.local 참고), 기본값은 확정된 모델로 고정.
MODEL_ID = os.environ.get("HF_TTS_MODEL_REPO") or "kimseunguk/qwen3-tts-kss-finetuned"


SPEAKER = "kss_speaker"

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VOICE_CLONE_REF_AUDIO = str(_ASSETS_DIR / "kss_reference.wav")
VOICE_CLONE_REF_TEXT = "나는 살아오면서 감기를 앓은 적이 한 번도 없다."  # data/kss/metadata.csv 000008


# 모델은 최초 1번만 로드하고 이후 호출에서 재사용
_model = None

_LOAD_LOCK = threading.Lock()

# base 타입 체크포인트일 때만 쓰는 voice-clone 프롬프트 — 레퍼런스 오디오가 고정이라 최초
# 1번만 만들고 재사용(모델 로드와 마찬가지로 매 합성마다 다시 만들 필요 없음).
_voice_clone_prompt = None


# ============================================================
# TTS 모델 로드
# ============================================================

def load_tts_model():

    global _model

    # 이미 모델이 로드되어 있으면 재사용
    if _model is not None:

        return _model

    # _LOAD_LOCK 정의부 주석 참고 — 두 스레드가 동시에 여기 들어와서 위 "이미 로드됨"
    # 검사를 둘 다 통과해버리는 경합을 막는다. 락을 기다리는 동안 다른 스레드가 이미
    # 로딩을 끝냈을 수 있으니, 락을 잡은 뒤에도 한 번 더 확인한다(이중 확인 잠금).
    with _LOAD_LOCK:

        if _model is not None:

            return _model

        from qwen_tts import Qwen3TTSModel

        local_cache_dir = os.environ.get("TTS_LOCAL_CACHE_DIR")
        model_source = MODEL_ID
        use_local = False
        if local_cache_dir and Path(local_cache_dir).expanduser().exists():
            model_source = str(Path(local_cache_dir).expanduser())
            use_local = True

        token = os.environ.get("HF_TOKEN")

        if not use_local and not token:

            raise RuntimeError(
                f"HF_TOKEN이 필요함 ({MODEL_ID}는 private repo) — .env 또는 배포 환경변수에 설정할 것"
            )


        if not torch.cuda.is_available():

            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2). "
                "CUDA 드라이버/torch 설치를 확인할 것."
            )

        device_map, dtype = "cuda:0", torch.bfloat16


        try:

            import flash_attn  # noqa: F401

            attn_impl = "flash_attention_2"

        except ImportError:

            attn_impl = "sdpa"


        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                _model = Qwen3TTSModel.from_pretrained(

                    model_source,

                    token=None if use_local else token,

                    device_map=device_map,

                    dtype=dtype,

                    attn_implementation=attn_impl,
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 — 재시도 대상인지 여기선 구분 안 하고 다 재시도
                last_exc = exc
                suffix = "재시도합니다." if attempt < 3 else "재시도 횟수를 다 씀."
                print(f"[TTS] 모델 로드 실패(시도 {attempt}/3): {exc!r} — {suffix}")
                torch.cuda.empty_cache()

        if last_exc is not None:
            raise last_exc

        print(f"[TTS] 모델 로드 완료: {model_source} (device={device_map}, attn={attn_impl}, local={use_local})")


        return _model


# ============================================================
# 런타임 음성 합성
# ============================================================

DEFAULT_MAX_NEW_TOKENS = 400  # 아주 짧은 문장(예: "다음 단계로 가주세요")의 최소 하한
_TOKENS_PER_CHAR = 20  # 글자당 예상 생성 토큰 수(잠정치, 위 문서 참고) — 아래 토크나이저
_MAX_NEW_TOKENS_CEILING = 1500  # do_sample=True에서 운 나쁘게 못 멈추는 경우의 상한선

_tts_tokenizer = None
_tts_tokenizer_load_failed = False


def _get_tts_tokenizer():
    global _tts_tokenizer, _tts_tokenizer_load_failed
    if _tts_tokenizer is not None or _tts_tokenizer_load_failed:
        return _tts_tokenizer
    try:
        from transformers import AutoTokenizer

        _tts_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    except Exception as exc:  # noqa: BLE001 — 실패하면 그냥 폴백, TTS 자체는 안 죽어야 함
        print(f"[TTS] 토크나이저 기반 길이 추정용 AutoTokenizer 로드 실패(글자수 추정으로 폴백): {exc!r}")
        _tts_tokenizer_load_failed = True
    return _tts_tokenizer


def _dynamic_max_new_tokens(text: str) -> int:
    """문장 길이에 비례해서 생성 예산을 계산한다 — 위 DEFAULT_MAX_NEW_TOKENS 문서 참고."""
    tokenizer = _get_tts_tokenizer()
    if tokenizer is not None:
        try:
            token_count = len(tokenizer(text).input_ids)
            estimated = int(token_count * 1.5)
            return min(_MAX_NEW_TOKENS_CEILING, max(DEFAULT_MAX_NEW_TOKENS, estimated))
        except Exception as exc:  # noqa: BLE001 — 인코딩 실패해도 폴백으로 계속 진행
            print(f"[TTS] 토크나이저 기반 길이 추정 실패(글자수 추정으로 폴백): {exc!r}")
    estimated = len(text) * _TOKENS_PER_CHAR
    return min(_MAX_NEW_TOKENS_CEILING, max(DEFAULT_MAX_NEW_TOKENS, estimated))


DEFAULT_SEED = 42


_TAIL_SILENCE_WINDOW_MS = 150  # 무음 판정 구간(끝에서부터) — 위 실측으로 정함
_TAIL_SILENCE_TRIGGER_RATIO = 0.15  # 이 구간 RMS가 앞부분 RMS의 이 비율보다 작으면 "무음"(실측 간극 2.5%~35% 사이 중간값)
_TAIL_SILENCE_MAX_ATTEMPTS = 2  # 최초 1회 + 재시도 최대 1회(시드만 바꿔서 재생성)


def _tail_silence_ratio(waveform: np.ndarray, sample_rate: int) -> float | None:
    """끝 _TAIL_SILENCE_WINDOW_MS 구간 RMS / 그 앞부분 RMS.

    문장이 너무 짧아 앞/뒤로 못 나누면(또는 앞부분이 완전 무음이면) None — 판정
    불가로 보고 호출부가 재시도 없이 그대로 쓴다.
    """
    n = waveform.shape[0]
    window = int(sample_rate * _TAIL_SILENCE_WINDOW_MS / 1000)
    if window <= 0 or window >= n:
        return None
    tail_rms = float(np.sqrt(np.mean(np.square(waveform[-window:]))))
    reference_rms = float(np.sqrt(np.mean(np.square(waveform[:-window]))))
    if reference_rms <= 0:
        return None
    return tail_rms / reference_rms


def _generate_once(
    model,
    model_type: str | None,
    tts_text: str,
    language: str,
    instruct: str,
    max_new_tokens: int,
):
    """실제 모델 호출 1회 — 재시도 루프(tts_synthesize)가 시드를 바꿔가며 여러 번
    부를 수 있어서 별도 함수로 뺐다. model_type 분기 자체는 기존 로직 그대로."""
    global _voice_clone_prompt

    if model_type == "base":
        # custom_voice 화자 임베딩이 없는 체크포인트 — 레퍼런스 음성으로 목소리를 복제해서 생성.
        if _voice_clone_prompt is None:
            _voice_clone_prompt = model.create_voice_clone_prompt(
                ref_audio=VOICE_CLONE_REF_AUDIO,
                ref_text=VOICE_CLONE_REF_TEXT,
            )
        return model.generate_voice_clone(
            text=tts_text,
            language=language,
            voice_clone_prompt=_voice_clone_prompt,
            max_new_tokens=max_new_tokens,
        )

    if model_type == "custom_voice":
        return model.generate_custom_voice(
            text=tts_text,
            language=language,
            speaker=SPEAKER,
            instruct=instruct,
            max_new_tokens=max_new_tokens,
        )

    raise ValueError(
        f"tts_synthesize()가 아직 지원하지 않는 tts_model_type={model_type!r} "
        f"({MODEL_ID})"
    )


_TRAILING_ARTIFACT_SCAN_MS = 1500  # 끝에서부터 이 구간 안에서만 패턴을 찾는다(문장 중간의 쉼표 등 오탐 방지)
_TRAILING_ARTIFACT_GAP_MS = 150  # 이 이상 연속으로 무음이어야 "확실한 끝 무음 구간"으로 본다
_TRAILING_ARTIFACT_ENVELOPE_MS = 30  # RMS 포락선 해상도(스캔 창을 이 단위로 잘게 나눠서 훑는다)
_TRAILING_ARTIFACT_PAD_MS = 80  # 잘라낸 자리에 남겨둘 자연스러운 무음 여유
_TRAILING_ARTIFACT_LOUDNESS_RATIO = 1.3  # 무음 뒤 소리 RMS가 본문 RMS의 이 배수를 넘어야 "튀는 소리"로 확정


def _trim_trailing_artifact(
    waveform: np.ndarray, sample_rate: int
) -> tuple[np.ndarray, bool]:
    """끝 쪽에서 "확실한 무음 -> 본문보다 훨씬 큰 소리"가 나오면, 그 무음이
    시작되는 지점부터 잘라낸다. 무음 뒤에 나온 소리가 본문과 비슷하거나 더
    작으면(= 정상적으로 이어지는 다음 문장일 가능성) 손대지 않는다.

    반환값은 (트리밍된 파형, 잘랐는지 여부) — 잘랐는지는 [TTS_DEBUG] 로그에 남긴다.
    """
    n = waveform.shape[0]
    scan_samples = int(sample_rate * _TRAILING_ARTIFACT_SCAN_MS / 1000)
    if scan_samples <= 0 or scan_samples >= n:
        return waveform, False  # 문장이 너무 짧아 본문/스캔 구간을 못 나누면 손대지 않는다

    region_start = n - scan_samples
    reference = waveform[:region_start]
    reference_rms = float(np.sqrt(np.mean(np.square(reference))))
    if reference_rms <= 0:
        return waveform, False

    silence_floor = reference_rms * _TAIL_SILENCE_TRIGGER_RATIO
    loudness_ceiling = reference_rms * _TRAILING_ARTIFACT_LOUDNESS_RATIO
    win = max(1, int(sample_rate * _TRAILING_ARTIFACT_ENVELOPE_MS / 1000))
    gap_needed = int(sample_rate * _TRAILING_ARTIFACT_GAP_MS / 1000)

    silence_run_start: int | None = None
    silence_run_len = 0
    cut_at: int | None = None

    idx = region_start
    while idx < n:
        seg = waveform[idx : idx + win]
        seg_rms = float(np.sqrt(np.mean(np.square(seg)))) if len(seg) else 0.0
        if seg_rms < silence_floor:
            if silence_run_start is None:
                silence_run_start = idx
            silence_run_len = idx + len(seg) - silence_run_start
        else:
            if silence_run_start is not None and silence_run_len >= gap_needed:
                # 무음 뒤에 다시 소리가 남 — 그 소리가 본문보다 확연히 큰
                # "튀는 소리"인지, 본문과 비슷한 "정상적으로 이어지는 다음
                # 문장"인지 RMS로 구분한다.
                followup = waveform[idx:]
                followup_rms = float(np.sqrt(np.mean(np.square(followup)))) if len(followup) else 0.0
                if followup_rms > loudness_ceiling:
                    cut_at = silence_run_start
                    break
                # 본문 수준 이하 — 정상적인 다음 문장일 수 있으니 자르지 않고
                # 계속 훑는다(이 뒤에 또 다른 무음->튀는소리 패턴이 있을 수 있음).
            silence_run_start = None
            silence_run_len = 0
        idx += win

    if cut_at is None:
        return waveform, False  # 무음 뒤 재발음 패턴 없음(또는 정상 크기의 다음 문장) — 그대로 둔다

    pad = min(int(sample_rate * _TRAILING_ARTIFACT_PAD_MS / 1000), n - cut_at)
    return waveform[: cut_at + pad], True


_TAIL_BOOST_WINDOW_MS = 400  # 분석/부스트 대상 구간 — 끝에서부터 이만큼
_TAIL_BOOST_RAMP_MS = 60  # 경계에서 게인이 갑자기 바뀌면 클릭음이 나서, 이 구간 동안만 서서히 올린다
_TAIL_BOOST_TRIGGER_RATIO = 0.35  # 끝 구간 RMS가 앞부분 RMS의 이 비율보다 작아야 "너무 작다"고 판단
_TAIL_BOOST_TARGET_RATIO = 0.7  # 부스트 목표 = 앞부분 RMS의 이 비율까지만(완전히 맞추면 과할 수 있어 여유를 둠)
_TAIL_BOOST_MAX_GAIN = 4.0  # 무음에 가까운 구간을 노이즈까지 증폭하지 않도록 게인 상한
_TAIL_BOOST_MIN_RMS = 1e-4  # 끝 구간이 이보다도 작으면 "진짜 무음"(발화가 아님)으로 보고 손대지 않는다


def _boost_quiet_tail(
    waveform: np.ndarray, sample_rate: int
) -> tuple[np.ndarray, float | None]:
    """문장 끝 구간이 그 앞보다 확연히 작게 생성됐으면 그 구간만 게인을 올린다.

    반환값은 (보정된 파형, 적용된 게인 — 안 건드렸으면 None). 게인을 로그로 남길 수
    있게 함께 돌려준다(호출부의 [TTS_DEBUG] 참고).
    """
    n = waveform.shape[0]
    tail_samples = int(sample_rate * _TAIL_BOOST_WINDOW_MS / 1000)
    if tail_samples <= 0 or tail_samples >= n:
        return waveform, None  # 문장이 너무 짧아 앞/뒤로 나눌 수 없으면 건드리지 않는다

    tail = waveform[-tail_samples:]
    reference = waveform[:-tail_samples]

    tail_rms = float(np.sqrt(np.mean(np.square(tail))))
    reference_rms = float(np.sqrt(np.mean(np.square(reference))))

    if tail_rms < _TAIL_BOOST_MIN_RMS or reference_rms <= 0:
        return waveform, None  # 진짜 무음 — 노이즈 증폭 방지

    if tail_rms >= reference_rms * _TAIL_BOOST_TRIGGER_RATIO:
        return waveform, None  # 이미 충분히 크게 생성됨

    gain = min(_TAIL_BOOST_MAX_GAIN, (reference_rms * _TAIL_BOOST_TARGET_RATIO) / tail_rms)

    ramp_samples = min(int(sample_rate * _TAIL_BOOST_RAMP_MS / 1000), tail_samples)
    gain_curve = np.full(tail_samples, gain, dtype=np.float32)
    if ramp_samples > 0:
        gain_curve[:ramp_samples] = np.linspace(1.0, gain, ramp_samples, dtype=np.float32)
    if waveform.ndim > 1:
        gain_curve = gain_curve[:, None]

    boosted = waveform.copy()
    boosted[-tail_samples:] = tail * gain_curve
    np.clip(boosted, -1.0, 1.0, out=boosted)
    return boosted, gain


def tts_synthesize(
    text: str,
    *,
    language: str = "Korean",
    instruct: str = "",
    max_new_tokens: int | None = None,
    seed: int = DEFAULT_SEED,
    session_id: str | None = None,
) -> tuple[np.ndarray, int]:
    """조리 안내 문장 하나 -> (waveform, sample_rate)."""

    if max_new_tokens is None:
        max_new_tokens = _dynamic_max_new_tokens(text)

    model = load_tts_model()

    model_type = getattr(model.model, "tts_model_type", None)

    # 화면 표시/로그/DB용 원문(text)은 그대로 두고, TTS에 넘길 사본에만 발음 보정을 적용.
    tts_text = apply_pronunciation_fixes(text)

    best_wavs = None
    best_sample_rate = None
    best_ratio = -1.0
    best_seed = seed
    attempts_used = 0

    for attempt in range(_TAIL_SILENCE_MAX_ATTEMPTS):
        attempt_seed = seed if attempt == 0 else seed + attempt * 1000

        torch.manual_seed(attempt_seed)

        if torch.cuda.is_available():

            torch.cuda.manual_seed_all(attempt_seed)

        wavs, sample_rate = _generate_once(model, model_type, tts_text, language, instruct, max_new_tokens)
        attempts_used = attempt + 1

        ratio = _tail_silence_ratio(wavs[0], sample_rate)
        # ratio가 None이면(문장이 너무 짧아 판정 불가) 무조건 이번 결과를 채택 —
        # best_ratio를 1.0으로 취급해서 아래 break도 같이 타게 한다.
        effective_ratio = 1.0 if ratio is None else ratio
        if effective_ratio > best_ratio:
            best_wavs, best_sample_rate, best_ratio, best_seed = wavs, sample_rate, effective_ratio, attempt_seed

        if effective_ratio >= _TAIL_SILENCE_TRIGGER_RATIO:
            break  # 무음 아님(또는 판정 불가) — 이 결과로 확정, 재시도 안 함

    wavs, sample_rate = best_wavs, best_sample_rate


    trimmed_wav, trailing_trimmed = _trim_trailing_artifact(wavs[0], sample_rate)
    waveform, tail_boost_gain = _boost_quiet_tail(trimmed_wav, sample_rate)

    duration_s = len(waveform) / sample_rate
    print(
        f"[TTS_DEBUG] sid={session_id} text_len={len(text)} max_new_tokens={max_new_tokens} "
        f"duration_s={duration_s:.2f} implied_tokens_per_s={max_new_tokens / duration_s:.1f} "
        f"trailing_trimmed={trailing_trimmed} "
        f"tail_boost_gain={tail_boost_gain} "
        f"tail_attempts={attempts_used} tail_ratio={best_ratio:.3f} seed_used={best_seed} "
        f"text={text[-15:]!r}(끝부분)",
        flush=True,
    )

    return waveform, sample_rate
