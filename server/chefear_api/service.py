"""대화 상태 기계. 기존 Streamlit 앱(ui/dispatch.py, ui/screens/*)의 분기를 그대로 옮기되,
상태는 세션 저장소에 두고 화면은 `screen` 값으로만 알려 준다(서버는 상태를 들고 있지 않다).

의도 분류·레시피 검색·등록·계정 로직(orchestration/*)은 그대로 쓴다.
요리명 추출용 로컬 LLM(EXAONE)은 쓰지 않는다 — 검색(완전·부분·자모 편집거리 일치)과 임베딩 의도 분류가
이미 같은 일을 하고, 등록 의도는 handle_utterance()가 ValueError로 알려 준다(아래 처리). A/B는 별도로 잰다.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date

from chefear_api import guard
from chefear_api import speech as sp
from chefear_api.audio import AudioIndex
from chefear_api.config import Settings
from chefear_api.inference_client import InferenceClient
from chefear_api.sessions import SessionStore, default_pipeline, new_session_data
from orchestration.pipeline import get_precomputed_steps, handle_utterance, manual_fallback
from orchestration.registration import delete_recipe, register_recipe, update_recipe
from orchestration.term_dict import resolve_for_display

_HOME_WORDS = {
    "처음", "처음으로", "처음화면", "처음 화면", "처음 화면으로",
    "메인", "메인 화면", "홈",
    "초기", "초기화면", "초기 화면", "초기화",
}
_REGISTER_WORD = "등록"
_YES_WORDS = ("네", "응", "맞아", "맞아요", "그래", "그래요", "좋아", "좋아요")
_CANCEL_WORDS = ("취소", "취소할래", "취소할래요", "취소해줘")
_NO_WORDS = ("아니", "싫", "말고", "별로", "취소", "안 좋", "안좋", "안 할", "안할", "안 해", "안해", "안 돼", "안돼")
_GO_WORDS = ("응", "네", "좋", "다음", "그래", "시작", "진행", "할래")
_MAX_DISH_NAME = 25
_MAX_BLOCKED_PER_SESSION = 10  # 한 세션에서 공격 문구가 이만큼 넘으면 더는 받지 않는다
_CHAT_KEEP = 20
_CHAT_TAIL = re.compile(r"[\s?!.。]+$")
_STEP_PREFIX = re.compile(r"^\d+\.\s*")

TEXT_ONLY_SCREENS_BACKGROUND = ("register_ingredients", "register_steps", "my_recipes", "edit_recipe")
LISTEN_SCREENS = ("start", "cooking_step", "cooking_complete", "unclassified", "complete")


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class BadRequest(Exception):
    pass


def is_home_word(text: str) -> bool:
    norm = text.strip().rstrip("?!. ")
    return any(word in norm for word in _HOME_WORDS)


def _ingredient_list(raw: str) -> list[str]:
    """"[재료] 두부| 감자" 같은 원문 -> 표시용 재료 목록."""
    text = re.sub(r"\[[^\]]*\]", "", raw or "")
    return [seg.strip() for seg in text.split("|") if seg.strip()]


def _display_step(raw_step_text: str) -> str:
    return _STEP_PREFIX.sub("", resolve_for_display(raw_step_text), count=1).strip()


class ChefEarService:
    def __init__(
        self,
        settings: Settings,
        store: SessionStore,
        audio: AudioIndex,
        inference: InferenceClient,
        client_factory,
    ) -> None:
        self.s = settings
        self.store = store
        self.audio = audio
        self.inference = inference
        self._client_factory = client_factory
        self._reg_counts: dict[tuple[str, str], int] = {}
        self._reg_lock = threading.Lock()

    # ── 공통 ────────────────────────────────────────────────────────────
    @property
    def client(self):
        return self._client_factory()

    def _load(self, session_id: str, owner_id: str | None) -> dict:
        data = self.store.get(session_id)
        if data is None:
            raise NotFound("session_not_found")
        if data.get("owner_id") != owner_id:
            # 로그인·로그아웃이 바뀌면 진행 중이던 것(특히 등록)을 이어가지 않는다.
            self._reset(data)
            data["owner_id"] = owner_id
        data["speech"] = None
        data["notice"] = None
        return data

    def _save(self, data: dict) -> dict:
        self.store.put(data)
        return self._state(data)

    def _reset(self, s: dict) -> None:
        s["pipeline"] = default_pipeline()
        s["pending_dish_name"] = None
        s["chat"] = []
        s["recipe"] = None
        s["saved"] = None
        s["screen"] = "start"

    def _say(self, s: dict, text: str) -> None:
        """읽어 줄 문장을 정하고, 대화 카드에도 "ChefEar:" 줄로 남긴다(끝의 문장부호는 뗀다)."""
        s["speech"] = {"text": text}
        self._chat(s, "ai", _CHAT_TAIL.sub("", text))

    def _chat(self, s: dict, role: str, text: str) -> None:
        s["chat"].append({"role": role, "text": text})
        del s["chat"][:-_CHAT_KEEP]

    def _load_recipe(self, recipe_id: str) -> dict:
        rows = self.client.table("recipes").select("*").eq("id", recipe_id).execute().data or []
        if not rows:
            raise NotFound("recipe_not_found")
        row = rows[0]
        steps = get_precomputed_steps(recipe_id, client=self.client)
        return {
            "recipe_id": recipe_id,
            "dish_name": row["dish_name"],
            "ingredients_raw": row.get("ingredients") or "",
            "steps": steps.get("steps", []) if steps.get("available") else [],
        }

    def _steps_cache(self, s: dict) -> list[dict] | None:
        view = s.get("recipe")
        rid = s["pipeline"].get("current_recipe_id")
        if view and view.get("recipe_id") == rid and view.get("steps"):
            return view["steps"]
        return None

    # ── 상태 응답 ───────────────────────────────────────────────────────
    def _state(self, s: dict) -> dict:
        owner = s.get("owner_id")
        pipe = s["pipeline"]
        speech = None
        if s.get("speech"):
            text = s["speech"]["text"]
            speech = {"text": text, "audio_url": self.audio.url_for(text, owner)}

        recipe = None
        view = s.get("recipe")
        if view and s["screen"] in ("recipe_confirm", "cooking_step", "cooking_complete", "complete"):
            steps = view.get("steps", [])
            total = len(steps)
            recipe = {
                "recipe_id": view["recipe_id"],
                "dish_name": view["dish_name"],
                "ingredients": _ingredient_list(view.get("ingredients_raw", "")),
                "steps": [{"step_number": st["step_number"], "text": _display_step(st["text"])} for st in steps],
                "step_number": min(pipe.get("step_number", 1), total) if total else 1,
                "total": total,
            }

        registration = None
        reg = pipe.get("registration")
        if reg and s["screen"] in ("register_dish_name", "register_ingredients", "register_steps"):
            registration = {
                "dish_name": reg["dish_name"],
                "ingredients": list(reg["ingredients"]),
                "instructions": list(reg["instructions"]),
                "guess": s.get("pending_dish_name"),
            }
        elif s["screen"] == "register_dish_name":
            registration = {"dish_name": "", "ingredients": [], "instructions": [], "guess": s.get("pending_dish_name")}

        return {
            "session_id": s["session_id"],
            "screen": s["screen"],
            "logged_in": bool(owner),
            "transcript": None,
            "speech": speech,
            "notice": s.get("notice"),
            "chat": list(s.get("chat", [])),
            "recipe": recipe,
            "registration": registration,
        }

    # ── 세션 ────────────────────────────────────────────────────────────
    def new_session(self, owner_id: str | None) -> dict:
        s = new_session_data(owner_id)
        return self._save(s)

    def get_state(self, session_id: str, owner_id: str | None) -> dict:
        data = self.store.get(session_id)
        if data is None:
            raise NotFound("session_not_found")
        if data.get("owner_id") != owner_id:
            self._reset(data)
            data["owner_id"] = owner_id
            self.store.put(data)
        # 새로고침·재접속에서는 마지막 안내를 다시 읽거나 띄우지 않는다(음성·안내는 발화·동작의 응답에만 실린다).
        data["speech"] = None
        data["notice"] = None
        return self._state(data)

    # ── 발화 ────────────────────────────────────────────────────────────
    def utterance(self, session_id: str, text: str, owner_id: str | None) -> dict:
        s = self._load(session_id, owner_id)
        # 채팅·음성 인식 결과가 들어오는 유일한 문. 정리하고, 길이를 제한하고, 명백한 공격 문구는 처리하지 않고 버린다.
        try:
            text = guard.clean(text or "", max_len=guard.MAX_UTTERANCE, field="text")
        except guard.InputRejected as exc:
            if exc.code != "text_too_long":
                raise BadRequest(exc.code) from exc
            s["notice"] = sp.FALLBACK_TOO_LONG
            return self._save(s)
        if not text:
            s["notice"] = sp.FALLBACK_EMPTY
            return self._save(s)
        kind = guard.suspicious(text)
        if kind:
            guard.log_blocked(kind, "utterance", text)
            s["blocked_count"] = int(s.get("blocked_count", 0)) + 1
            if s["blocked_count"] > _MAX_BLOCKED_PER_SESSION:
                raise BadRequest("too_many_invalid")
            s["notice"] = sp.FALLBACK_UNCLASSIFIED  # 대화 기록에도 남기지 않고, DB 조회·분류도 하지 않는다
            return self._save(s)
        screen = s["screen"]
        if screen == "recipe_confirm":
            self._on_recipe_confirm(s, text)
        elif screen == "register_dish_name":
            self._on_register_dish_text(s, text, owner_id)
        elif screen in TEXT_ONLY_SCREENS_BACKGROUND:
            self._on_background_only(s, text)
        elif screen == "login_required":
            if is_home_word(text):
                self._reset(s)
        else:
            self._process(s, text, owner_id)
        return self._save(s)

    def _goto_register(self, s: dict, owner_id: str | None, guess: str | None) -> None:
        if not owner_id:
            s["screen"] = "login_required"
            self._say(s, sp.LOGIN_REQUIRED_MESSAGE)
            return
        s["pending_dish_name"] = guess
        s["screen"] = "register_dish_name"
        self._say(s, sp.REGISTER_CONFIRM_GUESS_MESSAGE if guess else sp.REGISTER_ASK_DISH_MESSAGE)

    def _process(self, s: dict, text: str, owner_id: str | None) -> None:
        """start/cooking_step/cooking_complete/unclassified/complete 화면에서 들어온 발화(ui/dispatch.py::process_utterance)."""
        pipe = s["pipeline"]
        if is_home_word(text):
            self._reset(s)
            return
        if _REGISTER_WORD in text and not pipe.get("current_recipe_id"):
            self._chat(s, "user", "등록")
            self._goto_register(s, owner_id, None)
            return

        try:
            result = handle_utterance(pipe, text, steps=self._steps_cache(s), owner_id=owner_id, client=self.client)
        except ValueError:
            # 등록 의도로 분류됐지만 등록 단계 정보가 없는 자유 발화 → 신규 등록으로 안내(기존 value_error 분기)
            if pipe.get("current_recipe_id"):
                return  # 조리 중에는 등록 의도를 무시(기존과 동일)
            self._goto_register(s, owner_id, None)
            return
        except Exception as exc:  # noqa: BLE001 — DB·네트워크 오류도 서비스가 죽지 않게
            print(f"[service] handle_utterance 실패: {exc!r}", flush=True)
            s["screen"] = "unclassified"
            self._say(s, sp.TEMPORARY_ERROR_MESSAGE)
            return

        intent = result.get("intent")
        if intent in ("미분류", "감탄사"):
            s["notice"] = result.get("message") or sp.FALLBACK_UNCLASSIFIED
            return

        if intent == "조회":
            if "message" in result:
                self._say(s, result["message"])
                return
            self._chat(s, "user", result["dish_name"])
            s["recipe"] = self._load_recipe(result["recipe_id"])
            self._say(s, sp.confirm_text(result["dish_name"]))
            s["screen"] = "recipe_confirm"
            return

        if intent in ("진행", "재청취", "이전"):
            label = {"진행": "다음", "재청취": "다시", "이전": "이전"}[intent]
            self._apply_nav(s, result, label)
            return

        self._chat(s, "user", text)
        s["screen"] = "unclassified"
        self._say(s, sp.UNHANDLED_MESSAGE)

    def _apply_nav(self, s: dict, result: dict, label: str) -> None:
        """다음/다시/이전 결과를 화면에 반영(발화·수동 버튼 공통, ui/dispatch.py + fallback_buttons)."""
        self._chat(s, "user", label)
        pipe = s["pipeline"]
        pipe["step_number"] = result["step_number"]
        step = result.get("step")
        if result.get("no_previous"):
            s["notice"] = sp.NO_PREVIOUS_MESSAGE
            self._say(s, sp.NO_PREVIOUS_MESSAGE)
            s["screen"] = "cooking_step"
        elif step is None:
            self._say(s, sp.COOKING_COMPLETE_MESSAGE)
            s["screen"] = "cooking_complete"
        else:
            self._say(s, sp.step_speech_text(step["text"]))
            s["screen"] = "cooking_step"

    def _on_recipe_confirm(self, s: dict, text: str) -> None:
        """ui/screens/cooking.py::handle_recipe_confirm"""
        view = s.get("recipe")
        if not view:
            self._reset(s)
            return
        norm = text.strip().rstrip("?!. ")
        if is_home_word(norm) or "처음" in norm:
            self._chat(s, "user", text)
            self._reset(s)
        elif "다시" in norm:
            self._chat(s, "user", text)
            self._say(s, sp.confirm_text(view["dish_name"]))
        elif any(w in norm for w in _NO_WORDS):
            self._chat(s, "user", text)
            self._reset(s)
        elif "등록" in norm:
            self._chat(s, "user", "등록")
            self._goto_register(s, s.get("owner_id"), None)
        elif any(w in norm for w in _GO_WORDS) or norm.lower() == "next":
            self._chat(s, "user", text)
            self._start_cooking(s)
        else:
            s["notice"] = "'응'이라고 말씀하시면 시작해요. 다른 레시피를 찾으려면 '처음'이라고 말씀해 주세요."

    def _start_cooking(self, s: dict) -> None:
        view = s.get("recipe")
        s["pipeline"]["step_number"] = 1
        if view and view["steps"]:
            self._say(s, sp.step_speech_text(view["steps"][0]["text"]))
        else:
            self._say(s, sp.FIRST_STEP_MISSING_MESSAGE)
        s["screen"] = "cooking_step"

    def _on_background_only(self, s: dict, text: str) -> None:
        """register_ingredients/register_steps/마이레시피: 텍스트 폼이 진짜 입력 수단이라 안전한 몇 단어에만 반응."""
        norm = text.strip().rstrip("?!. ")
        if is_home_word(norm):
            self._reset(s)
        elif norm in _CANCEL_WORDS:
            if s["screen"] in ("register_ingredients", "register_steps"):
                s["pipeline"]["registration"] = None
            self._reset(s)

    def _on_register_dish_text(self, s: dict, text: str, owner_id: str | None) -> None:
        """ui/screens/register.py::handle_register_dish_name"""
        if not owner_id:
            s["screen"] = "login_required"
            self._say(s, sp.LOGIN_REQUIRED_MESSAGE)
            return
        norm = text.strip().rstrip("?!. ")
        if is_home_word(norm) or norm in _CANCEL_WORDS:
            self._reset(s)
            return
        if norm in _YES_WORDS:
            if not s.get("pending_dish_name"):
                s["notice"] = "요리 이름을 말씀해 주세요."
                return
            dish_name = s["pending_dish_name"]
        elif len(norm.replace(" ", "")) > _MAX_DISH_NAME:
            s["notice"] = "요리 이름만 짧게 말씀해 주세요."
            return
        else:
            dish_name = text.strip()
        self._set_dish_name(s, dish_name)

    def _set_dish_name(self, s: dict, dish_name: str) -> None:
        if not dish_name.strip():
            raise BadRequest("empty_dish_name")
        register_recipe(s["pipeline"], "dish_name", dish_name, client=self.client)
        s["screen"] = "register_ingredients"
        self._say(s, sp.REGISTER_INGREDIENTS_MESSAGE)

    # ── 버튼·폼 동작 ────────────────────────────────────────────────────
    def action(self, session_id: str, action: dict, owner_id: str | None) -> dict:
        s = self._load(session_id, owner_id)
        if not isinstance(action, dict):
            raise BadRequest("invalid_input")
        kind = action.get("type")
        # 동작 이름은 정해진 형태(소문자·밑줄)만 받는다. 이 값으로 메서드를 찾으므로 아무 문자열이나 넘기지 못하게 한다.
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,40}", kind):
            raise BadRequest("unknown_action")
        handler = getattr(self, f"_a_{kind}", None)
        if handler is None:
            raise BadRequest("unknown_action")
        handler(s, action, owner_id)
        return self._save(s)

    def _text(self, value: object, *, max_len: int, field: str) -> str:
        """등록·수정 폼 글자. 정리 + 길이 제한 + 공격 문구 차단. 어기면 400."""
        try:
            return guard.check_text(value, max_len=max_len, field=field)
        except guard.InputRejected as exc:
            raise BadRequest(exc.code) from exc

    def _texts(self, value: object, *, max_items: int, max_len: int, field: str) -> list[str]:
        try:
            items = guard.clean_list(value, max_items=max_items, max_len=max_len, field=field)
            for item in items:
                kind = guard.suspicious(item)
                if kind:
                    guard.log_blocked(kind, field, item)
                    raise guard.InputRejected("invalid_text")
            return items
        except guard.InputRejected as exc:
            raise BadRequest(exc.code) from exc

    @staticmethod
    def _int(action: dict, key: str, default: int = -1) -> int:
        try:
            return int(action.get(key, default))
        except (TypeError, ValueError, OverflowError) as exc:
            raise BadRequest("invalid_input") from exc

    def _a_home(self, s, a, owner):
        self._reset(s)

    def _a_cancel(self, s, a, owner):
        if s["screen"] in ("register_dish_name", "register_ingredients", "register_steps"):
            s["pipeline"]["registration"] = None
        self._reset(s)

    def _a_nav(self, s, a, owner):
        name = a.get("name")
        if name not in ("이전", "다시", "다음"):
            raise BadRequest("bad_nav")
        if s["screen"] not in ("cooking_step", "unclassified") or not s["pipeline"].get("current_recipe_id"):
            raise BadRequest("not_cooking")
        result = manual_fallback(s["pipeline"], name, client=self.client, steps=self._steps_cache(s))
        self._apply_nav(s, result, name)

    def _a_goto_step(self, s, a, owner):
        view = s.get("recipe")
        n = self._int(a, "step_number", 0)
        if not view or not view["steps"] or not (1 <= n <= len(view["steps"])):
            raise BadRequest("bad_step")
        s["pipeline"]["step_number"] = n
        self._say(s, sp.step_speech_text(view["steps"][n - 1]["text"]))
        s["screen"] = "cooking_step"

    def _a_start_cooking(self, s, a, owner):
        if s["screen"] != "recipe_confirm":
            raise BadRequest("not_confirming")
        self._start_cooking(s)

    def _a_other_recipe(self, s, a, owner):
        self._reset(s)

    def _a_register_start(self, s, a, owner):
        self._goto_register(s, owner, None)

    def _a_register_dish_name(self, s, a, owner):
        if not owner:
            self._goto_register(s, owner, None)
            return
        value = self._text(a.get("value", ""), max_len=guard.MAX_DISH_NAME, field="dish_name")
        if len(value.replace(" ", "")) > _MAX_DISH_NAME:
            raise BadRequest("dish_name_too_long")
        self._set_dish_name(s, value)

    def _reg(self, s: dict) -> dict:
        reg = s["pipeline"].get("registration")
        if reg is None:
            self._reset(s)
            raise BadRequest("no_registration")
        return reg

    def _a_register_add_ingredients(self, s, a, owner):
        reg = self._reg(s)
        items = self._texts(a.get("items", []), max_items=guard.MAX_INGREDIENTS, max_len=guard.MAX_INGREDIENT, field="ingredient")
        if not items:
            raise BadRequest("empty_items")
        if len(reg["ingredients"]) + len(items) > guard.MAX_INGREDIENTS:
            raise BadRequest("ingredient_too_many")
        register_recipe(s["pipeline"], "ingredients", items, client=self.client)

    def _a_register_ingredients_done(self, s, a, owner):
        reg = self._reg(s)
        if not reg["ingredients"]:
            raise BadRequest("no_ingredients")
        s["screen"] = "register_steps"
        self._say(s, sp.REGISTER_STEPS_MESSAGE)

    def _a_register_add_step(self, s, a, owner):
        reg = self._reg(s)
        text = self._text(a.get("text", ""), max_len=guard.MAX_STEP, field="step")
        if not text:
            raise BadRequest("empty_step")
        if len(reg["instructions"]) >= guard.MAX_STEPS:
            raise BadRequest("step_too_many")
        register_recipe(s["pipeline"], "instructions", [text], client=self.client)

    def _a_register_edit_step(self, s, a, owner):
        reg = self._reg(s)
        i, text = self._int(a, "index"), self._text(a.get("text", ""), max_len=guard.MAX_STEP, field="step")
        if not (0 <= i < len(reg["instructions"])) or not text:
            raise BadRequest("bad_step")
        reg["instructions"][i] = text

    def _a_register_delete_step(self, s, a, owner):
        reg = self._reg(s)
        i = self._int(a, "index")
        if not (0 <= i < len(reg["instructions"])):
            raise BadRequest("bad_step")
        reg["instructions"].pop(i)

    def _a_register_save(self, s, a, owner):
        if not owner:
            s["screen"] = "login_required"
            self._say(s, sp.LOGIN_REQUIRED_MESSAGE)
            return
        reg = self._reg(s)
        if not reg["instructions"]:
            raise BadRequest("no_steps")
        if not self._take_register_quota(owner):
            s["notice"] = sp.REGISTER_LIMIT_MESSAGE
            self._say(s, sp.REGISTER_LIMIT_MESSAGE)
            return
        dish_name = reg["dish_name"]
        result = register_recipe(s["pipeline"], "confirm", None, client=self.client, owner_id=owner)
        self.inference.queue_recipe_audio(result["recipe_id"], owner)
        s["recipe"] = {"recipe_id": result["recipe_id"], "dish_name": dish_name, "ingredients_raw": "", "steps": []}
        s["screen"] = "complete"
        self._say(s, sp.REGISTER_SAVED_MESSAGE)

    def _take_register_quota(self, owner_id: str) -> bool:
        key = (owner_id, date.today().isoformat())
        with self._reg_lock:
            if len(self._reg_counts) > 2000:
                self._reg_counts.clear()
            if self._reg_counts.get(key, 0) >= self.s.register_daily_limit:
                return False
            self._reg_counts[key] = self._reg_counts.get(key, 0) + 1
            return True

    # ── 마이레시피 ──────────────────────────────────────────────────────
    def _own_recipe(self, recipe_id: str, owner_id: str | None) -> dict:
        if not owner_id:
            raise Forbidden("login_required")
        rows = self.client.table("recipes").select("*").eq("id", recipe_id).execute().data or []
        if not rows or rows[0].get("owner_id") != owner_id:
            raise NotFound("recipe_not_found")  # 남의 것은 "없음"과 같게 보인다(IDOR 방지)
        return rows[0]

    def list_my_recipes(self, owner_id: str | None) -> list[dict]:
        if not owner_id:
            raise Forbidden("login_required")
        rows = (
            self.client.table("recipes").select("id,dish_name,created_at")
            .eq("source", "user_custom").eq("owner_id", owner_id).execute().data or []
        )
        ready = self.audio.audio_ready_recipe_ids(owner_id)
        rows = sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)
        return [
            {"recipe_id": r["id"], "dish_name": r["dish_name"], "created_at": r.get("created_at", ""),
             "audio_ready": r["id"] in ready}
            for r in rows
        ]

    def get_my_recipe(self, recipe_id: str, owner_id: str | None) -> dict:
        row = self._own_recipe(recipe_id, owner_id)
        steps = get_precomputed_steps(recipe_id, client=self.client)
        lines = [_display_step(st["text"]) for st in steps.get("steps", [])] if steps.get("available") else []
        return {
            "recipe_id": recipe_id,
            "dish_name": row["dish_name"],
            "ingredients": [x.strip() for x in (row.get("ingredients") or "").split("|") if x.strip()],
            "instructions": [x for x in lines if x],
        }

    def update_my_recipe(self, recipe_id: str, body: dict, owner_id: str | None) -> dict:
        self._own_recipe(recipe_id, owner_id)
        if not isinstance(body, dict):
            raise BadRequest("invalid_input")
        dish_name = self._text(body.get("dish_name", ""), max_len=guard.MAX_DISH_NAME, field="dish_name")
        ingredients = self._texts(body.get("ingredients"), max_items=guard.MAX_INGREDIENTS, max_len=guard.MAX_INGREDIENT, field="ingredient")
        instructions = self._texts(body.get("instructions"), max_items=guard.MAX_STEPS, max_len=guard.MAX_STEP, field="step")
        if not dish_name or not instructions:
            raise BadRequest("empty_recipe")
        update_recipe(recipe_id, dish_name, ingredients, instructions, client=self.client, owner_id=owner_id)
        self.inference.queue_recipe_audio(recipe_id, owner_id)
        return self.get_my_recipe(recipe_id, owner_id)

    def delete_my_recipe(self, recipe_id: str, owner_id: str | None) -> dict:
        self._own_recipe(recipe_id, owner_id)
        delete_recipe(recipe_id, client=self.client, owner_id=owner_id)
        self.audio.delete_recipe_assets(owner_id, recipe_id)
        return {"deleted": True}
