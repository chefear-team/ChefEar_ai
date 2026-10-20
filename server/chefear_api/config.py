"""환경변수 설정. 값은 .env 또는 배포 환경(Modal 비밀값)에서 읽는다 — 코드에 넣지 않는다."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str  # 서버 전용(service_role). 웹에는 절대 주지 않는다.
    supabase_anon_key: str  # 토큰 확인용 apikey. 없으면 supabase_key를 쓴다.
    inference_backend: str  # modal | http | none
    modal_app_name: str
    stt_url: str
    tts_url: str
    recipe_audio_url: str
    warmup_url: str
    inference_token: str
    allowed_origins: tuple[str, ...]
    allow_dev_user: bool  # 로컬 개발용: x-dev-user 헤더를 로그인으로 취급
    register_daily_limit: int
    stt_rate_per_min: int
    tts_rate_per_min: int
    max_audio_bytes: int
    tts_public_bucket: str
    tts_private_bucket: str

    @property
    def auth_apikey(self) -> str:
        return self.supabase_anon_key or self.supabase_key

    def public_audio_url(self, key: str) -> str:
        return f"{self.supabase_url}/storage/v1/object/public/{self.tts_public_bucket}/standard/{key}.mp3"


def get_settings() -> Settings:
    origins = tuple(o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip())
    return Settings(
        supabase_url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
        supabase_key=os.environ.get("SUPABASE_KEY", ""),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        inference_backend=os.environ.get("INFERENCE_BACKEND", "http"),
        modal_app_name=os.environ.get("MODAL_APP_NAME", "chefear"),
        stt_url=os.environ.get("INFERENCE_STT_URL", ""),
        tts_url=os.environ.get("INFERENCE_TTS_URL", ""),
        recipe_audio_url=os.environ.get("INFERENCE_RECIPE_AUDIO_URL", ""),
        warmup_url=os.environ.get("INFERENCE_WARMUP_URL", ""),
        inference_token=os.environ.get("INFERENCE_TOKEN", ""),
        allowed_origins=origins or ("*",),
        allow_dev_user=os.environ.get("ALLOW_DEV_USER", "") == "1",
        register_daily_limit=_int("REGISTER_DAILY_LIMIT", 5),
        stt_rate_per_min=_int("STT_RATE_PER_MIN", 30),
        tts_rate_per_min=_int("TTS_RATE_PER_MIN", 20),
        max_audio_bytes=_int("MAX_AUDIO_BYTES", 2_000_000),
        tts_public_bucket=os.environ.get("TTS_PUBLIC_BUCKET", "tts"),
        tts_private_bucket=os.environ.get("TTS_PRIVATE_BUCKET", "tts-private"),
    )
