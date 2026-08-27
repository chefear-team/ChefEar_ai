"""ChefEar 관리자 페이지 2FA — 화자검증(ECAPA-TDNN).

docs/specs/admin_voice_2fa.md 참고. 관리자 페이지(`/admin`) 접근은 2단계다:
  1차 = `.env`의 `ADMIN_ACCESS_TOKEN` (`?admin_key=`, `app.py::_admin_gate_ok()`)
  2차 = 화면에 뜬 랜덤 한글 단어 3개를 읽은 녹음을, 등록된 관리자 목소리와 대조 (이 모듈)

[모델] `speechbrain/spkrec-ecapa-voxceleb` — ECAPA-TDNN, 192-dim 화자 임베딩.
VoxCeleb 학습, 파라미터 ~22M로 작다.

[배포 — CPU 전용] 팀 GPU 데스크탑(RTX 5070, 12GB)은 STT/TTS/LLM/문장임베딩으로 이미
VRAM 여유가 ~1GB뿐이라 여기에 못 올린다. 관리자 인증은 드물고 지연에 둔감해서
(5초 클립 CPU 임베딩 ~1~2초) CPU로 충분하다 — 그래서 `_GPU_LOCK`도 안 잡는다.
챌린지 단어 인식용 STT(`stt_transcribe`)만 GPU를 쓰고, 그건 호출부
(`ui/screens/admin_auth.py`)가 `_GPU_LOCK`으로 감싼다.

[torchaudio 심] 이 저장소 배포 venv는 torchaudio 2.11인데 speechbrain 1.0.2가
`torchaudio.list_audio_backends()`(2.9+에서 제거됨)를 import 시점에 부른다 —
speechbrain을 import하기 전에 이 함수를 심어준다(soundfile 백엔드만 쓰므로 무해).

[성문 저장] `data/admin_voiceprints.json` — `{이름: {"embedding": [192 float],
"sample_count": int, "updated_at": iso}}`. Supabase 테이블 대신 파일을 쓰는 이유:
저장소 폴더가 네트워크 공유라 파일도 기기 간 공유되고, 관리자가 소수라 파일 하나로
충분하며, Supabase DDL을 사람이 대시보드에서 직접 실행하는 단계를 생략할 수 있다.
관리자 제거 = 이 dict에서 키 삭제. 나중에 필요하면 verify/enroll 인터페이스는 그대로
두고 저장소만 Supabase로 바꾸면 된다.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

import numpy as np

from orchestration.db import load_env

load_env()

_MODEL_ID = os.environ.get("ADMIN_SPEAKER_MODEL") or "speechbrain/spkrec-ecapa-voxceleb"
_THRESHOLD = float(os.environ.get("ADMIN_VOICE_THRESHOLD", "0.55"))
_SAMPLE_RATE = 16000

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 로컬 우선: models/spkrec-ecapa-voxceleb/ 에 체크포인트가 있으면 그걸 쓰고(네트워크
# 안 탐), 없으면 HF에서 받아 이 폴더에 캐싱한다.
_LOCAL_MODEL_DIR = Path(
    os.environ.get("ADMIN_SPEAKER_DIR") or (_PROJECT_ROOT / "models" / "spkrec-ecapa-voxceleb")
).expanduser()

_VOICEPRINT_FILE = Path(
    os.environ.get("ADMIN_VOICEPRINT_FILE") or (_PROJECT_ROOT / "data" / "admin_voiceprints.json")
).expanduser()

_model = None
_LOAD_LOCK = threading.Lock()


def load_speaker_model():
    """ECAPA-TDNN을 최초 1회 CPU로 로드하고 재사용한다(llm/infer.py::load_llm()과 같은
    지연 로드 + 이중확인 잠금 패턴). 실패는 예외를 그대로 올린다 — 호출부가 잡아
    "검증 실패(fail-closed)"로 처리한다(spec EC-11)."""
    global _model
    if _model is not None:
        return _model
    with _LOAD_LOCK:
        if _model is not None:
            return _model

        import torchaudio

        # torchaudio 2.9+ 에서 제거된 함수를 speechbrain(check_torchaudio_backend)이
        # import 시점에 부른다 — soundfile 백엔드만 쓰므로 무해한 심을 넣는다.
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]

        from speechbrain.inference.speaker import EncoderClassifier

        source = str(_LOCAL_MODEL_DIR) if (_LOCAL_MODEL_DIR / "hyperparams.yaml").exists() else _MODEL_ID
        _model = EncoderClassifier.from_hparams(
            source=source,
            savedir=str(_LOCAL_MODEL_DIR),
            run_opts={"device": "cpu"},
        )
        return _model


def _to_waveform(audio, sample_rate: int | None = None) -> np.ndarray:
    """파일 경로 / bytes / 파일류 객체(st.audio_input 결과) / numpy 파형 →
    16kHz 모노 float32 1D numpy, 진폭 정규화(피크 0.95)."""
    import soundfile as sf

    if isinstance(audio, np.ndarray):
        wav = audio.astype(np.float32)
        sr = sample_rate or _SAMPLE_RATE
    else:
        if hasattr(audio, "getvalue"):
            raw = audio.getvalue()
        elif hasattr(audio, "read"):
            raw = audio.read()
        elif isinstance(audio, (bytes, bytearray)):
            raw = bytes(audio)
        else:
            raw = None
        src = io.BytesIO(raw) if raw is not None else str(audio)
        try:
            wav, sr = sf.read(src, dtype="float32", always_2d=False)
        except Exception:
            # WAV가 아닌 포맷(m4a 등) — st.audio_input()은 WAV라 실서비스엔 안 오지만
            # 테스트/디버그 덤프 대응으로 librosa(ffmpeg 백엔드) 폴백.
            import librosa

            if isinstance(src, io.BytesIO):
                src.seek(0)
            wav, sr = librosa.load(src, sr=_SAMPLE_RATE, mono=True)

    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != _SAMPLE_RATE:
        import librosa

        wav = librosa.resample(np.ascontiguousarray(wav, dtype=np.float32), orig_sr=sr, target_sr=_SAMPLE_RATE)
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak > 0:
        wav = wav * (0.95 / peak)
    return wav


def embed(audio, sample_rate: int | None = None) -> np.ndarray:
    """오디오 하나 → 192-dim L2정규화 화자 임베딩(numpy float32). CPU 추론."""
    import torch

    wav = _to_waveform(audio, sample_rate)
    model = load_speaker_model()
    with torch.no_grad():
        t = torch.from_numpy(wav).unsqueeze(0)  # (1, T)
        emb = model.encode_batch(t).reshape(-1).cpu().numpy().astype(np.float32)
    norm = float(np.linalg.norm(emb))
    return emb / norm if norm > 0 else emb


def _load_voiceprints() -> dict:
    if not _VOICEPRINT_FILE.exists():
        return {}
    try:
        return json.loads(_VOICEPRINT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_voiceprints(data: dict) -> None:
    _VOICEPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _VOICEPRINT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_VOICEPRINT_FILE)


def list_admins() -> list[str]:
    return sorted(_load_voiceprints().keys())


def verify(audio, sample_rate: int | None = None) -> tuple[bool, str | None, float]:
    """녹음 → 등록된 전 관리자 임베딩과 코사인 유사도.
    반환 (통과여부, 매칭된 이름 또는 None, 최대 유사도).
    등록된 성문이 하나도 없으면 (False, None, 0.0) — fail-closed(spec EC-04/EC-06)."""
    prints = _load_voiceprints()
    if not prints:
        return False, None, 0.0
    q = embed(audio, sample_rate)  # 이미 L2정규화
    best_name, best_sim = None, -1.0
    for name, rec in prints.items():
        e = np.asarray(rec.get("embedding", []), dtype=np.float32)
        if e.size != q.size:
            continue
        n = float(np.linalg.norm(e))
        sim = float(np.dot(q, e / n)) if n > 0 else -1.0
        if sim > best_sim:
            best_name, best_sim = name, sim
    if best_name is None:
        return False, None, 0.0
    return (best_sim >= _THRESHOLD), best_name, best_sim


def enroll(name: str, audios: list, sample_rate: int | None = None) -> None:
    """녹음 여러 개 → 임베딩 평균(L2정규화) → data/admin_voiceprints.json 에 UPSERT.
    같은 이름이면 덮어쓴다(재등록). 이름/샘플이 비면 ValueError."""
    name = (name or "").strip()
    if not name:
        raise ValueError("이름이 비어 있습니다.")
    if not audios:
        raise ValueError("음성 샘플이 없습니다.")
    embs = [embed(a, sample_rate) for a in audios]
    mean = np.mean(np.stack(embs, axis=0), axis=0)
    norm = float(np.linalg.norm(mean))
    if norm > 0:
        mean = mean / norm
    data = _load_voiceprints()
    data[name] = {
        "embedding": [round(float(x), 7) for x in mean.tolist()],
        "sample_count": len(audios),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _save_voiceprints(data)


def remove_admin(name: str) -> bool:
    data = _load_voiceprints()
    if name in data:
        del data[name]
        _save_voiceprints(data)
        return True
    return False
