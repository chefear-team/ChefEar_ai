import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "server", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 이 PC에는 sentence-transformers가 없다. 의도 분류 모델은 테스트에서 키워드 분류기로 바꿔 끼우므로
# import만 통과시키는 빈 모듈을 둔다(진짜 모델이 설치된 환경에서는 쓰이지 않는다).
try:
    import sentence_transformers  # noqa: F401
except ImportError:
    stub = types.ModuleType("sentence_transformers")
    stub.SentenceTransformer = object
    sys.modules["sentence_transformers"] = stub

from chefear_api.audio import StaticAudioIndex  # noqa: E402
from chefear_api.config import Settings  # noqa: E402
from chefear_api.service import ChefEarService  # noqa: E402
from chefear_api.sessions import MemorySessionStore  # noqa: E402
from fake_supabase import FakeSupabaseClient  # noqa: E402


def make_settings(**over) -> Settings:
    base = dict(
        supabase_url="", supabase_key="", supabase_anon_key="", inference_backend="http", modal_app_name="chefear", stt_url="", tts_url="", recipe_audio_url="",
        warmup_url="", inference_token="t", allowed_origins=("*",), allow_dev_user=True,
        register_daily_limit=2, stt_rate_per_min=100, tts_rate_per_min=100, max_audio_bytes=1_000_000,
        tts_public_bucket="tts", tts_private_bucket="tts-private",
    )
    base.update(over)
    return Settings(**base)


def fake_classify(utterance, context_recipe_id=None):
    """키워드로 흉내 내는 의도 분류(진짜는 임베딩 유사도). 맥락 규칙(조리 중 조회·등록 무시)은 진짜와 같다."""
    text = (utterance or "").strip()
    if not text:
        return {"intent": "미분류", "similarity_score": 0.0, "fallback_message": "다시 말씀해주세요."}
    if "다음" in text:
        intent = "진행"
    elif "다시" in text:
        intent = "재청취"
    elif "이전" in text:
        intent = "이전"
    elif text in ("와", "오"):
        intent = "감탄사"
    elif "올리고 싶" in text or "등록" in text:
        intent = "등록"
    elif "만들" in text or "레시피" in text:
        intent = "조회"
    else:
        intent = "미분류"
    if intent in ("등록", "조회") and context_recipe_id:
        intent = "미분류"
    if intent == "미분류":
        return {"intent": "미분류", "similarity_score": 0.1, "fallback_message": "잘 이해하지 못했어요."}
    return {"intent": intent, "similarity_score": 0.9, "matched_example": text}


class FakeInference:
    def __init__(self):
        self.queued: list[tuple[str, str]] = []
        self.transcript = "된장찌개 어떻게 만들어"
        self.fail = False

    def transcribe(self, wav: bytes) -> str:
        from chefear_api.inference_client import InferenceUnavailable

        if self.fail:
            raise InferenceUnavailable("down")
        return self.transcript

    def synthesize(self, text: str) -> bytes:
        return b"ID3fake"

    def queue_recipe_audio(self, recipe_id, owner_id):
        self.queued.append((recipe_id, owner_id))
        return True

    def warmup(self):
        return "warming"


@pytest.fixture(autouse=True)
def _patch_classifier(monkeypatch):
    import orchestration.pipeline as pipeline

    monkeypatch.setattr(pipeline, "classify_intent", fake_classify)


@pytest.fixture
def world():
    """레시피 2개(표준 1개 + 다른 사람 등록 1개)가 든 가짜 DB와 서비스."""
    client = FakeSupabaseClient()
    recipe = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "[재료] 두부| 감자", "source": "api_standard"}
    )
    steps = [
        "1. 두부, 감자를 깍둑썰기 해주세요.\n[TERM:깍둑썰기]",
        "2. 물을 끓여 주세요.",
        "3. 된장을 풀어 끓여 주세요.",
    ]
    for i, text in enumerate(steps, start=1):
        client.table("recipe_steps").seed(
            {"recipe_id": recipe["id"], "step_number": i, "step_text": text, "source": "api_standard"}
        )
    other = client.table("recipes").seed(
        {"dish_name": "문어초무침", "ingredients": "문어", "source": "user_custom", "owner_id": "other-user"}
    )
    client.table("recipe_steps").seed(
        {"recipe_id": other["id"], "step_number": 1, "step_text": "1. 문어를 데쳐요.", "source": "user_custom"}
    )
    inference = FakeInference()
    audio = StaticAudioIndex()
    service = ChefEarService(make_settings(), MemorySessionStore(), audio, inference, lambda: client)
    return types.SimpleNamespace(
        client=client, service=service, inference=inference, audio=audio, recipe=recipe, other=other, steps=steps
    )
