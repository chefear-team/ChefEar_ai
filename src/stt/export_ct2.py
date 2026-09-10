"""ChefEar STT 배포용 CTranslate2 변환 스크립트 (오프라인, 1회 실행)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import WhisperForConditionalGeneration, WhisperProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from orchestration.db import load_env

load_env()

if not torch.cuda.is_available():
    raise RuntimeError(
        "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
    )

BASE_MODEL_ID = "openai/whisper-large-v3-turbo"
ADAPTER_ID = os.environ.get("HF_STT_MODEL_REPO") or "leeony/chefear-stt-large-v3-turbo"

MERGED_DIR = PROJECT_ROOT / "models" / "stt_finetuned" / "_merged_fp16"
CT2_DIR = PROJECT_ROOT / "models" / "stt_finetuned" / "ct2_int8"


def main() -> None:
    print(f"[1/3] base 모델 로드: {BASE_MODEL_ID} (fp16, GPU — merge_and_unload()는 4bit 양자화 상태로는 안 됨)")
    base_model = WhisperForConditionalGeneration.from_pretrained(
        BASE_MODEL_ID, torch_dtype=torch.float16, device_map="cuda:0"
    )
    processor = WhisperProcessor.from_pretrained(ADAPTER_ID)

    print(f"[2/3] LoRA 어댑터 병합: {ADAPTER_ID}")
    merged = PeftModel.from_pretrained(base_model, ADAPTER_ID).merge_and_unload()
    merged.config.forced_decoder_ids = None
    merged.generation_config.forced_decoder_ids = None

    # save_pretrained()는 GPU 텐서를 그대로 저장하지 않는다(state_dict를 CPU로 옮겨서 저장) —
    # 다만 병합된 모델 자체는 여전히 GPU에 있으므로 다음 실행을 위해 명시적으로 CPU로 옮겨
    # GPU 메모리를 비워둔다(같은 프로세스에서 이후 단계가 GPU를 더 안 쓰긴 하지만, 다른
    # 사용자가 같은 GPU 데스크탑을 공유하는 환경이라 불필요하게 오래 잡고 있지 않는다).
    merged = merged.to("cpu")

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(MERGED_DIR)
    processor.save_pretrained(MERGED_DIR)
    print(f"    병합 모델 저장: {MERGED_DIR}")

    print(f"[3/3] CTranslate2 int8 변환 -> {CT2_DIR}")
    if CT2_DIR.exists():
        shutil.rmtree(CT2_DIR)
    subprocess.run(
        [
            "ct2-transformers-converter",
            "--model", str(MERGED_DIR),
            "--output_dir", str(CT2_DIR),
            "--quantization", "int8",
        ],
        check=True,
    )

    preprocessor_src = MERGED_DIR / "preprocessor_config.json"
    if preprocessor_src.exists():
        shutil.copy(preprocessor_src, CT2_DIR / "preprocessor_config.json")
        print("    preprocessor_config.json 복사 완료(feature_size=128 유지)")
    else:
        print("    ⚠ preprocessor_config.json이 병합 모델에도 없음 — 수동 확인 필요")

    print(f"✅ 변환 완료: {CT2_DIR}")
    print("   반입(HF Hub 업로드 여부)은 별도 결정 필요 — docs/specs/stt_deploy.md의 Open Issue 참고.")


if __name__ == "__main__":
    main()
