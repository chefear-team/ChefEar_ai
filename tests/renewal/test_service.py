"""서버 상태 기계(ChefEarService) — 기존 Streamlit 앱의 흐름이 같게 동작하는지."""
import pytest

from chefear_api import speech as sp
from chefear_api.service import BadRequest, Forbidden, NotFound


def _start(w, owner=None):
    return w.service.new_session(owner)["session_id"]


def _say(w, sid, text, owner=None):
    return w.service.utterance(sid, text, owner)


def _act(w, sid, owner=None, **action):
    return w.service.action(sid, action, owner)


def test_chat_card_keeps_both_sides(world):
    """대화 카드에는 "나"와 "ChefEar" 줄이 둘 다 남는다(ChefEar 줄은 끝의 문장부호를 뗀 읽은 문장)."""
    w = world
    sid = _start(w)
    st = _say(w, sid, "된장찌개 어떻게 만들어")
    assert st["chat"] == [
        {"role": "user", "text": "된장찌개"},
        {"role": "ai", "text": sp.confirm_text("된장찌개").rstrip("?!. ")},
    ]
    st = _say(w, sid, "응")
    roles = [m["role"] for m in st["chat"]]
    assert roles == ["user", "ai", "user", "ai"]
    assert all(not m["text"].endswith(("?", "!", ".")) for m in st["chat"] if m["role"] == "ai")


def test_lookup_confirm_and_cook_flow(world):
    w = world
    sid = _start(w)
    st = _say(w, sid, "된장찌개 어떻게 만들어")
    assert st["screen"] == "recipe_confirm"
    assert st["speech"]["text"] == sp.confirm_text("된장찌개")
    assert st["recipe"]["ingredients"] == ["두부", "감자"]
    assert st["recipe"]["total"] == 3

    st = _say(w, sid, "응")
    assert st["screen"] == "cooking_step"
    assert st["recipe"]["step_number"] == 1
    # 화면용 문장에는 번호·용어 태그가 없고, 음성용 문장에는 용어 설명이 들어간다.
    assert st["recipe"]["steps"][0]["text"] == "두부, 감자를 깍둑썰기 해주세요."
    assert "깍둑썰기란" in st["speech"]["text"]

    st = _say(w, sid, "다음")
    assert st["recipe"]["step_number"] == 2 and st["screen"] == "cooking_step"
    st = _act(w, sid, type="nav", name="이전")
    assert st["recipe"]["step_number"] == 1
    st = _act(w, sid, type="nav", name="이전")
    assert st["recipe"]["step_number"] == 1 and st["notice"] == sp.NO_PREVIOUS_MESSAGE

    _act(w, sid, type="goto_step", step_number=3)
    st = _say(w, sid, "다음")
    assert st["screen"] == "cooking_complete" and st["speech"]["text"] == sp.COOKING_COMPLETE_MESSAGE


def test_audio_url_only_when_prebuilt(world):
    w = world
    sid = _start(w)
    st = _say(w, sid, "된장찌개 어떻게 만들어")
    assert st["speech"]["audio_url"] is None  # 아직 미리 만든 음성이 없다 → 웹이 실시간 TTS로 대체
    w.audio.public_keys.add(sp.audio_key(sp.confirm_text("된장찌개")))
    st = w.service.get_state(sid, None)
    assert st["speech"] is None  # 읽을 문장은 응답마다 새로 정해진다
    st = _say(w, sid, "다시")
    assert st["speech"]["audio_url"].endswith(f"{sp.audio_key(sp.confirm_text('된장찌개'))}.mp3")


def test_home_word_and_cancel_reset(world):
    w = world
    sid = _start(w)
    _say(w, sid, "된장찌개 어떻게 만들어")
    st = _say(w, sid, "처음으로")
    assert st["screen"] == "start" and st["recipe"] is None and st["chat"] == []
    st = _say(w, sid, "된장찌개 어떻게 만들어")
    st = _act(w, sid, type="other_recipe")
    assert st["screen"] == "start"


def test_unknown_dish_keeps_screen_and_is_honest(world):
    w = world
    sid = _start(w)
    st = _say(w, sid, "마라탕 어떻게 만들어")
    assert st["screen"] == "start"
    assert st["speech"]["text"] == sp.DISH_NOT_FOUND_MESSAGE


def test_registration_requires_login(world):
    w = world
    sid = _start(w)
    st = _say(w, sid, "레시피 등록")
    assert st["screen"] == "login_required" and st["speech"]["text"] == sp.LOGIN_REQUIRED_MESSAGE
    st = _act(w, sid, type="register_start")
    assert st["screen"] == "login_required"
    with pytest.raises(Forbidden):
        w.service.list_my_recipes(None)


def test_full_registration_and_isolation(world):
    w = world
    me = "user-1"
    sid = _start(w, me)
    st = _say(w, sid, "레시피 등록", me)
    assert st["screen"] == "register_dish_name"
    st = _act(w, sid, me, type="register_dish_name", value="계란말이")
    assert st["screen"] == "register_ingredients"
    _act(w, sid, me, type="register_add_ingredients", items=["계란", "대파"])
    st = _act(w, sid, me, type="register_ingredients_done")
    assert st["screen"] == "register_steps"
    _act(w, sid, me, type="register_add_step", text="계란을 풀어요.")
    _act(w, sid, me, type="register_add_step", text="팬에 부어 말아요.")
    st = _act(w, sid, me, type="register_edit_step", index=0, text="계란과 대파를 풀어요.")
    assert st["registration"]["instructions"][0] == "계란과 대파를 풀어요."
    st = _act(w, sid, me, type="register_save")
    assert st["screen"] == "complete" and st["speech"]["text"] == sp.REGISTER_SAVED_MESSAGE

    saved = w.client.table("recipes").select("*").eq("dish_name", "계란말이").execute().data
    assert len(saved) == 1 and saved[0]["owner_id"] == me and saved[0]["source"] == "user_custom"
    assert w.inference.queued == [(saved[0]["id"], me)]

    # 본인은 조회되고, 다른 사용자·익명은 "등록되지 않은 레시피"로 보인다.
    st = _say(w, _start(w, me), "계란말이 어떻게 만들어", me)
    assert st["screen"] == "recipe_confirm"
    for other in (None, "user-2"):
        st = _say(w, _start(w, other), "계란말이 어떻게 만들어", other)
        assert st["screen"] == "start" and st["speech"]["text"] == sp.DISH_NOT_FOUND_MESSAGE

    mine = w.service.list_my_recipes(me)
    assert [r["dish_name"] for r in mine] == ["계란말이"]
    with pytest.raises(NotFound):
        w.service.get_my_recipe(w.other["id"], me)  # 남의 레시피는 없음과 같다
    with pytest.raises(NotFound):
        w.service.delete_my_recipe(w.other["id"], me)


def test_register_daily_limit(world):
    w = world
    me = "user-1"
    for i in range(3):
        sid = _start(w, me)
        _say(w, sid, "레시피 등록", me)
        _act(w, sid, me, type="register_dish_name", value=f"요리{i}")
        _act(w, sid, me, type="register_add_ingredients", items=["재료"])
        _act(w, sid, me, type="register_ingredients_done")
        _act(w, sid, me, type="register_add_step", text="만들어요.")
        st = _act(w, sid, me, type="register_save")
    assert st["screen"] == "register_steps" and st["notice"] == sp.REGISTER_LIMIT_MESSAGE
    assert len(w.client.table("recipes").select("*").eq("owner_id", me).execute().data) == 2


def test_my_recipe_update_and_delete_queue_audio(world):
    w = world
    me = "user-1"
    sid = _start(w, me)
    _say(w, sid, "레시피 등록", me)
    _act(w, sid, me, type="register_dish_name", value="김밥")
    _act(w, sid, me, type="register_add_ingredients", items=["밥"])
    _act(w, sid, me, type="register_ingredients_done")
    _act(w, sid, me, type="register_add_step", text="밥을 말아요.")
    _act(w, sid, me, type="register_save")
    rid = w.service.list_my_recipes(me)[0]["recipe_id"]
    w.inference.queued.clear()

    updated = w.service.update_my_recipe(
        rid, {"dish_name": "참치김밥", "ingredients": ["밥", "참치"], "instructions": ["밥에 참치를 올려요.", "말아요."]}, me
    )
    assert updated["dish_name"] == "참치김밥" and updated["instructions"] == ["밥에 참치를 올려요.", "말아요."]
    assert w.inference.queued == [(rid, me)]
    with pytest.raises(BadRequest):
        w.service.update_my_recipe(rid, {"dish_name": "", "instructions": []}, me)

    assert w.service.delete_my_recipe(rid, me) == {"deleted": True}
    assert w.audio.deleted == [(me, rid)]
    assert w.service.list_my_recipes(me) == []


def test_owner_change_resets_registration(world):
    w = world
    sid = _start(w, "user-1")
    _say(w, sid, "레시피 등록", "user-1")
    st = w.service.get_state(sid, None)  # 로그아웃
    assert st["screen"] == "start" and st["registration"] is None


def test_unknown_session_and_action(world):
    w = world
    with pytest.raises(NotFound):
        w.service.get_state("nope", None)
    sid = _start(w)
    with pytest.raises(BadRequest):
        w.service.action(sid, {"type": "hack"}, None)
    with pytest.raises(BadRequest):
        w.service.action(sid, {"type": "nav", "name": "다음"}, None)  # 조리 중이 아님
