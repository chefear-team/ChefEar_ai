"""Qwen3-TTS 1.7B CPU 추론 속도 실측 (HF Spaces CPU Basic, 2 vCPU 흉내).

읽기 전용 벤치마크. 학습 스크립트/체크포인트를 건드리지 않는다.

사용 체크포인트 우선순위(2026-08-19 수정 — 이슈: 기존 코드는 models/tts_finetuned/가
비어있으면 곧장 사전학습 베이스로 폴백해서, 실제로는 한 번도 우리 파인튜닝 모델을 재지
않고 있었다):
  1) models/tts_finetuned/ 아래 가장 최근 체크포인트(로컬에 내려받아둔 경우)
  2) 없으면 실제 배포 모델(kimseunguk/qwen3-tts-kss-finetuned, HF Hub private repo,
     src/tts/infer.py의 MODEL_ID와 동일) — HF_TOKEN 필요
  3) 그것도 안 되면(HF_TOKEN 없음 등) 마지막 수단으로 사전학습 베이스
     Qwen/Qwen3-TTS-12Hz-1.7B-Base + 공개 데모 참조 오디오(이 경우 실제 배포 모델 속도가
     아니라는 걸 콘솔에 명시적으로 경고한다)

결과: results/tts/cpu_inference_test.csv (text, run, inference_seconds)
"""

import csv
import os
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""

import torch

torch.set_num_threads(2)

from qwen_tts import Qwen3TTSModel

# 일반 스크립트 실행(`python tests/tts_cpu_inference_test.py`)이면 __file__ 기준으로 잡고,
# Colab/Jupyter 셀에 내용을 붙여넣어 직접 실행한 경우(__file__ 없음)엔 현재 작업 디렉터리를
# 저장소 루트로 가정한다(둘 다 models/tts_finetuned, results/tts는 루트 기준 상대경로라 동일하게 맞음).
if "__file__" in globals():
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
else:
    PROJECT_ROOT = Path.cwd()
CHECKPOINT_DIR = PROJECT_ROOT / "models" / "tts_finetuned"
RESULTS_CSV = PROJECT_ROOT / "results" / "tts" / "cpu_inference_test.csv"
BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

# src/tts/infer.py와 동일한 방식으로 .env를 읽는다(python-dotenv 새로 추가하지 않음).
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from orchestration.db import load_env

load_env()
DEPLOYED_MODEL_ID = os.environ.get("HF_TTS_MODEL_REPO") or "kimseunguk/qwen3-tts-kss-finetuned"
HF_TOKEN = os.environ.get("HF_TOKEN")

# 공식 예제 저장소의 공개 데모 참조 오디오 — 실제 배포 모델을 못 불러왔을 때만(마지막 수단) 씀.
DEMO_REF_AUDIO = "https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-TTS-Repo/clone.wav"
DEMO_REF_TEXT = (
    "Okay. Yeah. I resent you. I love you. I respect you. "
    "But you know what? You blew it! And thanks to you."
)

# src/tts/infer.py와 동일한 실제 배포용 참조 음성(KSS 000008, 한국어) — 실제 배포 모델을
# voice-clone(base 타입)으로 재는 경우 이걸 쓴다.
DEPLOYED_REF_AUDIO = str(PROJECT_ROOT / "src" / "tts" / "assets" / "kss_reference.wav")
DEPLOYED_REF_TEXT = "나는 살아오면서 감기를 앓은 적이 한 번도 없다."

# custom_voice 타입 체크포인트로 되돌아갈 경우를 대비한 화자명 — src/tts/infer.py와 동일
# ("kss_speaker_a100"이 아니라 "kss_speaker", 2026-08-18 실측 확인).
SPEAKER = "kss_speaker"

SENTENCES = [
'양파와 마느를 다진 뒤, 패네 기르믈 두르고 중부레서 노르타게 보까주세요',
'일.오커븨 무를 러코 뚜껑을 더픈 채로 십뿐간 조린 다음, 부를 끄고 오분 정도 뜨믈 드려주세요',
'두부와 감자를 먹끼 조은 크기로 써러 너씀니다',
'된장을 푸러줌니다',
'약뿔로 오분간 끄려주세요',
'소그믈 러코 잘 서꺼주세요',
'고기를 로르타게 구워주세요',
'궁무리 끄르면 부를 주려주세요'


]

RUNS_PER_SENTENCE = 3  # 1회차 워밍업 제외, 2·3회차 평균
TARGET_SECONDS = 5.0

# 체크포인트의 generation_config.json에 max_new_tokens=8192가 박혀있고 do_sample=True라,
# 명시적으로 안 넘기면 EOS를 늦게 뽑는 시행에서 CPU 기준 1시간+까지 폭주할 수 있다(실측: 0.5초/토큰).
# 위 SENTENCES 중 가장 긴 문장도 12Hz 기준 250토큰(~20초 분량)이면 충분히 자연 종료된다.
MAX_NEW_TOKENS = 195


def find_latest_checkpoint(checkpoint_dir: Path) -> Path | None:
    if not checkpoint_dir.exists():
        return None
    candidates = [
        p for p in checkpoint_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main():
    checkpoint = find_latest_checkpoint(CHECKPOINT_DIR)
    token_kwargs = {}
    if checkpoint is not None:
        model_path = str(checkpoint)
        model_source_desc = f"로컬 파인튜닝 체크포인트: {checkpoint}"
        ref_audio, ref_text = DEPLOYED_REF_AUDIO, DEPLOYED_REF_TEXT
    elif HF_TOKEN:
        model_path = DEPLOYED_MODEL_ID
        model_source_desc = f"실제 배포 모델(HF Hub): {DEPLOYED_MODEL_ID}"
        token_kwargs = {"token": HF_TOKEN}
        ref_audio, ref_text = DEPLOYED_REF_AUDIO, DEPLOYED_REF_TEXT
    else:
        model_path = BASE_MODEL_ID
        model_source_desc = (
            f"⚠️ 로컬 체크포인트도 없고 HF_TOKEN도 없어 사전학습 베이스로 폴백: {BASE_MODEL_ID} "
            "— 이 결과는 실제 배포 모델(kimseunguk/qwen3-tts-kss-finetuned)의 속도가 아님, "
            "참고용으로만 취급할 것"
        )
        ref_audio, ref_text = DEMO_REF_AUDIO, DEMO_REF_TEXT

    print(f"[모델 소스] {model_source_desc}")
    print("[양자화] 없음 (float32, CPU, 2 threads)")
    print("[디바이스] CPU 강제 고정 (CUDA_VISIBLE_DEVICES=\"\", torch.set_num_threads(2))")
    print()

    load_start = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        model_path,
        device_map="cpu",
        dtype=torch.float32,
        **token_kwargs,
    )
    load_seconds = time.perf_counter() - load_start
    print(f"[모델 로딩 시간] {load_seconds:.2f}초\n")

    model_type = getattr(model.model, "tts_model_type", None)
    print(f"[모델 타입] {model_type}")
    is_base_model = model_type == "base"

    voice_clone_prompt = None
    if is_base_model:
        prompt_start = time.perf_counter()
        voice_clone_prompt = model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        prompt_seconds = time.perf_counter() - prompt_start
        print(
            f"[참조 오디오 프롬프트 준비 시간] {prompt_seconds:.2f}초 "
            "(로딩 단계로 취급, 문장별 추론 시간에는 미포함)\n"
        )

    rows = []  # (text, run, inference_seconds)
    per_sentence_avg = {}

    for sentence in SENTENCES:
        timings = []
        for run in range(1, RUNS_PER_SENTENCE + 1):
            start = time.perf_counter()
            if model_type == "base":
                model.generate_voice_clone(
                    text=sentence,
                    language="Korean",
                    voice_clone_prompt=voice_clone_prompt,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            elif model_type == "custom_voice":
                model.generate_custom_voice(
                    text=sentence,
                    language="Korean",
                    speaker=SPEAKER,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            else:
                raise ValueError(
                    f"이 벤치마크가 아직 지원하지 않는 tts_model_type={model_type!r} — "
                    "generate_voice_design 등 다른 경로 추가 필요"
                )
            elapsed = time.perf_counter() - start

            tag = "워밍업(제외)" if run == 1 else f"{run}회차"
            print(f"  [{sentence[:20]}...] run {run} ({tag}): {elapsed:.2f}초")

            rows.append((sentence, run, f"{elapsed:.4f}"))
            if run > 1:
                timings.append(elapsed)

        avg = sum(timings) / len(timings)
        per_sentence_avg[sentence] = avg

    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "run", "inference_seconds"])
        writer.writerows(rows)

    print(f"\n결과 저장: {RESULTS_CSV}")

    print("\n=== 결과 요약 ===")
    print(f"모델 로딩 시간(1회): {load_seconds:.2f}초")
    print()
    for sentence, avg in per_sentence_avg.items():
        status = "PASS" if avg <= TARGET_SECONDS else "FAIL"
        print(f"[{status}] 평균 {avg:.2f}초 (목표 {TARGET_SECONDS}초) - \"{sentence}\"")

    overall_avg = sum(per_sentence_avg.values()) / len(per_sentence_avg)
    overall_status = "PASS" if overall_avg <= TARGET_SECONDS else "FAIL"
    print(f"\n[전체 평균] {overall_avg:.2f}초 -> {overall_status}")


if __name__ == "__main__":
    main()
