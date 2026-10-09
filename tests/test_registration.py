"""registration.py 테스트 — 문서 7.5 AC-06, EC-14~17."""
from fake_supabase import FakeSupabaseClient

from orchestration.registration import register_recipe, save_recipe, update_recipe
from orchestration.term_dict import resolve_for_tts


def test_ac06_full_flow_confirms_and_saves_as_user_custom():
    client = FakeSupabaseClient()
    session: dict = {}

    register_recipe(session, "dish_name", "문어초무침", client=client)
    register_recipe(session, "ingredients", ["문어", "오이", "초고추장"], client=client)
    register_recipe(session, "instructions", ["문어를 데친다", "재료를 무친다"], client=client)
    result = register_recipe(session, "confirm", client=client, owner_id="sha256-user-id")

    assert result["saved"] is True
    assert session["registration"] is None

    saved = client.table("recipes").rows[result["recipe_id"]]
    assert saved["dish_name"] == "문어초무침"
    assert saved["source"] == "user_custom"
    assert saved["approved"] == "Y"
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
    first = save_recipe("된장찌개", ["두부"], ["끓인다"], client=client, owner_id="A")
    second = save_recipe("된장찌개", ["감자"], ["끓인다"], client=client, owner_id="A")

    assert first["recipe_id"] != second["recipe_id"]
    assert len(client.table("recipes").rows) == 2


def test_ac04_owner_id_reflected_when_logged_in_and_null_when_not():
    """docs/specs/user_accounts_google_login.md AC-04 + private_recipe_visibility:
    로그인 저장은 owner_id 기록, 비로그인 user_custom 신규 저장은 거부."""
    import pytest

    client = FakeSupabaseClient()

    logged_in = save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id="sha256-user-id")

    with pytest.raises(ValueError):
        save_recipe("김치찌개", ["김치"], ["끓인다"], client=client, owner_id=None)

    assert client.table("recipes").rows[logged_in["recipe_id"]]["owner_id"] == "sha256-user-id"


def test_register_confirm_without_login_rejected():
    """private_recipe_visibility: confirm 단계에서도 비로그인이면 저장 전에 거부."""
    import pytest

    client = FakeSupabaseClient()
    session: dict = {}
    register_recipe(session, "dish_name", "김치찌개", client=client)
    register_recipe(session, "ingredients", ["김치"], client=client)
    register_recipe(session, "instructions", ["끓인다"], client=client)
    with pytest.raises(ValueError):
        register_recipe(session, "confirm", client=client, owner_id=None)


def test_ac02_update_recipe_replaces_steps_and_keeps_recipe_id():
    """docs/specs/my_recipes.md AC-02 — 조리순서가 3단계에서 2단계로 줄어도 UPDATE되고
    (새 recipe_id로 insert되지 않음), recipe_steps는 옛 3단계가 전부 사라지고 새
    2단계만 남는다."""
    client = FakeSupabaseClient()
    saved = save_recipe("김치찌개", ["김치", "돼지고기"], ["1단계", "2단계", "3단계"], client=client, owner_id="A")
    recipe_id = saved["recipe_id"]

    result = update_recipe(
        recipe_id, "김치찌개 ", ["김치"], ["새 1단계", "새 2단계"], client=client
    )

    assert result == {"recipe_id": recipe_id, "updated": True}
    assert len(client.table("recipes").rows) == 1  # 새로 insert 안 됨, 같은 행 그대로
    row = client.table("recipes").rows[recipe_id]
    assert row["dish_name"] == "김치찌개"  # _normalize_dish_name()으로 trailing 공백 제거
    assert row["ingredients"] == "김치"

    steps = sorted(
        (r for r in client.table("recipe_steps").rows.values() if r["recipe_id"] == recipe_id),
        key=lambda r: r["step_number"],
    )
    assert [s["step_text"] for s in steps] == ["1. 새 1단계", "2. 새 2단계"]


def test_update_recipe_preserves_owner_id_and_approved():
    """update_recipe()는 recipes 행을 UPDATE만 하지 owner_id/approved는 안 건드린다."""
    client = FakeSupabaseClient()
    saved = save_recipe("된장찌개", ["두부"], ["끓인다"], client=client, owner_id="sha256-user-id")
    recipe_id = saved["recipe_id"]

    update_recipe(recipe_id, "된장찌개", ["두부", "감자"], ["끓인다"], client=client)

    row = client.table("recipes").rows[recipe_id]
    assert row["owner_id"] == "sha256-user-id"
    assert row["approved"] == "Y"  # save_recipe()가 넣은 값 그대로, update_recipe()가 안 바꿈


def test_register_recipe_confirm_passes_owner_id_through_to_save_recipe():
    client = FakeSupabaseClient()
    session: dict = {}
    register_recipe(session, "dish_name", "김치찌개", client=client)
    register_recipe(session, "ingredients", ["김치"], client=client)
    register_recipe(session, "instructions", ["끓인다"], client=client)

    result = register_recipe(session, "confirm", client=client, owner_id="sha256-user-id")

    assert client.table("recipes").rows[result["recipe_id"]]["owner_id"] == "sha256-user-id"


def test_save_recipe_auto_tags_variant_phrases_for_tts():
    """500개 큐레이션 데이터는 term_dict.TERM_PATTERNS에 미리 맞춰
    [TERM:...] 태그가 붙은 채로 들어오지만, 사용자가 직접 등록하는 조리순서는
    "무를 나박하게 썰어주세요"처럼 자유 형식이라 태그가 없다. save_recipe가
    저장 직전 auto_tag_terms를 거쳐서 이런 변형 표현도 자동으로 태깅해야
    resolve_for_tts가 나중에 설명을 붙여줄 수 있다 — 이 경로 전체(등록 ->
    저장 -> DB에 실제로 들어간 step_text -> TTS 변환)를 끝까지 확인한다.
    """
    client = FakeSupabaseClient()
    result = save_recipe(
        "무나물",
        ["무", "대파"],
        ["무를 나박하게 썰어주세요", "양파는 어슷하게 썰어주세요", "그릇에 담아주세요"],
        client=client,
        owner_id="A",
    )

    steps = {
        r["step_number"]: r
        for r in client.table("recipe_steps").rows.values()
        if r["recipe_id"] == result["recipe_id"]
    }
    assert steps[1]["step_text"] == "1. 무를 나박하게 썰어주세요\n[TERM:나박썰기]"
    assert steps[2]["step_text"] == "2. 양파는 어슷하게 썰어주세요\n[TERM:어슷썰기]"
    # 매칭되는 용어가 없는 문장은 태그 없이 그대로 저장돼야 한다.
    assert steps[3]["step_text"] == "3. 그릇에 담아주세요"
    # source는 여전히 user_custom 그대로다 — rule_generated는 500개 큐레이션
    # 데이터 전용이라 사용자 등록 경로에서는 절대 쓰이면 안 된다.
    assert steps[1]["source"] == "user_custom"

    assert resolve_for_tts(steps[1]["step_text"]) == (
        "1. 무를 나박하게 썰어주세요 나박썰기란 얇고 네모지게 써는 방법이에요."
    )
    assert resolve_for_tts(steps[2]["step_text"]) == (
        "2. 양파는 어슷하게 썰어주세요 어슷썰기란 칼을 비스듬히 기울여 사선으로 써는 방법이에요."
    )


def test_update_recipe_tags_terms_added_by_edit():
    """edit_recipe_term_tag.md AC-03 — 수정으로 넣은 용어 표현에도 등록과 같은 태그가 붙는다."""
    client = FakeSupabaseClient()
    saved = save_recipe("감자조림", ["감자"], ["감자를 썰어주세요.", "물을 부어주세요."], client=client, owner_id="A")
    recipe_id = saved["recipe_id"]

    update_recipe(recipe_id, "감자조림", ["감자"], ["감자를 썰어주세요.", "양파를 어슷썰기 해주세요."], client=client, owner_id="A")

    texts = [r["step_text"] for r in sorted(client.table("recipe_steps").rows.values(), key=lambda r: r["step_number"])]
    assert "[TERM:어슷썰기]" in texts[1]


def test_update_recipe_drops_tag_when_term_removed():
    """edit_recipe_term_tag.md AC-04 — 용어 표현을 지우면 태그도 사라진다."""
    client = FakeSupabaseClient()
    saved = save_recipe("감자조림", ["감자"], ["중불에서 15분간 조려주세요."], client=client, owner_id="A")
    recipe_id = saved["recipe_id"]

    update_recipe(recipe_id, "감자조림", ["감자"], ["중불에서 15분간 끓여주세요."], client=client, owner_id="A")

    texts = [r["step_text"] for r in client.table("recipe_steps").rows.values()]
    assert texts == ["1. 중불에서 15분간 끓여주세요."]
