"""추론 서버 호출. STT·TTS·등록 음성 생성·깨우기.

backend:
- modal: Modal SDK로 배포된 함수를 직접 부른다(운영). STT·TTS를 공개 URL로 열지 않으므로 남이 호출할 수 없다.
- http : 주소(INFERENCE_*_URL) + 공유 토큰으로 부른다(개발·테스트).
- 그 외: 추론 없음(InferenceUnavailable) — 글자 입력과 글자 안내로만 동작한다.
"""
from __future__ import annotations

import threading

import httpx

from chefear_api.config import Settings


class InferenceUnavailable(RuntimeError):
    """추론 서버 주소가 없거나 응답이 없다. 호출한 쪽이 글자 입력·글자 안내로 대신한다."""


class InferenceClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self._s = settings
        self._http = http or httpx.Client()
        self._modal_handles: dict[str, object] = {}
        self._modal_lock = threading.Lock()

    # ── Modal ──────────────────────────────────────────────────────────
    def _use_modal(self) -> bool:
        return self._s.inference_backend == "modal"

    def _modal_obj(self, cls_name: str):
        with self._modal_lock:
            if cls_name not in self._modal_handles:
                import modal  # 운영 이미지에만 있다. 개발 환경에서는 http 방식을 쓴다.

                self._modal_handles[cls_name] = modal.Cls.from_name(self._s.modal_app_name, cls_name)()
            return self._modal_handles[cls_name]

    # ── HTTP ───────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        return {"x-chefear-token": self._s.inference_token}

    # ── 공개 메서드 ────────────────────────────────────────────────────
    def transcribe(self, wav: bytes) -> str:
        if self._use_modal():
            try:
                return str(self._modal_obj("Stt").transcribe.remote(wav)).strip()
            except Exception as exc:  # noqa: BLE001 — modal 예외 종류가 많아 한곳에서 변환
                raise InferenceUnavailable(f"STT 호출 실패: {exc!r}") from exc
        if not self._s.stt_url:
            raise InferenceUnavailable("STT 주소 없음")
        try:
            res = self._http.post(
                self._s.stt_url, content=wav, headers={**self._headers(), "content-type": "audio/wav"}, timeout=90.0
            )
            res.raise_for_status()
            return str(res.json().get("text", "")).strip()
        except (httpx.HTTPError, ValueError) as exc:
            raise InferenceUnavailable(f"STT 호출 실패: {exc!r}") from exc

    def synthesize(self, text: str) -> bytes:
        if self._use_modal():
            try:
                return self._modal_obj("Tts").synthesize.remote(text)
            except Exception as exc:  # noqa: BLE001
                raise InferenceUnavailable(f"TTS 호출 실패: {exc!r}") from exc
        if not self._s.tts_url:
            raise InferenceUnavailable("TTS 주소 없음")
        try:
            res = self._http.post(self._s.tts_url, json={"text": text}, headers=self._headers(), timeout=120.0)
            res.raise_for_status()
            return res.content
        except httpx.HTTPError as exc:
            raise InferenceUnavailable(f"TTS 호출 실패: {exc!r}") from exc

    def queue_recipe_audio(self, recipe_id: str, owner_id: str) -> bool:
        """등록·수정한 레시피의 음성 생성을 요청한다. 기다리지 않고(백그라운드) 요청 성공 여부만 돌려준다."""
        if self._use_modal():
            try:
                self._modal_obj("RecipeAudio").generate.spawn(recipe_id, owner_id)
                return True
            except Exception as exc:  # noqa: BLE001 — 실패해도 레시피 저장은 끝난 뒤라 재생 때 실시간 합성으로 대체
                print(f"[inference] 등록 음성 생성 요청 실패(재생 때 실시간 합성으로 대체): {exc!r}", flush=True)
                return False
        if not self._s.recipe_audio_url:
            return False

        def _call() -> None:
            try:
                self._http.post(
                    self._s.recipe_audio_url,
                    json={"recipe_id": recipe_id, "owner_id": owner_id},
                    headers=self._headers(),
                    timeout=30.0,
                )
            except httpx.HTTPError as exc:
                print(f"[inference] 등록 음성 생성 요청 실패(재생 때 실시간 합성으로 대체): {exc!r}", flush=True)

        threading.Thread(target=_call, daemon=True).start()
        return True

    def warmup(self) -> str:
        """STT 컨테이너를 미리 깨운다(기다리지 않는다).

        TTS는 깨우지 않는다 — 조리 흐름은 미리 만든 음성을 재생하므로 쓰지 않는 GPU를 5분 켜 두는 낭비가 된다.
        미리 만든 음성이 없는 문장이 나왔을 때 /api/tts가 그때 깨운다.
        """
        if self._use_modal():
            def _call() -> None:
                for name in ("Stt",):
                    try:
                        self._modal_obj(name).warmup.spawn()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[inference] {name} 깨우기 실패: {exc!r}", flush=True)

            threading.Thread(target=_call, daemon=True).start()
            return "warming"
        if not self._s.warmup_url:
            return "disabled"

        def _call_http() -> None:
            try:
                self._http.post(self._s.warmup_url, headers=self._headers(), timeout=120.0)
            except httpx.HTTPError:
                pass

        threading.Thread(target=_call_http, daemon=True).start()
        return "warming"
