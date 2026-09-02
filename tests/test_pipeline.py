"""pipeline.py 테스트 — 문서 7.4/7.1.1 AC-07~09, AC-12/13, handle_utterance() 라우팅."""
from fake_supabase import FakeSupabaseClient

from orchestration.pipeline import (
    DISH_NOT_FOUND_MESSAGE,
    NOT_AVAILABLE_MESSAGE,
    PENDING_MESSAGE,
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
    죽던 실제 버그. 정직하게 되물어야 한다."""
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


def test_handle_utterance_search_pending_approval_gets_distinct_message():
    """admin_recipe_approval.md — 등록은 됐지만 아직 관리자 승인 전(approved='N')이면
    "아예 없음"과는 다른 메시지가 나와야 하고, 세션도 안 바뀌어야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "고등어라테", "ingredients": "고등어, 우유", "source": "user_custom", "approved": "N"}
    )
    session: dict = {}

    result = handle_utterance(session, "고등어라테 어떻게 만들어?", dish_name="고등어라테", client=client)

    assert result["intent"] == "조회"
    assert result["message"] == PENDING_MESSAGE
    assert result["message"] != DISH_NOT_FOUND_MESSAGE
    assert "current_recipe_id" not in session


def test_handle_utterance_search_owner_id_restricts_user_custom_to_owner():
    """2026-09-02 — docs/specs/private_recipe_visibility.md AC-01/02: handle_utterance()가
    받은 owner_id를 select_standard_recipe()까지 그대로 전달해야, 등록자 본인은 바로
    조회되고 다른 사람은 "아예 없음"과 같은 안내를 받는다."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {
            "dish_name": "고등어라테",
            "ingredients": "고등어|우유",
            "source": "user_custom",
            "approved": "Y",
            "owner_id": "user-a",
        }
    )

    owner_session: dict = {}
    owner_result = handle_utterance(
        owner_session, "고등어라테 어떻게 만들어?", dish_name="고등어라테", client=client, owner_id="user-a"
    )
    assert owner_result["intent"] == "조회"
    assert "message" not in owner_result
    assert owner_session["current_recipe_id"] is not None

    stranger_session: dict = {}
    stranger_result = handle_utterance(
        stranger_session, "고등어라테 어떻게 만들어?", dish_name="고등어라테", client=client, owner_id="user-b"
    )
    assert stranger_result["message"] == DISH_NOT_FOUND_MESSAGE
    assert "current_recipe_id" not in stranger_session


def test_handle_utterance_search_llm_dish_name_mismatch_is_honest_not_recovered():
    """2026-08-26 — dish_name(로컬 LLM 추측)이 DB의 정확한 문자열과 한 글자라도 다르면
    (여기선 "된장찌개"의 흔한 오인식 "된장치개") 완전일치가 실패하고, 그대로 "표준
    데이터 밖"으로 안내한다 — 발화 원문으로 extract_dish_name() 보정을 한 번 더
    시도하는 안전망을 잠깐 넣었다가 되돌렸다(알고 있는 한계).

    되돌린 이유: extract_dish_name()의 "후보 중 가장 긴 것을 채택"(길이만 보고
    매칭 신뢰도는 안 봄) 결함이 이 안전망 경로로 새로 노출돼서, 존재하지 않는
    요리("초코민트 된장찌개" 등)가 편집거리 약한 매칭(0.7대)으로 전혀 다른 실제
    요리("토마토된장찌개")에 잘못 매칭되는 문제가 실측 확인됐다 — "모르면 모른다고
    한다"는 1.5 원칙에 이게 더 크게 어긋난다고 판단해, "우리엄마가 만든 된장찌개."
    같은 진짜 매칭 실패 케이스를 못 구하는 손해를 감수하기로 함(pipeline.py::
    handle_utterance() "조회" 분기 주석 참고).
    """
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부", "source": "api_standard"})
    session: dict = {}

    result = handle_utterance(session, "된장찌개 어떻게 만들어?", dish_name="된장치개", client=client)

    assert result["intent"] == "조회"
    assert result["message"] == DISH_NOT_FOUND_MESSAGE
    assert "current_recipe_id" not in session


def test_handle_utterance_search_recovers_when_llm_strips_dish_name_spacing():
    """2026-08-26 실측 리포트 — "직접 등록한 '고등어 라테'가 조회 안 됨" 재현/수정.

    entity_extract_llm.py::extract_intent_llm()이 LLM에 넘기기 전 띄어쓰기를 전부
    지우는 전처리를 하기 때문에(2026-08-20 추가, "소고기 미역국"이 "미역국"만 잘리는
    문제 방지용), LLM이 돌려주는 dish_name도 공백 없이("고등어라테") 오는 경우가
    흔하다 — DB엔 원문 그대로("고등어 라테") 저장돼 있어 완전일치가 실패했다.
    find_dish_name_ignoring_spaces()(공백만 무시하는 완전일치, 편집거리 유사도 아님)로
    구해내야 한다.
    """
    client = FakeSupabaseClient()
    recipe = client.table("recipes").seed(
        {"dish_name": "고등어 라테", "ingredients": "고등어, 우유, 커피", "source": "api_standard"}
    )
    session: dict = {}

    result = handle_utterance(session, "고등어라테 어떻게 만들어?", dish_name="고등어라테", client=client)

    assert result["intent"] == "조회"
    assert "message" not in result
    assert session["current_recipe_id"] == recipe["id"]


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
