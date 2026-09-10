"""파인튜닝 어댑터 vs 원본 사전학습 모델 — 실사용자 실제 음성 A/B 비교 스크립트 (진단용, 오프라인 1회 실행)."""
from __future__ import annotations

import sys
from pathlib import Path

import librosa

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stt.infer import stt_transcribe, stt_transcribe_realtime_base  # noqa: E402


def compare_one(audio_path: Path) -> None:
    waveform, sr = librosa.load(str(audio_path), sr=16000)

    finetuned_text = stt_transcribe(waveform, sample_rate=16000)
    base_text = stt_transcribe_realtime_base(waveform, sample_rate=16000)

    print(f"\n=== {audio_path.name} ===")
    print(f"파인튜닝 어댑터(현재 배포): {finetuned_text!r}")
    print(f"원본(파인튜닝 전)        : {base_text!r}")


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python src/stt/compare_realtime_models.py <wav 파일...>")
        raise SystemExit(1)

    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"⚠ 파일 없음, 건너뜀: {path}")
            continue
        compare_one(path)


if __name__ == "__main__":
    main()
