"""registration.py 테스트 — 문서 7.5 AC-06, EC-14~17."""
from fake_supabase import FakeSupabaseClient

from orchestration.registration import register_recipe, save_recipe
from orchestration.term_dict import resolve_for_tts


def test_ac06_full_flow_confirms_and_saves_as_user_custom():
    client = FakeSupabaseClient()
    session: dict = {}

    register_recipe(session, "dish_name", "문어초무침", client=client)
    register_recipe(session, "ingredients", ["문어", "오이", "초고추장"], client=client)
    register_recipe(session, "instructions", ["문어를 데친다", "재료를 무친다"], client=client)
    result = register_recipe(session, "confirm", client=client)

    assert result["saved"] is True
    assert session["registration"] is None

    saved = client.table("recipes").rows[result["recipe_id"]]
    assert saved["dish_name"] == "문어초무침"
    assert saved["source"] == "user_custom"
    # 2026-08-27 — 계정/쿠키 시스템 삭제로 등록자를 추적하지 않는다(owner_id 안 채움).
    # 대신 관리자 승인 전까진 조회에서 제외되도록 approved='N'으로 저장된다
    # (admin_recipe_approval.md).
    assert saved["approved"] == "N"
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


def test_save_recipe_auto_tags_variant_phrases_for_tts():
    """2026-09-01 — 500개 큐레이션 데이터는 term_dict.TERM_PATTERNS에 미리 맞춰
    [TERM:...] 태그가 붙은 채로 들어오지만, 사용자가 직접 등록하는 조리순서는
    "무를 나박하게 썰어주세요"처럼 자유 형식이라 태그가 없다. save_recipe()가
    저장 직전 auto_tag_terms()를 거쳐서 이런 변형 표현도 자동으로 태깅해야
    resolve_for_tts()가 나중에 설명을 붙여줄 수 있다 — 이 경로 전체(등록 ->
    저장 -> DB에 실제로 들어간 step_text -> TTS 변환)를 끝까지 확인한다."""
    client = FakeSupabaseClient()
    result = save_recipe(
        "무나물",
        ["무", "대파"],
        ["무를 나박하게 썰어주세요", "양파는 어슷하게 썰어주세요", "그릇에 담아주세요"],
        client=client,
    )

    steps = {
        r["step_number"]: r
        for r in client.table("recipe_steps").rows.values()
        if r["recipe_id"] == result["recipe_id"]
    }
    assert steps[1]["step_text"] == "무를 나박하게 썰어주세요\n[TERM:나박썰기]"
    assert steps[2]["step_text"] == "양파는 어슷하게 썰어주세요\n[TERM:어슷썰기]"
    # 매칭되는 용어가 없는 문장은 태그 없이 그대로 저장돼야 한다.
    assert steps[3]["step_text"] == "그릇에 담아주세요"
    # source는 여전히 user_custom 그대로다 — rule_generated는 500개 큐레이션
    # 데이터 전용이라 사용자 등록 경로에서는 절대 쓰이면 안 된다.
    assert steps[1]["source"] == "user_custom"

    assert resolve_for_tts(steps[1]["step_text"]) == (
        "무를 나박하게 썰어주세요 나박썰기란 얇고 네모지게 써는 방법이에요."
    )
    assert resolve_for_tts(steps[2]["step_text"]) == (
        "양파는 어슷하게 썰어주세요 어슷썰기란 칼을 비스듬히 기울여 사선으로 써는 방법이에요."
    )
