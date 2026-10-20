"""ChefEar API (FastAPI). 계약: renewal/API_CONTRACT.md"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from chefear_api import guard
from chefear_api.auth import user_id_from_headers
from chefear_api.config import Settings, get_settings
from chefear_api.inference_client import InferenceClient, InferenceUnavailable
from chefear_api.service import BadRequest, ChefEarService, Forbidden, NotFound


class RateLimiter:
    """IP마다 1분 안의 호출 횟수를 센다(서버 한 대 기준 — 남용 방어용 거친 제한)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 5000:
                self._hits.clear()
            return True


def build_service(settings: Settings) -> ChefEarService:
    """운영 조립: Supabase 세션 저장소 + 음성 색인. 환경변수가 없으면 개발용 메모리 구성."""
    from chefear_api.audio import StaticAudioIndex, SupabaseAudioIndex
    from chefear_api.sessions import MemorySessionStore, SupabaseSessionStore
    from orchestration.db import get_client

    client_factory = get_client
    if settings.supabase_url and settings.supabase_key:
        client = get_client()
        store = SupabaseSessionStore(client)
        audio = SupabaseAudioIndex(settings, client)
    else:  # 로컬 개발: 가짜 DB, 메모리 세션
        store = MemorySessionStore()
        audio = StaticAudioIndex()
    return ChefEarService(settings, store, audio, InferenceClient(settings), client_factory)


def create_app(service: ChefEarService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="ChefEar API", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    limiter = RateLimiter()
    holder: dict[str, ChefEarService] = {}
    max_body = settings.max_audio_bytes + 64 * 1024  # 음성 업로드가 가장 크다. 그보다 큰 본문은 읽지 않고 거절한다.
    ident = re.compile(r"[A-Za-z0-9_-]{1,64}")

    @app.middleware("http")
    async def _guard_http(request: Request, call_next):
        try:
            declared = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "bad_request"}, status_code=400)
        if declared > max_body:
            return JSONResponse({"detail": "payload_too_large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def valid_id(value: str) -> str:
        """경로의 session_id·recipe_id 는 정해진 문자만. 이상한 값은 없는 것과 같게 404."""
        if not ident.fullmatch(value):
            raise HTTPException(404, "not_found")
        return value

    async def json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — 깨진 JSON 은 500 이 아니라 400
            raise HTTPException(400, "bad_json") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "bad_json")
        return body

    def svc() -> ChefEarService:
        if service is not None:
            return service
        if "s" not in holder:
            holder["s"] = build_service(settings)
        return holder["s"]

    def owner(authorization: str | None, dev_user: str | None) -> str | None:
        return user_id_from_headers(settings, authorization, dev_user)

    def member(authorization: str | None, dev_user: str | None) -> str:
        """서비스 전체가 로그인한 사용자 전용이다(GPU 비용 보호). 로그인하지 않았으면 401."""
        who = owner(authorization, dev_user)
        if who is None:
            raise HTTPException(401, "login_required")
        return who

    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Forbidden)
    async def _fb(_: Request, exc: Forbidden):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.exception_handler(BadRequest)
    async def _br(_: Request, exc: BadRequest):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/warmup")
    def warmup(authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        # GPU(STT)는 로그인한 사용자만 깨운다. 비로그인 방문(봇 포함)이 페이지만 열어도 GPU 요금이 나가는 걸 막는다.
        # API 컨테이너 자체는 이 요청을 받으며 이미 깨어난다(CPU라 싸다).
        if owner(authorization, x_dev_user) is None:
            return {"stt": "login_required"}
        return {"stt": InferenceClient(settings).warmup() if service is None else svc().inference.warmup()}

    @app.post("/api/session")
    async def create_session(authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        return await run_in_threadpool(svc().new_session, member(authorization, x_dev_user))

    @app.get("/api/session/{session_id}")
    async def get_session(session_id: str, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        return await run_in_threadpool(svc().get_state, valid_id(session_id), member(authorization, x_dev_user))

    @app.post("/api/session/{session_id}/utterance")
    async def utterance(
        session_id: str, request: Request, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)
    ):
        who = member(authorization, x_dev_user)
        if not limiter.allow(f"u:{client_ip(request)}", settings.stt_rate_per_min):
            raise HTTPException(429, "rate_limited")
        ctype = request.headers.get("content-type", "")
        transcript: str | None = None
        if ctype.startswith("application/json"):
            body = await json_body(request)
            text = body.get("text", "")
            if not isinstance(text, str):
                raise HTTPException(400, "invalid_input")
        else:
            form = await request.form()
            upload = form.get("audio")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(400, "audio_required")
            wav = await upload.read()
            if len(wav) > settings.max_audio_bytes:
                raise HTTPException(413, "audio_too_large")
            try:
                text = await run_in_threadpool(svc().inference.transcribe, wav)
            except InferenceUnavailable as exc:
                print(f"[api] STT 사용 불가: {exc!r}", flush=True)
                raise HTTPException(503, "stt_unavailable") from exc
            transcript = text
        state = await run_in_threadpool(svc().utterance, valid_id(session_id), text, who)
        state["transcript"] = transcript
        return state

    @app.post("/api/session/{session_id}/action")
    async def action(
        session_id: str, request: Request, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)
    ):
        who = member(authorization, x_dev_user)
        body = await json_body(request)
        return await run_in_threadpool(svc().action, valid_id(session_id), body, who)

    @app.post("/api/tts")
    async def tts(request: Request, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        member(authorization, x_dev_user)
        if not limiter.allow(f"t:{client_ip(request)}", settings.tts_rate_per_min):
            raise HTTPException(429, "rate_limited")
        body = await json_body(request)
        try:
            text = guard.check_text(body.get("text", ""), max_len=guard.MAX_TTS, field="tts")
        except guard.InputRejected as exc:
            raise HTTPException(400, "bad_text") from exc
        if not text:
            raise HTTPException(400, "bad_text")
        try:
            audio = await run_in_threadpool(svc().inference.synthesize, text)
        except InferenceUnavailable as exc:
            print(f"[api] TTS 사용 불가: {exc!r}", flush=True)
            raise HTTPException(503, "tts_unavailable") from exc
        return Response(content=audio, media_type="audio/mpeg")

    @app.get("/api/my-recipes")
    async def my_recipes(authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        return await run_in_threadpool(svc().list_my_recipes, owner(authorization, x_dev_user))

    @app.get("/api/my-recipes/{recipe_id}")
    async def my_recipe(recipe_id: str, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)):
        return await run_in_threadpool(svc().get_my_recipe, valid_id(recipe_id), owner(authorization, x_dev_user))

    @app.put("/api/my-recipes/{recipe_id}")
    async def put_my_recipe(
        recipe_id: str, request: Request, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)
    ):
        who = owner(authorization, x_dev_user)
        body = await json_body(request)
        return await run_in_threadpool(svc().update_my_recipe, valid_id(recipe_id), body, who)

    @app.delete("/api/my-recipes/{recipe_id}")
    async def delete_my_recipe(
        recipe_id: str, authorization: str | None = Header(None), x_dev_user: str | None = Header(None)
    ):
        return await run_in_threadpool(svc().delete_my_recipe, valid_id(recipe_id), owner(authorization, x_dev_user))

    return app


def app_factory() -> FastAPI:
    """uvicorn chefear_api.main:app_factory --factory"""
    return create_app()
