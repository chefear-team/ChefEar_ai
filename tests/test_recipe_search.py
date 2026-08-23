"""recipe_search.py 테스트 — 문서 7.3/7.6 AC-03~05, EC-06~09, EC-18~20.

FakeSupabaseClient(인메모리)로 필터링/선정 로직만 검증한다. 실제 Supabase(PostgREST)
연동 자체는 자격증명 확보 후 별도 확인이 필요하다(작업1 보고 참고).
"""
from fake_supabase import FakeSupabaseClient

from orchestration.recipe_search import (
    NOT_FOUND_MESSAGE,
    extract_dish_name,
    search_by_ingredient_content,
    search_variant_recipe,
    select_standard_recipe,
)


def test_ac03_exact_name_match():
    client = FakeSupabaseClient()
    base = client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부, 감자", "source": "api_standard"})
    client.table("recipes").seed({"dish_name": "바지락된장찌개", "ingredients": "바지락, 두부", "source": "api_standard"})

    result = search_variant_recipe(base["id"], ["바지락"], client=client)

    assert result["match_type"] == "exact_name"
    assert result["result_dish_name"] == "바지락된장찌개"


def test_ac04_ingredient_content_match_with_and_condition():
    """EC-07(AND 조건) 동시 검증: 새우만 있거나 바지락만 있는 레시피는 안 걸려야 함."""
    client = FakeSupabaseClient()
    base = client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부, 감자", "source": "api_standard"})
    client.table("recipes").seed({"dish_name": "새우된장찌개", "ingredients": "새우, 두부", "source": "api_standard"})
    client.table("recipes").seed(
        {"dish_name": "해물된장찌개", "ingredients": "새우, 바지락조개, 두부", "source": "api_standard"}
    )  # EC-06: "바지락"이 "바지락조개"에 부분 매칭돼야 함

    result = search_variant_recipe(base["id"], ["새우", "바지락"], client=client)

    assert result["match_type"] == "ingredient_content"
    assert result["result_dish_name"] == "해물된장찌개"


def test_ac05_no_match_returns_honest_none_message():
    client = FakeSupabaseClient()
    base = client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부, 감자", "source": "api_standard"})

    result = search_variant_recipe(base["id"], ["문어", "성게"], client=client)

    assert result == {"match_type": "none", "message": NOT_FOUND_MESSAGE}


def test_ec08_excluded_ingredient_filters_out_matches_that_contain_it():
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "해물된장찌개", "ingredients": "새우, 애호박, 두부", "source": "api_standard"}
    )
    ok = client.table("recipes").seed({"dish_name": "새우된장찌개", "ingredients": "새우, 두부", "source": "api_standard"})

    result = search_by_ingredient_content("base-id", ["새우"], excluded_ingredient="애호박", client=client)

    assert result["match_type"] == "ingredient_content"
    assert result["result_recipe_id"] == ok["id"]


def test_ec09_multiple_matches_picks_highest_view_count():
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "새우된장찌개", "ingredients": "새우, 두부", "source": "api_standard", "view_count": 10}
    )
    best = client.table("recipes").seed(
        {"dish_name": "새우된장찌개2", "ingredients": "새우, 대파", "source": "api_standard", "view_count": 999}
    )

    result = search_by_ingredient_content("base-id", ["새우"], client=client)

    assert result["result_recipe_id"] == best["id"]


def test_ec18_single_candidate_full_representativeness():
    client = FakeSupabaseClient()
    row = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "두부", "source": "api_standard", "view_count": 1403370}
    )

    result = select_standard_recipe("된장찌개", client=client)

    assert result["recipe_id"] == row["id"]
    assert result["total_candidates"] == 1
    assert result["representativeness"] == 1.0


def test_ec19_all_zero_view_count_uses_latest_created_at():
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {
            "dish_name": "신메뉴",
            "ingredients": "재료",
            "source": "api_standard",
            "view_count": 0,
            "created_at": "2026-01-01T00:00:00",
        }
    )
    newest = client.table("recipes").seed(
        {
            "dish_name": "신메뉴",
            "ingredients": "재료",
            "source": "api_standard",
            "view_count": 0,
            "created_at": "2026-06-01T00:00:00",
        }
    )

    result = select_standard_recipe("신메뉴", client=client)

    assert result["recipe_id"] == newest["id"]


def test_ec20_user_custom_preferred_over_api_standard():
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "표준 재료", "source": "api_standard", "view_count": 1403370}
    )
    mine = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "내 맘대로 재료", "source": "user_custom", "view_count": 0}
    )

    result = select_standard_recipe("된장찌개", client=client)

    assert result["recipe_id"] == mine["id"]


def test_not_found_dish_name_returns_none():
    client = FakeSupabaseClient()
    assert select_standard_recipe("존재하지않는요리", client=client) is None


def test_owner_id_scoping_prefers_own_user_custom_over_others_and_standard():
    """작업3(FR-08): 여러 사용자의 user_custom이 섞여 있어도 내 것만 우선해야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "표준", "source": "api_standard", "view_count": 100}
    )
    others = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "남의 것", "source": "user_custom", "owner_id": "user-B"}
    )
    mine = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "내 것", "source": "user_custom", "owner_id": "user-A"}
    )

    result = select_standard_recipe("된장찌개", owner_id="user-A", client=client)

    assert result["recipe_id"] == mine["id"]
    assert result["recipe_id"] != others["id"]


def test_owner_id_scoping_falls_back_to_standard_when_only_others_custom_exists():
    client = FakeSupabaseClient()
    standard = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "표준", "source": "api_standard", "view_count": 100}
    )
    client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "남의 것", "source": "user_custom", "owner_id": "user-B"}
    )

    result = select_standard_recipe("된장찌개", owner_id="user-A", client=client)

    assert result["recipe_id"] == standard["id"]


def test_owner_id_scoping_never_leaks_others_custom_when_no_standard_exists():
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "이색요리", "ingredients": "남의 것", "source": "user_custom", "owner_id": "user-B"}
    )

    result = select_standard_recipe("이색요리", owner_id="user-A", client=client)

    assert result is None


def test_extract_dish_name_exact_match():
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("부대찌개", client=client) == "부대찌개"


def test_extract_dish_name_substring_prefers_longer_match():
    """"김치"와 "김치찌개" 둘 다 발화에 포함되면, 더 구체적인 "김치찌개"를 채택해야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "김치", "ingredients": "배추", "source": "api_standard"})
    client.table("recipes").seed({"dish_name": "김치찌개", "ingredients": "김치, 돼지고기", "source": "api_standard"})

    assert extract_dish_name("김치찌개 어떻게 만들어?", client=client) == "김치찌개"


def test_extract_dish_name_fuzzy_matches_stt_misheard_whole_utterance():
    """STT 오인식("부대찌개" -> "부대찌게")이 발화 전체일 때 편집거리로 보정돼야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("부대찌게", client=client) == "부대찌개"


def test_extract_dish_name_fuzzy_matches_misheard_word_inside_sentence():
    """오인식된 요리명이 문장 속에 섞여 있어도(부분일치로는 못 잡음) 편집거리로 잡혀야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("부대찌게 어떻게 만들어?", client=client) == "부대찌개"


def test_extract_dish_name_fuzzy_matches_phoneme_level_mishearing():
    """2026-08-23 실사용 보고: 상시 마이크로 "된장찌개"라고 말했는데 STT가 "된장치게"로
    오인식(찌/치 된소리-거센소리 혼동 + 개/게 애-에 모음 혼동, 자모 하나씩만 다름).
    음절 단위 SequenceMatcher.ratio()는 0.5로 FUZZY_CUTOFF(0.7) 미달이라 기존 구현은
    이 케이스를 못 잡았다 — 자모 분해 비교(_decompose_hangul)로 고쳐서 잡아야 한다."""
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "된장찌개", "ingredients": "두부, 감자", "source": "api_standard"})

    assert extract_dish_name("된장치게", client=client) == "된장찌개"


def test_extract_dish_name_returns_none_when_nothing_close():
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("완전히 다른 이야기입니다", client=client) is None


def test_extract_dish_name_empty_utterance_returns_none():
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("   ", client=client) is None
