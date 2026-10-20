"""ChefEar Modal 앱: API(CPU) + STT + TTS + 등록 음성 생성. 배포: `modal deploy inference/modal_app.py`

구성(전부 안 쓰면 0대로 줄어든다 — 마지막 요청 뒤 SCALEDOWN_S(5분) 동안만 켜져 있다):
- api          : FastAPI(CPU). 웹이 부르는 유일한 공개 주소.
- Stt          : 파인튜닝한 Whisper(CT2 int8). GPU 또는 CPU(CHEFEAR_STT_GPU 환경변수로 배포 때 고른다).
- Tts          : 실시간 합성(미리 만들어 두지 않은 문장만). 공개 주소 없음 — API가 SDK로만 부른다.
- RecipeAudio  : 등록·수정한 레시피 음성 생성(배치). 동시에 1대만.

비밀값은 Modal 비밀 `chefear`에 넣는다(docs: renewal/DEPLOY.md). 코드에는 값이 없다.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = os.environ.get("MODAL_APP_NAME", "chefear")
SCALEDOWN_S = 300  # 마지막 요청 뒤 5분 동안 켜 둔다(요리 중 말이 끊겨도 다시 깨어나지 않게)
STT_GPU = os.environ.get("CHEFEAR_STT_GPU") or None  # 예: "L4". 비우면 CPU로 돌린다(0단계 측정 결과로 결정).
TTS_GPU = os.environ.get("CHEFEAR_TTS_GPU", "L4")
REPO = Path(__file__).resolve().parents[1]

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("chefear")

_IGNORE = ["**/__pycache__/**", "**/*.pyc", "src/ui/**", "src/app.py"]


def with_code(image: modal.Image) -> modal.Image:
    """저장소 코드(src, server, inference, 의도 예문)를 이미지에 넣는다.

    Modal 규칙: add_local_*는 이미지 빌드 단계의 맨 마지막이어야 한다(그 뒤에 pip_install·env 등을 붙이면 배포 때 실패).
    그래서 설치·환경변수 단계를 전부 끝낸 이미지를 이 함수에 넘긴다.
    """
    return (
        image.env({"PYTHONPATH": "/app/src:/app/server:/app", "USE_TF": "0"})
        .add_local_dir(REPO / "src", "/app/src", ignore=_IGNORE)
        .add_local_dir(REPO / "server", "/app/server", ignore=["**/__pycache__/**", "**/*.pyc"])
        .add_local_dir(REPO / "inference", "/app/inference", ignore=["**/__pycache__/**", "**/*.pyc"])
        .add_local_dir(REPO / "data" / "intent_examples", "/app/data/intent_examples")
    )


CUDA_BASE = "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04"


# ── 모델 파일을 이미지에 미리 받아 둔다 ─────────────────────────────────────────
# 컨테이너가 켜질 때마다 Hugging Face에서 내려받지 않게 이미지 빌드 때 한 번만 받는다(콜드 스타트 단축).
# 줄어드는 건 내려받는 시간뿐이다 — GPU 메모리에 올리는 시간은 그대로다. 비밀값 chefear(HF_TOKEN)는 빌드 때만 쓰이고
# 이미지에 남지 않는다. 모델을 새로 올렸다면 `modal deploy` 때 force_build로 다시 받아야 한다(아래 주석 참고).
def _bake_stt() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(os.environ["HF_STT_CT2_REPO"], token=os.environ.get("HF_TOKEN"))


def _bake_tts() -> None:
    """저장소 파일 + qwen-tts가 로드 때 따로 받는 것까지 한 번 로드해서 전부 캐시에 넣는다(빌드 때 GPU를 잠깐 쓴다)."""
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel
    from transformers import AutoTokenizer

    repo = os.environ.get("HF_TTS_MODEL_REPO") or "kimseunguk/qwen3-tts-kss-finetuned"
    token = os.environ.get("HF_TOKEN")
    snapshot_download(repo, token=token)
    Qwen3TTSModel.from_pretrained(repo, token=token, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    AutoTokenizer.from_pretrained(repo, token=token)


# 모델이 바뀌었는데 이미지가 그대로 쓰이면 예전 모델이 쓰인다. 모델을 새로 올렸다면 아래 BAKE_VERSION을 올린다.
BAKE_VERSION = "1"

_stt_base = (
    modal.Image.from_registry(CUDA_BASE, add_python="3.12")
    .pip_install("faster-whisper==1.2.1", "numpy", "scipy", "soundfile", "huggingface_hub==0.36.2")
    .env({"CHEFEAR_BAKE_VERSION": BAKE_VERSION})
    .run_function(_bake_stt, secrets=[secret])
)
stt_image = with_code(_stt_base)

_tts_base = (
    modal.Image.from_registry(CUDA_BASE, add_python="3.12")
    .apt_install("ffmpeg", "libsndfile1", "sox")  # 기존 Dockerfile과 같은 오디오 시스템 패키지(+ qwen-tts의 sox)
    .pip_install(
        # torch 계열은 반드시 같은 버전으로 맞춘다(기존 Dockerfile과 동일). torchaudio를 고정하지 않으면 qwen-tts가
        # 최신 torchaudio(CUDA 13용)를 끌고 와 torch 2.6.0(CUDA 12.4)과 충돌한다 — 첫 배포에서 실제로 터졌다.
        "torch==2.6.0",
        "torchaudio==2.6.0",
        "torchvision==0.21.0",
        "transformers==4.57.3",
        "accelerate==1.12.0",
        "qwen-tts==0.1.1",
        "huggingface_hub==0.36.2",
        "numpy",
        "soundfile",
    )
    .env({"CHEFEAR_BAKE_VERSION": BAKE_VERSION})
    .run_function(_bake_tts, secrets=[secret], gpu=TTS_GPU)
)
tts_image = with_code(_tts_base)
recipe_audio_image = with_code(_tts_base.pip_install("supabase==2.31.0"))


def _download_embedder() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer("jhgan/ko-sroberta-multitask")


api_image = with_code(
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.6.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install(
        "sentence-transformers==5.6.1",
        "fastapi==0.141.1",
        "httpx==0.28.1",
        "python-multipart==0.0.32",
        "supabase==2.31.0",
        "modal",
        "numpy",
    )
    .run_function(_download_embedder)  # 의도 분류 모델을 이미지에 미리 받아 둔다(콜드 스타트 단축)
)


# ── API ────────────────────────────────────────────────────────────────
@app.function(image=api_image, secrets=[secret], cpu=2.0, memory=3072, scaledown_window=SCALEDOWN_S, timeout=300)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def api():
    from orchestration.intent_classifier import _example_embeddings

    _example_embeddings()  # 컨테이너가 뜰 때 한 번 데워 첫 요청이 느리지 않게
    from chefear_api.main import create_app

    return create_app()


# ── STT ────────────────────────────────────────────────────────────────
@app.cls(image=stt_image, gpu=STT_GPU, secrets=[secret], scaledown_window=SCALEDOWN_S, timeout=600, max_containers=2)
class Stt:
    @modal.enter()
    def load(self) -> None:
        from faster_whisper import WhisperModel

        repo = os.environ.get("HF_STT_CT2_REPO")
        if not repo:
            raise RuntimeError("비밀값 HF_STT_CT2_REPO가 없다")
        device = "cuda" if STT_GPU else "cpu"
        kwargs = {"cpu_threads": int(os.environ.get("STT_CPU_THREADS", "4"))} if device == "cpu" else {}
        self.model = WhisperModel(
            repo, device=device, compute_type="int8", use_auth_token=os.environ.get("HF_TOKEN"), **kwargs
        )

    @modal.method()
    def transcribe(self, wav: bytes) -> str:
        from inference.stt_runtime import transcribe_wav

        vad = os.environ.get("STT_VAD_FILTER", "0") == "1"
        return transcribe_wav(self.model, wav, vad_filter=vad)

    @modal.method()
    def warmup(self) -> bool:
        return True


# ── TTS(실시간, 미리 만들어 두지 않은 문장만) ───────────────────────────
@app.cls(image=tts_image, gpu=TTS_GPU, secrets=[secret], scaledown_window=SCALEDOWN_S, timeout=600, max_containers=2)
class Tts:
    @modal.enter()
    def load(self) -> None:
        from tts.infer import load_tts_model

        load_tts_model()

    @modal.method()
    def synthesize(self, text: str) -> bytes:
        from inference.audio_encode import encode_mp3
        from tts.infer import tts_synthesize

        waveform, sample_rate = tts_synthesize(text)
        return encode_mp3(waveform, sample_rate)

    @modal.method()
    def warmup(self) -> bool:
        return True


# ── 등록·수정한 레시피 음성 생성(배치, 동시 1대) ────────────────────────
@app.cls(
    image=recipe_audio_image, gpu=TTS_GPU, secrets=[secret], scaledown_window=60, timeout=1800, max_containers=1
)
class RecipeAudio:
    @modal.enter()
    def load(self) -> None:
        from supabase import create_client
        from tts.infer import load_tts_model

        load_tts_model()
        self.db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    @modal.method()
    def generate(self, recipe_id: str, owner_id: str) -> dict:
        from inference.audio_encode import encode_mp3
        from inference.recipe_audio import generate_for_recipe
        from tts.infer import tts_synthesize

        def synthesize(text: str) -> bytes:
            waveform, sample_rate = tts_synthesize(text)
            return encode_mp3(waveform, sample_rate)

        return generate_for_recipe(self.db, recipe_id, owner_id, synthesize, os.environ.get("TTS_PRIVATE_BUCKET", "tts-private"))
