"""파인튜닝 어댑터 vs 원본 사전학습 모델 — 실사용자 실제 음성 A/B 비교 스크립트 (진단용, 오프라인 1회 실행).

배경(2026-08-23 실사용 보고)
--------------------------
상시 마이크로 조용한 환경에서 천천히 말해도 자주 엉뚱하게 인식되는데, TTS로 만든 합성
음성 파일을 같은 파이프라인에 넣으면 잘 알아듣는다는 게 실측으로 확인됐다. 이 STT
어댑터의 학습 데이터(FR-09, `docs/ChefEar_PRD_SDD_v0.8.md`)는 KSS(단일 실제 화자
낭독체) + Qwen3-TTS 합성 음성(텍스트-음성 쌍)뿐이라 — 실제 여러 사용자의 자연스러운
육성(마이크·룸 어쿠스틱·화자 다양성 포함)은 학습 데이터에 전혀 없다. 그래서 "학습
데이터와 닮은 소리(TTS)는 잘 알아듣고, 학습 데이터에 없던 소리(실제 사람 육성)는 잘
못 알아듣는" 전형적인 분포 불일치(train/serve mismatch) 증상일 가능성이 높다.

이 스크립트가 확인하는 것
------------------------
같은 오디오 파일을 두 모델에 그대로 넣어서 인식 결과를 나란히 비교한다.

  1) stt_transcribe()            — 배포 중인 파인튜닝 어댑터(CTranslate2 int8)
  2) stt_transcribe_realtime_base() — 파인튜닝 전 원본 openai/whisper-large-v3-turbo

결과 해석
--------
- 원본 모델이 사용자 육성을 더 잘 알아들으면
    -> 파인튜닝이 "일반 화자에 대한 인식력"을 오히려 깎아먹었다는 뜻(과적합/네거티브
       트랜스퍼 가능성 높음). 실시간 경로를 원본 모델로 되돌리거나, 실제 사람 육성
       데이터를 학습셋에 추가해서 재학습하는 쪽으로 방향을 잡아야 한다.
- 원본 모델도 똑같이 못 알아들으면
    -> 문제는 파인튜닝이 아니라 오디오 캡처 경로(WebRTC 프레임 처리, 리샘플링, VAD
       분할 등, `ui/mic_vad.py`/`src/ui/voice_io.py`) 쪽일 가능성이 높다.

사용법 (GPU 환경, ct2_int8 변환본이 이미 있어야 함 — export_ct2.py 참고)
------------------------------------------------------------------
    python src/stt/compare_realtime_models.py 내목소리1.wav 내목소리2.wav ...

wav는 아무 녹음 앱으로나 "된장찌개" 등 실패했던 문장을 실제 육성으로 녹음해서 준비하면
된다(16kHz가 아니어도 됨 — 두 함수 모두 내부에서 필요시 리샘플링한다).
"""
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
