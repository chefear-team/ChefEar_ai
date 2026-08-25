"""registration.py 테스트 — 문서 7.5 AC-06, EC-14~17."""
from fake_supabase import FakeSupabaseClient

from orchestration.registration import register_recipe, save_recipe


def test_ac06_full_flow_confirms_and_saves_as_user_custom():
    client = FakeSupabaseClient()
    session = {"owner_id": "user-A"}  # 작업3: 쿠키에서 이미 발급받은 UUID라고 가정

    register_recipe(session, "dish_name", "문어초무침", client=client)
    register_recipe(session, "ingredients", ["문어", "오이", "초고추장"], client=client)
    register_recipe(session, "instructions", ["문어를 데친다", "재료를 무친다"], client=client)
    result = register_recipe(session, "confirm", client=client)

    assert result["saved"] is True
    assert session["registration"] is None

    saved = client.table("recipes").rows[result["recipe_id"]]
    assert saved["dish_name"] == "문어초무침"
    assert saved["source"] == "user_custom"
    assert saved["owner_id"] == "user-A"
    steps = [r for r in client.table("recipe_steps").rows.values() if r["recipe_id"] == result["recipe_id"]]
    assert len(steps) == 2


def test_ec15_instructions_can_be_appended_across_multiple_turns():
    session = {}
    register_recipe(session, "dish_name", "된장찌개", client=FakeSupabaseClient())
    register_recipe(session, "ingredients", ["두부"], client=FakeSupabaseClient())

    register_recipe(session, "instructions", ["물을 끓인다"], client=FakeSupabaseClient())
    register_recipe(session, "instructions", ["두부를 넣는다"], client=FakeSupabaseClient())

    assert session["registration"]["instructions"] == ["물을 끓인다", "두부를 넣는다"]


def test_ec16_abort_discards_session_without_saving():
    client = FakeSupabaseClient()
    session = {}
    register_recipe(session, "dish_name", "된장찌개", client=client)

    result = register_recipe(session, "abort", client=client)

    assert result == {"aborted": True}
    assert session["registration"] is None
    assert client.table("recipes").rows == {}


def test_ec17_duplicate_dish_name_saved_as_separate_row_not_overwritten():
    client = FakeSupabaseClient()
    first = save_recipe("된장찌개", ["두부"], ["끓인다"], client=client)
    second = save_recipe("된장찌개", ["감자"], ["끓인다"], client=client)

    assert first["recipe_id"] != second["recipe_id"]
    assert len(client.table("recipes").rows) == 2
