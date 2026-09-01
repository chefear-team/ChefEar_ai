"""ui/screens/my_recipes.py 테스트 — docs/specs/my_recipes.md AC-01/05/06."""
from fake_supabase import FakeSupabaseClient

from orchestration.registration import save_recipe
from ui.screens.my_recipes import _approval_label, _authorized_recipe, _my_recipes


def test_ac01_only_own_user_custom_recipes_returned():
    client = FakeSupabaseClient()
    # A 소유 user_custom 2건
    a1 = save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id="A")
    a2 = save_recipe("된장찌개", ["된장"], ["끓인다"], client=client, owner_id="A")
    # B 소유 user_custom 1건 — A 목록엔 안 보여야 함
    save_recipe("계란찜", ["계란"], ["찐다"], client=client, owner_id="B")
    # api_standard(표준 데이터, owner_id 없음) — source가 달라서 안 보여야 함
    client.table("recipes").insert(
        {"dish_name": "표준레시피", "ingredients": "", "source": "api_standard", "owner_id": None}
    ).execute()

    rows = _my_recipes("A", client)

    ids = {r["id"] for r in rows}
    assert ids == {a1["recipe_id"], a2["recipe_id"]}


def test_ac01_sorted_by_created_at_newest_first():
    client = FakeSupabaseClient()
    older = save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id="A")
    client.table("recipes").rows[older["recipe_id"]]["created_at"] = "2026-01-01T00:00:00"
    newer = save_recipe("된장찌개", ["된장"], ["끓인다"], client=client, owner_id="A")
    client.table("recipes").rows[newer["recipe_id"]]["created_at"] = "2026-06-01T00:00:00"

    rows = _my_recipes("A", client)

    assert [r["id"] for r in rows] == [newer["recipe_id"], older["recipe_id"]]


def test_ac06_approval_label_reflects_approved_column():
    assert _approval_label({"approved": "Y"}) == "승인됨"
    assert _approval_label({"approved": "N"}) == "심사중"
    assert _approval_label({}) == "심사중"  # 방어적 기본값


def test_ac05_authorized_recipe_returns_none_for_wrong_owner():
    client = FakeSupabaseClient()
    saved = save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id="A")

    assert _authorized_recipe(saved["recipe_id"], "B", client) is None


def test_ac05_authorized_recipe_returns_none_for_missing_recipe():
    client = FakeSupabaseClient()
    assert _authorized_recipe("00000000-0000-0000-0000-000000000000", "A", client) is None


def test_ac05_authorized_recipe_returns_row_for_correct_owner():
    client = FakeSupabaseClient()
    saved = save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id="A")

    recipe = _authorized_recipe(saved["recipe_id"], "A", client)

    assert recipe is not None
    assert recipe["dish_name"] == "김치찌개"
