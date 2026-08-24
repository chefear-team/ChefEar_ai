"""pipeline.py 테스트 — 문서 7.4/7.1.1 AC-07~09, AC-12/13, handle_utterance() 라우팅."""
from fake_supabase import FakeSupabaseClient

from orchestration.pipeline import (
    DISH_NOT_FOUND_MESSAGE,
    NOT_AVAILABLE_MESSAGE,
    advance_step,
    get_precomputed_steps,
    handle_utterance,
    manual_fallback,
)


def _seed_recipe_with_steps(client, n=3):
    recipe = client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부", "source": "api_standard"})
    for i in range(1, n + 1):
        client.table("recipe_steps").seed(
            {"recipe_id": recipe["id"], "step_number": i, "step_text": f"{i}단계", "source": "api_standard"}
        )
    return recipe


def test_ac12_existing_recipe_steps_available():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)

    result = get_precomputed_steps(recipe["id"], client=client)

    assert result["available"] is True
    assert [s["step_number"] for s in result["steps"]] == [1, 2, 3]


def test_ac13_missing_recipe_id_is_honest_about_it():
    client = FakeSupabaseClient()
    result = get_precomputed_steps("no-such-id", client=client)
    assert result == {"available": False, "ingredients_only": False, "message": NOT_AVAILABLE_MESSAGE}


def test_ac07_previous_step_moves_back_one():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 3}

    result = advance_step(session, "이전", client=client)

    assert result["step_number"] == 2
    assert session["step_number"] == 2
    assert result["step"]["text"] == "2단계"


def test_ac08_previous_at_step_one_stays_and_flags_no_previous():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 1}

    result = advance_step(session, "이전", client=client)

    assert result["step_number"] == 1
    assert result["no_previous"] is True


def test_next_moves_forward_and_again_stays():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 1}

    advance_step(session, "다음", client=client)
    assert session["step_number"] == 2

    advance_step(session, "다시", client=client)
    assert session["step_number"] == 2


def test_ac09_manual_button_bypasses_intent_classification():
    """FR-16/AC-09: 화면의 [다시] 버튼은 classify_intent 없이 바로 현재 단계를 다시 안내."""
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 2}

    result = manual_fallback(session, "다시", client=client)

    assert result["step_number"] == 2
    assert result["step"]["text"] == "2단계"


def test_handle_utterance_progress_advances_step():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 1}

    result = handle_utterance(session, "다음", client=client)

    assert result["intent"] == "진행"
    assert result["step_number"] == 2
    assert result["step"]["text"] == "2단계"


def test_handle_utterance_progress_without_active_recipe_is_honest_not_a_crash():
    """실측 회귀 테스트(2026-08-20): 레시피를 고른 적 없는 상태(session 비어있음)에서
    "다음"이 오면 advance_step()이 session["current_recipe_id"]를 못 찾아 KeyError로
    죽던 실제 버그. 재료대체의 EC-05와 같은 방식으로 정직하게 되물어야 한다."""
    client = FakeSupabaseClient()
    session: dict = {}

    result = handle_utterance(session, "다음", client=client)

    assert result["intent"] == "미분류"
    assert "message" in result
    assert "current_recipe_id" not in session


def test_handle_utterance_resume_repeats_current_step():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 2}

    result = handle_utterance(session, "다시", client=client)

    assert result["intent"] == "재청취"
    assert result["step_number"] == 2


def test_handle_utterance_previous_at_step_one_flags_no_previous():
    client = FakeSupabaseClient()
    recipe = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": recipe["id"], "step_number": 1}

    result = handle_utterance(session, "이전", client=client)

    assert result["intent"] == "이전"
    assert result["no_previous"] is True


def test_handle_utterance_substitution_updates_session_and_can_be_cancelled():
    client = FakeSupabaseClient()
    base = _seed_recipe_with_steps(client)
    client.table("recipes").seed({"dish_name": "새우된장찌개", "ingredients": "새우", "source": "api_standard"})
    session = {"current_recipe_id": base["id"], "step_number": 2}

    result = handle_utterance(session, "새우도 넣어도 될까?", requested_ingredient=["새우"], client=client)

    assert result["intent"] == "재료대체"
    assert result["result_dish_name"] == "새우된장찌개"
    assert session["current_recipe_id"] == result["result_recipe_id"]
    assert session["previous_recipe_id"] == base["id"]
    assert session["step_number"] == 2  # 7.1.1: 재료대체 후에도 step_number는 그대로 유지

    cancel_result = handle_utterance(session, "취소해줘", client=client)

    assert cancel_result["intent"] == "취소"
    assert cancel_result["rolled_back"] is True
    assert session["current_recipe_id"] == base["id"]


def test_handle_utterance_substitution_no_match_reports_match_type_none():
    """이슈 #8(tests/integration_issues_2026-08-18.md): 매칭 완전 실패 시
    match_type == "none"이 handle_utterance() 응답에서 조용히 빠질 수 있는데도
    이를 지키는 pytest 회귀테스트가 없었다. tests/integration_test.md 시나리오 C를
    그대로 옮겨 직접 assert한다."""
    client = FakeSupabaseClient()
    base = _seed_recipe_with_steps(client)
    session = {"current_recipe_id": base["id"], "step_number": 2}

    result = handle_utterance(
        session, "문어랑 성게 같이 넣어도 돼?", requested_ingredient=["문어", "성게"], client=client
    )

    assert result["intent"] == "재료대체"
    assert result["match_type"] == "none"
    assert result["message"]  # 그럴싸하게 지어내지 않고 정직한 안내 문구가 있어야 함(1.5 원칙)
    assert session["current_recipe_id"] == base["id"]  # 매칭 실패 시 세션은 그대로 유지


def test_handle_utterance_search_sets_current_recipe():
    client = FakeSupabaseClient()
    recipe = client.table("recipes").seed({"dish_name": "떡볶이", "ingredients": "떡", "source": "api_standard"})
    session: dict = {}

    result = handle_utterance(session, "떡볶이 어떻게 만들어?", dish_name="떡볶이", client=client)

    assert result["intent"] == "조회"
    assert session["current_recipe_id"] == recipe["id"]
    assert session["step_number"] == 1


def test_handle_utterance_search_extracts_dish_name_from_utterance_when_not_given():
    """dish_name을 안 넘겨도 발화 자체에서 요리명을 뽑아 조회까지 이어져야 함(extract_dish_name 연결)."""
    client = FakeSupabaseClient()
    recipe = client.table("recipes").seed({"dish_name": "떡볶이", "ingredients": "떡", "source": "api_standard"})
    session: dict = {}

    result = handle_utterance(session, "떡볶이 어떻게 만들어?", client=client)

    assert result["intent"] == "조회"
    assert session["current_recipe_id"] == recipe["id"]


def test_handle_utterance_search_extraction_fails_is_honest_about_it():
    """발화는 "조회" 의도로는 분류되지만(어떻게 만들어? 패턴), DB에 없는/유사어 없는
    요리명이라 extract_dish_name() 자체가 실패하는 경우도 정직하게 안내해야 함."""
    client = FakeSupabaseClient()
    session: dict = {}

    result = handle_utterance(session, "분홍코끼리조림 어떻게 만들어?", client=client)

    assert result["intent"] == "조회"
    assert result["message"] == DISH_NOT_FOUND_MESSAGE
    assert "current_recipe_id" not in session


def test_handle_utterance_search_dish_not_found_is_honest_about_it():
    client = FakeSupabaseClient()
    session: dict = {}

    result = handle_utterance(session, "떡볶이 어떻게 만들어?", dish_name="세상에없는요리", client=client)

    assert result["intent"] == "조회"
    assert result["message"] == DISH_NOT_FOUND_MESSAGE
    assert "current_recipe_id" not in session


def test_handle_utterance_registration_routes_to_register_recipe():
    client = FakeSupabaseClient()
    session: dict = {}

    result = handle_utterance(
        session, "새 레시피 등록하고 싶어", registration_step="dish_name", registration_value="김치찜", client=client
    )

    assert result["intent"] == "등록"
    assert result["prompt"] == "김치찜에 들어가는 재료를 알려주세요."
    assert session["registration"]["dish_name"] == "김치찜"


def test_handle_utterance_unclassified_returns_fallback_message():
    client = FakeSupabaseClient()
    session: dict = {}

    result = handle_utterance(session, "어… 그거…", client=client)

    assert result["intent"] == "미분류"
    assert "message" in result
