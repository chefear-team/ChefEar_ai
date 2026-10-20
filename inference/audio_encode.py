"""합성한 파형 -> mp3 바이트(모노, 낮은 비트레이트: 문장당 수십 KB)."""
from __future__ import annotations

import io

import numpy as np
import soundfile as sf


def encode_mp3(waveform, sample_rate: int) -> bytes:
    wav = np.asarray(waveform, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=1 if wav.shape[0] > wav.shape[1] else 0)
    wav = np.clip(wav, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, wav, int(sample_rate), format="MP3", subtype="MPEG_LAYER_III")
    return buf.getvalue()
