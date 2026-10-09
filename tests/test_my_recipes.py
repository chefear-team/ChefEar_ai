"""ui/screens/my_recipes.py 테스트 — docs/specs/my_recipes.md AC-01/05/06,
docs/specs/edit_recipe_term_tag.md AC-01/02/05/06."""
from fake_supabase import FakeSupabaseClient

from orchestration.registration import save_recipe, update_recipe
from ui.screens.my_recipes import (
    _approval_label,
    _authorized_recipe,
    _my_recipes,
    _parse_instructions,
    _prefill_instructions,
    _strip_step_prefix,
)

_POTATO_STEPS = [
    "감자와 양파를 한입 크기로 썰어주세요.",
    "냄비에 감자를 넣고 간장, 설탕, 물 한 컵을 부어주세요.",
    "중불에서 15분간 조려주세요.",
    "물엿과 참기름을 넣고 윤기가 나게 섞어주세요.",
]


def _steps(client, recipe_id):
    return sorted(
        (r for r in client.table("recipe_steps").rows.values() if r["recipe_id"] == recipe_id),
        key=lambda r: r["step_number"],
    )


def _save_from_edit_form_unchanged(client, recipe_id, owner_id):
    """수정 화면을 열고 아무것도 안 바꾼 채 저장하는 것과 같은 경로."""
    form_text = _prefill_instructions(_steps(client, recipe_id))
    update_recipe(recipe_id, "감자조림", ["감자 2개"], _parse_instructions(form_text), client=client, owner_id=owner_id)


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


def test_strip_step_prefix_removes_saved_number_and_leaves_legacy_text_untouched():
    """save_recipe/update_recipe가 붙이는 "N. " 순번을 수정 폼
    프리필 시 떼어내야 재저장할 때 "1. 1. ..."로 겹쳐 쌓이지 않는다(이 변경 이전에
    저장된, 접두어 없는 레거시 행은 그대로 통과해야 함).
    """
    assert _strip_step_prefix("1. 첫 단계") == "첫 단계"
    assert _strip_step_prefix("12. 열두 번째 단계") == "열두 번째 단계"
    assert _strip_step_prefix("접두어 없는 레거시 단계") == "접두어 없는 레거시 단계"


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


def test_term_tag_ac01_unchanged_edit_keeps_steps_identical():
    """edit_recipe_term_tag.md AC-01 — 수정 화면에서 그대로 저장해도 단계 수와 문장이 같다."""
    client = FakeSupabaseClient()
    saved = save_recipe("감자조림", ["감자 2개"], _POTATO_STEPS, client=client, owner_id="A")
    recipe_id = saved["recipe_id"]
    before = [s["step_text"] for s in _steps(client, recipe_id)]

    _save_from_edit_form_unchanged(client, recipe_id, "A")

    after = [s["step_text"] for s in _steps(client, recipe_id)]
    assert after == before
    assert after[2] == "3. 중불에서 15분간 조려주세요.\n[TERM:조리다]"


def test_term_tag_ac02_prefill_hides_tags():
    """edit_recipe_term_tag.md AC-02 — 수정 칸에는 태그가 보이지 않고 한 단계가 한 줄이다."""
    client = FakeSupabaseClient()
    saved = save_recipe("감자조림", ["감자 2개"], _POTATO_STEPS, client=client, owner_id="A")

    form_text = _prefill_instructions(_steps(client, saved["recipe_id"]))

    assert "[TERM:" not in form_text
    assert form_text.split("\n") == _POTATO_STEPS


def test_term_tag_ac05_already_split_rows_recover_on_next_save():
    """edit_recipe_term_tag.md AC-05 — 버그로 태그만 남은 단계는 다음 저장 때 사라지고 태그가 제자리로 돌아온다."""
    client = FakeSupabaseClient()
    saved = save_recipe("감자조림", ["감자 2개"], ["가"], client=client, owner_id="A")
    recipe_id = saved["recipe_id"]
    client.table("recipe_steps").delete().eq("recipe_id", recipe_id).execute()
    broken = ["1. 가", "2. 나", "3. 조려주세요.", "4. [TERM:조리다]", "5. 다"]
    client.table("recipe_steps").insert(
        [{"recipe_id": recipe_id, "step_number": i, "step_text": t, "source": "user_custom"} for i, t in enumerate(broken, 1)]
    ).execute()

    _save_from_edit_form_unchanged(client, recipe_id, "A")

    after = [s["step_text"] for s in _steps(client, recipe_id)]
    assert after == ["1. 가", "2. 나", "3. 조려주세요.\n[TERM:조리다]", "4. 다"]


def test_term_tag_ac06_tag_only_lines_are_not_steps():
    """edit_recipe_term_tag.md AC-06 — 사용자가 태그만 있는 줄을 넣어도 단계가 되지 않는다."""
    assert _parse_instructions("가\n[TERM:조리다]\n나") == ["가", "나"]
