"""ChefEar TTS→STT 라운드트립 검증 (읽기 전용 벤치마크)."""

import argparse
import csv
import string
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

RESULTS_DIR = PROJECT_ROOT / "results" / "tts"
AUDIO_DIR = RESULTS_DIR / "new_sentences_test"
RESULTS_CSV = RESULTS_DIR / "roundtrip_cer.csv"

# 조리 안내 문장 (tests/tts_cpu_inference_test.py의 SENTENCES와 동일 — 실제 TTS가
# 서비스에서 읽게 될 문장 스타일과 맞춤)
SENTENCES = [
    "약불로 5분간 끓여주세요",
    "양파와 마늘을 다진 뒤, 팬에 기름을 두르고 중불에서 노릇하게 볶아주세요",
    "1.5컵의 물을 넣고 뚜껑을 덮은 채로 10분간 졸인 다음, 불을 끄고 5분 정도 뜸을 들여주세요",
    "두부와 감자를 먹기 좋은 크기로 썰어 넣습니다",
    "된장을 풀어줍니다",
]


def _load_sentences(sentences_file: str | None) -> list[str]:
    """--sentences-file이 주어지면 그 텍스트 파일(줄마다 문장 하나)을 쓰고,
    없으면 기본 SENTENCES를 그대로 쓴다."""
    if not sentences_file:
        return SENTENCES
    lines = Path(sentences_file).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def _paths_for(sentences_file: str | None) -> tuple[Path, Path]:
    """오디오 폴더는 항상 AUDIO_DIR(results/tts/new_sentences_test/) 고정 — 문장 세트가
    바뀌어도 wav는 계속 이 폴더에 쌓인다. CSV만 --sentences-file
    이름을 따서 결과가 서로 덮어써지지 않게 분리한다(results/tts/<stem>.csv — 접두사 없이
    파일명 그대로 사용).
    """
    if not sentences_file:
        return AUDIO_DIR, RESULTS_CSV
    stem = Path(sentences_file).stem
    return AUDIO_DIR, RESULTS_DIR / f"{stem}.csv"


def _slugify(text: str, max_len: int = 20) -> str:
    """wav 파일명에 붙일 짧은 텍스트 조각을 만든다 — "01_닭을손질해주세요.wav"처럼
    파일명만 보고도 어느 문장인지 바로 알 수 있게(순번만 있으면 못 알아봄)."""
    keep = "".join(ch for ch in text if ch.isalnum())
    return keep[:max_len] or "untitled"


def normalize(text: str) -> str:
    """비교 전 정규화: 띄어쓰기·구두점 차이로 오류율이 왜곡되는 걸 막는다."""
    text = text.translate(str.maketrans("", "", string.punctuation + "？！。，"))
    return "".join(text.split())


def _run_synthesize(sentences_file: str | None = None):
    """1단계(별도 프로세스): TTS만 로드해서 문장들을 wav 파일로 저장.

    STT(GPU 필요)를 이 환경에서 바로 못 돌리는 경우를 위해, 합성 직후 "text/audio_file/
    duration_sec/status" 열을 가진 중간 CSV(<...>_pending.csv)도 같이 남긴다 — STT를
    나중에 다른(GPU 있는) 환경에서 돌릴 때 이 wav 폴더를 그대로 넘기면 된다.
    """
    import soundfile as sf

    from tts.infer import tts_synthesize

    sentences = _load_sentences(sentences_file)
    audio_dir, results_csv = _paths_for(sentences_file)
    pending_csv = results_csv.with_name(results_csv.stem + "_pending.csv")

    audio_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, text in enumerate(sentences):
        waveform, sample_rate = tts_synthesize(text)
        audio_path = audio_dir / f"{i:02d}_{_slugify(text)}.wav"
        sf.write(audio_path, waveform, sample_rate)
        duration_sec = len(waveform) / sample_rate
        rows.append((text, audio_path.name, f"{duration_sec:.2f}", "합성 완료, STT 대기중"))
        print(f"[합성 완료 {duration_sec:.1f}초] {i}: {text}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(pending_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        # "텍스트 : 닭 = 오디오 : 닭"처럼 어느 문장이 어느 wav 파일인지 한눈에 짝지어
        # 보이도록 한글 헤더로 씀(정답지 역할의 텍스트 열 + 실제 소리 파일 열).
        writer.writerow(["텍스트", "오디오", "길이(초)", "상태"])
        writer.writerows(rows)
    print(f"\n오디오 폴더: {audio_dir}")
    print(f"중간 결과 CSV: {pending_csv}")


def _run_transcribe(sentences_file: str | None = None):
    """2단계(별도 프로세스): STT만 로드해서 1단계가 만든 wav들을 인식하고 CER 계산."""
    import jiwer

    from stt.infer import _transcribe_audio, load_stt_model

    sentences = _load_sentences(sentences_file)
    audio_dir, results_csv = _paths_for(sentences_file)

    print("[STT 모델 로드 중 — 최초 1회만 시간 걸림]")
    load_stt_model()

    # 1단계가 남긴 pending CSV에서 실제 파일명을 읽어온다 — wav 파일명이 이제
    # "{순번}_{텍스트 일부}.wav"라 순번만으로 재구성할 수 없음(슬러그 로직을 두 곳에
    # 중복시키지 않기 위해서도 pending CSV를 그대로 신뢰하는 쪽이 안전함).
    pending_csv = results_csv.with_name(results_csv.stem + "_pending.csv")
    with open(pending_csv, encoding="utf-8-sig") as f:
        audio_filenames = [row["오디오"] for row in csv.DictReader(f)]

    rows = []
    for i, text in enumerate(sentences):
        audio_path = audio_dir / audio_filenames[i]
        hypothesis = _transcribe_audio(audio_path)
        cer = jiwer.cer(normalize(text), normalize(hypothesis))
        rows.append((text, hypothesis, f"{cer:.4f}"))
        print(f"[CER={cer:.3f}] 원문='{text}' | 인식='{hypothesis}'")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(results_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["텍스트", "음성인식결과", "CER"])
        writer.writerows(rows)

    avg_cer = sum(float(r[2]) for r in rows) / len(rows)
    print(f"\n평균 CER: {avg_cer:.4f}")
    print(f"결과 저장: {results_csv}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=["synthesize", "transcribe"],
        default=None,
        help="내부용 — 지정 안 하면 두 phase를 별도 프로세스로 순서대로 실행함",
    )
    parser.add_argument(
        "--sentences-file",
        default=None,
        help="줄마다 문장 하나인 텍스트 파일. 지정 안 하면 기본 SENTENCES를 씀",
    )
    args = parser.parse_args()

    if args.phase == "synthesize":
        _run_synthesize(args.sentences_file)
        return
    if args.phase == "transcribe":
        _run_transcribe(args.sentences_file)
        return

    # phase 지정 없이 실행: 자기 자신을 두 번 별도 프로세스로 재실행(위 모듈 docstring의
    # ⚠️ 설명 참고 — 같은 프로세스에 STT+TTS를 같이 두면 안 됨).
    import subprocess

    extra = ["--sentences-file", args.sentences_file] if args.sentences_file else []

    print("=== 1단계: TTS 합성 (별도 프로세스) ===")
    subprocess.run([sys.executable, __file__, "--phase", "synthesize", *extra], check=True)

    print("\n=== 2단계: STT 인식 + WER 계산 (별도 프로세스) ===")
    subprocess.run([sys.executable, __file__, "--phase", "transcribe", *extra], check=True)


if __name__ == "__main__":
    main()
