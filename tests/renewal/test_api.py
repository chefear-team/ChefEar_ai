"""FastAPI 계층 — 계약(renewal/API_CONTRACT.md)대로 응답하는지."""
import io
import wave

import pytest
from fastapi.testclient import TestClient

from chefear_api.main import create_app


@pytest.fixture
def client(world):
    """로그인한 사용자(user-1)로 부르는 클라이언트. 서비스 전체가 로그인 전용이다."""
    return TestClient(
        create_app(service=world.service, settings=world.service.s), headers={"x-dev-user": "user-1"}
    )


@pytest.fixture
def anon(world):
    """로그인하지 않은 클라이언트."""
    return TestClient(create_app(service=world.service, settings=world.service.s))


def _wav(seconds=0.2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_cors_preflight_allows_browser_calls(world):
    from conftest import make_settings

    c = TestClient(create_app(service=world.service, settings=make_settings(allowed_origins=("https://app.example",))))
    res = c.options(
        "/api/session",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 200 and res.headers["access-control-allow-origin"] == "https://app.example"
    bad = c.options(
        "/api/session",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


ME = {"x-dev-user": "user-1"}


def test_health_and_warmup(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.post("/api/warmup", headers=ME).json() == {"stt": "warming"}


def test_everything_needs_login(anon, world):
    """서비스 전체가 로그인 전용 — 비로그인은 세션도 못 만들고 GPU(음성·합성·깨우기)도 못 쓴다."""
    assert anon.get("/api/health").json() == {"ok": True}  # 서버 깨우기용으로만 열어 둔다
    assert anon.post("/api/warmup").json() == {"stt": "login_required"}

    def denied(res):
        return res.status_code == 401 and res.json()["detail"] == "login_required"

    assert denied(anon.post("/api/session"))
    assert denied(anon.get("/api/session/whatever"))
    assert denied(anon.post("/api/session/whatever/utterance", json={"text": "된장찌개 어떻게 만들어"}))
    assert denied(anon.post("/api/session/whatever/utterance", files={"audio": ("u.wav", _wav(), "audio/wav")}))
    assert denied(anon.post("/api/session/whatever/action", json={"type": "home"}))
    assert denied(anon.post("/api/tts", json={"text": "안녕하세요"}))
    assert anon.get("/api/my-recipes").status_code == 401


def test_session_text_flow(client):
    st = client.post("/api/session").json()
    sid = st["session_id"]
    assert st["screen"] == "start" and st["logged_in"] is True
    st = client.post(f"/api/session/{sid}/utterance", json={"text": "된장찌개 어떻게 만들어"}).json()
    assert st["screen"] == "recipe_confirm" and st["transcript"] is None
    st = client.post(f"/api/session/{sid}/action", json={"type": "start_cooking"}).json()
    assert st["screen"] == "cooking_step" and st["recipe"]["total"] == 3
    assert client.get(f"/api/session/{sid}").json()["screen"] == "cooking_step"


def test_audio_upload_returns_transcript(client, world):
    sid = client.post("/api/session", headers=ME).json()["session_id"]
    res = client.post(f"/api/session/{sid}/utterance", files={"audio": ("u.wav", _wav(), "audio/wav")}, headers=ME)
    assert res.status_code == 200
    body = res.json()
    assert body["transcript"] == "된장찌개 어떻게 만들어" and body["screen"] == "recipe_confirm"


def test_audio_errors(client, world):
    sid = client.post("/api/session", headers=ME).json()["session_id"]
    assert client.post(f"/api/session/{sid}/utterance", data={"x": "1"}, headers=ME).status_code == 400
    world.inference.fail = True
    res = client.post(f"/api/session/{sid}/utterance", files={"audio": ("u.wav", _wav(), "audio/wav")}, headers=ME)
    assert res.status_code == 503 and res.json()["detail"] == "stt_unavailable"
    big = b"0" * (world.service.s.max_audio_bytes + 1)
    res = client.post(f"/api/session/{sid}/utterance", files={"audio": ("u.wav", big, "audio/wav")}, headers=ME)
    assert res.status_code == 413


def test_unknown_session_is_404(client):
    assert client.get("/api/session/nope").status_code == 404
    assert client.post("/api/session/nope/utterance", json={"text": "안녕"}).status_code == 404


def test_tts_endpoint(client):
    res = client.post("/api/tts", json={"text": "안녕하세요"}, headers=ME)
    assert res.status_code == 200 and res.headers["content-type"] == "audio/mpeg"
    assert client.post("/api/tts", json={"text": ""}, headers=ME).status_code == 400


def test_my_recipes_need_login_and_isolate(client, world):
    me = {"x-dev-user": "user-1"}
    sid = client.post("/api/session", headers=me).json()["session_id"]
    post = lambda body: client.post(f"/api/session/{sid}/action", json=body, headers=me)  # noqa: E731
    client.post(f"/api/session/{sid}/utterance", json={"text": "레시피 등록"}, headers=me)
    post({"type": "register_dish_name", "value": "김밥"})
    post({"type": "register_add_ingredients", "items": ["밥"]})
    post({"type": "register_ingredients_done"})
    post({"type": "register_add_step", "text": "말아요."})
    assert post({"type": "register_save"}).json()["screen"] == "complete"

    items = client.get("/api/my-recipes", headers=me).json()
    assert len(items) == 1 and items[0]["audio_ready"] is False
    rid = items[0]["recipe_id"]
    assert client.get(f"/api/my-recipes/{rid}", headers=me).json()["instructions"] == ["말아요."]
    assert client.get(f"/api/my-recipes/{rid}", headers={"x-dev-user": "user-2"}).status_code == 404
    assert client.get(f"/api/my-recipes/{world.other['id']}", headers=me).status_code == 404
    assert client.delete(f"/api/my-recipes/{rid}", headers=me).json() == {"deleted": True}


def test_rate_limit_on_utterance(world):
    from conftest import make_settings

    limited = make_settings(stt_rate_per_min=2)
    c = TestClient(create_app(service=world.service, settings=limited), headers={"x-dev-user": "user-1"})
    sid = c.post("/api/session").json()["session_id"]
    codes = [c.post(f"/api/session/{sid}/utterance", json={"text": "다시"}).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]
