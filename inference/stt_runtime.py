"""STT 한 번 처리: WAV 바이트 -> 텍스트. 모델 객체는 밖에서 넣는다(테스트는 가짜 모델).

기존 stt.infer.stt_transcribe()와 같은 후처리(환각 방어, 단위 정규화)를 stt.postprocess로 공유한다.
"""
from __future__ import annotations

import io
from typing import Callable

from stt.postprocess import _looks_like_hallucination, correct_high_risk_with_context, normalize_stt_text

NO_SPEECH_LIMIT = 0.85


TARGET_SR = 16000


def _default_decode(wav: bytes):
    """WAV/MP3 바이트 -> 16kHz 모노 float32.

    faster-whisper의 decode_audio는 av 버전에 따라 깨진다(av 19에서 TypeError 확인). 웹이 보내는 건 16kHz 모노 WAV이므로
    soundfile로 직접 읽고, 16kHz가 아니면 resample_poly로 맞춘다. soundfile이 못 읽는 형식(webm 등)만 av로 넘긴다.
    """
    import numpy as np
    import soundfile as sf

    try:
        data, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 — 읽을 수 없는 형식은 마지막 수단으로 av
        from faster_whisper.audio import decode_audio

        return decode_audio(io.BytesIO(wav), sampling_rate=TARGET_SR)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if sr != TARGET_SR:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(sr), TARGET_SR)
        mono = resample_poly(mono, TARGET_SR // g, int(sr) // g).astype(np.float32)
    return np.ascontiguousarray(mono, dtype=np.float32)


def clean_segments(segments) -> str:
    """faster-whisper 구간 목록 -> 최종 텍스트(빈 문자열이면 못 알아들은 것)."""
    segments = list(segments)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    if not text:
        return ""
    if max((s.no_speech_prob for s in segments), default=0.0) > NO_SPEECH_LIMIT:
        return ""  # 말이 아닌 소리를 글자로 지어낸 것
    if _looks_like_hallucination(text):
        return ""
    if "�" in text:
        return ""
    return correct_high_risk_with_context(normalize_stt_text(text), None)


def transcribe_wav(model, wav: bytes, *, vad_filter: bool = False, decode: Callable = _default_decode) -> str:
    """브라우저가 이미 말한 구간만 잘라 보내므로 기본은 내부 VAD를 끈다(이중 필터로 작은 목소리가 걸러지던 이력)."""
    if not wav or len(wav) < 44:
        return ""
    audio = decode(wav)
    segments, _info = model.transcribe(audio, language="ko", vad_filter=vad_filter, beam_size=1)
    return clean_segments(segments)
