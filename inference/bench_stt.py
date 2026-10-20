"""0단계: 파인튜닝한 STT를 CPU(2·4 vCPU)와 GPU(L4)에서 돌려 발화당 시간과 정확도(WER)를 잰다.

    modal run inference/bench_stt.py            # 100문장 전체
    modal run inference/bench_stt.py --limit 10 # 빠른 확인

결과는 results/stt/bench_modal.json 에 저장된다. Modal 비밀 `chefear`에 HF_TOKEN, HF_STT_CT2_REPO가 필요하다.
평가셋은 저장소의 Fixed100(합성 음성 100문장)이다 — 실제 목소리 성능이 아니라 기존 수치와 같은 조건의 비교다.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parents[1]
app = modal.App("chefear-bench")
secret = modal.Secret.from_name("chefear")

_base = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04", add_python="3.12")
    .pip_install("faster-whisper==1.2.1", "numpy", "scipy", "soundfile", "huggingface_hub==0.36.2", "jiwer==4.0.0")
    .env({"PYTHONPATH": "/app/src:/app"})
)
image = (
    _base.add_local_dir(REPO / "src", "/app/src", ignore=["**/__pycache__/**", "**/*.pyc", "src/ui/**", "src/app.py"])
    .add_local_dir(REPO / "inference", "/app/inference", ignore=["**/__pycache__/**", "**/*.pyc"])
    .add_local_dir(REPO / "data" / "evaluation_scripts" / "stt", "/app/data/evaluation_scripts/stt")
)


def run_bench(device: str, threads: int, limit: int) -> dict:
    import csv

    import jiwer
    from faster_whisper import WhisperModel

    from inference.stt_runtime import transcribe_wav
    from stt.evaluate_fixed100 import normalize

    base = Path("/app/data/evaluation_scripts/stt")
    rows = list(csv.DictReader((base / "ChefEar_test_fixed_100.csv").open(encoding="utf-8-sig", newline="")))
    rows = rows[:limit] if limit else rows

    t0 = time.perf_counter()
    kwargs = {"cpu_threads": threads} if device == "cpu" else {}
    model = WhisperModel(
        os.environ["HF_STT_CT2_REPO"], device=device, compute_type="int8", use_auth_token=os.environ.get("HF_TOKEN"), **kwargs
    )
    load_s = time.perf_counter() - t0

    times, refs, hyps = [], [], []
    for i, row in enumerate(rows):
        data = (base / "test_audio_100" / f"{row['test_id']}.mp3").read_bytes()
        t = time.perf_counter()
        hyp = transcribe_wav(model, data, vad_filter=False)
        times.append(time.perf_counter() - t)
        refs.append(normalize(row["text"]))
        hyps.append(normalize(hyp))

    steady = times[1:] or times  # 첫 호출은 워밍업이라 따로 본다
    return {
        "device": device,
        "threads": threads,
        "n": len(rows),
        "model_load_s": round(load_s, 2),
        "first_call_s": round(times[0], 2),
        "mean_s": round(statistics.mean(steady), 2),
        "median_s": round(statistics.median(steady), 2),
        "p95_s": round(sorted(steady)[int(0.95 * (len(steady) - 1))], 2),
        "wer": round(jiwer.wer(refs, hyps), 4),
    }


# Modal의 cpu 1.0 = 물리 코어 1개 = 2 vCPU
@app.function(image=image, secrets=[secret], cpu=1.0, memory=4096, timeout=1800, name="bench_cpu_2vcpu")
def bench_cpu_2(limit: int = 100) -> dict:
    return run_bench("cpu", 2, limit)


@app.function(image=image, secrets=[secret], cpu=2.0, memory=4096, timeout=1800, name="bench_cpu_4vcpu")
def bench_cpu_4(limit: int = 100) -> dict:
    return run_bench("cpu", 4, limit)


@app.function(image=image, secrets=[secret], gpu="L4", timeout=1800, name="bench_gpu_l4")
def bench_gpu(limit: int = 100) -> dict:
    return run_bench("cuda", 0, limit)


@app.local_entrypoint()
def main(limit: int = 100):
    results = []
    for fn in (bench_cpu_2, bench_cpu_4, bench_gpu):
        res = fn.remote(limit)
        print(res)
        results.append(res)
    out = REPO / "results" / "stt" / "bench_modal.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장:", out)
