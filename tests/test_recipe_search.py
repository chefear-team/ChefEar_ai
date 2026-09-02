"""recipe_search.py 테스트 — 문서 7.3/7.6 AC-03~05, EC-18~19, 승인(approved) 워크플로우.

FakeSupabaseClient(인메모리)로 필터링/선정 로직만 검증한다. 실제 Supabase(PostgREST)
연동 자체는 자격증명 확보 후 별도 확인이 필요하다(작업1 보고 참고).

2026-08-27 — 재료대체 기능 삭제(remove_ingredient_substitution.md)로 search_variant_recipe()/
search_by_ingredient_content() 테스트를 걷어냈다. 계정/쿠키 시스템 삭제(remove_user_accounts.md)로
owner_id 기반 개인화 테스트도 걷어내고, 대신 관리자 승인(approved) 워크플로우
(admin_recipe_approval.md) 테스트로 교체했다.

2026-09-02 — docs/specs/private_recipe_visibility.md: 로그인 재도입으로 owner_id가 다시
쓰이면서, "승인되면 전체 공개" 테스트를 "승인 + 본인 소유일 때만 공개"로 되돌린다(approved
자체는 레거시 approved='N' 행을 걸러내는 역할로 남아 관련 테스트는 그대로 유지).
"""
from fake_supabase import FakeSupabaseClient

from orchestration.recipe_search import extract_dish_name, select_standard_recipe


def test_single_candidate_selected():
    """2026-09-01 — EC-18(조회수 기반 대표성) 테스트를 대체. 500개 표준 데이터는
    DB unique index(uq_recipes_dish_name_standard)로 요리명당 api_standard가
    정확히 1행만 있도록 이미 보장돼서, "여러 후보 중 대표 선정" 개념 자체가
    없어졌다(select_standard_recipe() 문서 참고) — total_candidates/
    representativeness 필드도 함께 제거됐다. 후보가 하나뿐일 때 그 하나가
    그대로 선택되는지만 확인한다."""
    client = FakeSupabaseClient()
    row = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "두부", "source": "api_standard", "view_count": 1403370}
    )

    result = select_standard_recipe("된장찌개", client=client)

    assert result["recipe_id"] == row["id"]
    assert "total_candidates" not in result
    assert "representativeness" not in result


def test_api_standard_preferred_over_user_custom_same_name():
    """2026-09-01 — EC-19(조회수 0일 때 최신 등록일 우선) 테스트를 대체. 다중
    api_standard 후보 시나리오는 이제 DB 제약상 발생할 수 없어서(위 문서 참고)
    그 규칙 자체가 무의미해졌다. 지금 실제로 남아있는 유일한 다중 후보 케이스—
    같은 요리명으로 api_standard와 user_custom이 같이 있는 경우—를 대신
    검증한다: 검증된 표준(api_standard)이 사용자 임의 제출보다 항상 우선해야
    한다(select_standard_recipe() 문서 참고)."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {
            "dish_name": "신메뉴",
            "ingredients": "재료",
            "source": "user_custom",
            "approved": "Y",
            "created_at": "2026-01-01T00:00:00",
        }
    )
    standard = client.table("recipes").seed(
        {
            "dish_name": "신메뉴",
            "ingredients": "재료",
            "source": "api_standard",
            "created_at": "2026-06-01T00:00:00",
        }
    )

    result = select_standard_recipe("신메뉴", client=client)

    assert result["recipe_id"] == standard["id"]


def test_not_found_dish_name_returns_none():
    client = FakeSupabaseClient()
    assert select_standard_recipe("존재하지않는요리", client=client) is None


def test_pending_when_only_unapproved_user_custom_exists():
    """admin_recipe_approval.md — 등록은 됐지만(approved='N') 아직 관리자 승인 전이면
    등록한 사람 포함 아무도 조회하면 안 되고, "아예 없음"과 구분되는 신호를 받아야 함."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "고등어라테", "ingredients": "고등어, 우유", "source": "user_custom", "approved": "N"}
    )

    result = select_standard_recipe("고등어라테", client=client)

    assert result == {"pending": True}


def test_approved_user_custom_visible_only_to_owner():
    """2026-09-02 — 승인(approved='Y')만으로는 더 이상 전체 공개되지 않는다. 등록한
    본인(owner_id 일치)만 조회되고, 다른 사용자·비로그인 조회자에게는 안 보인다
    (private_recipe_visibility.md)."""
    client = FakeSupabaseClient()
    row = client.table("recipes").seed(
        {
            "dish_name": "고등어라테",
            "ingredients": "고등어|우유",
            "source": "user_custom",
            "approved": "Y",
            "owner_id": "user-a",
        }
    )

    assert select_standard_recipe("고등어라테", client=client, owner_id="user-a")["recipe_id"] == row["id"]
    assert select_standard_recipe("고등어라테", client=client, owner_id="user-b") is None
    assert select_standard_recipe("고등어라테", client=client, owner_id=None) is None


def test_approved_api_standard_visible_to_everyone_regardless_of_owner():
    """api_standard는 owner_id 필터와 무관하게 항상 전체 공개 — 이미 검수된 표준
    데이터라 이번 소유자 제한 대상이 아니다."""
    client = FakeSupabaseClient()
    row = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "두부", "source": "api_standard", "approved": "Y"}
    )

    assert select_standard_recipe("된장찌개", client=client, owner_id=None)["recipe_id"] == row["id"]
    assert select_standard_recipe("된장찌개", client=client, owner_id="아무개")["recipe_id"] == row["id"]


def test_approved_candidate_preferred_over_pending_ones():
    """같은 이름으로 승인 대기 중인 것과 승인된 것이 섞여 있으면, 승인된 것만 후보로 본다."""
    client = FakeSupabaseClient()
    client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "누군가의 초안", "source": "user_custom", "approved": "N"}
    )
    approved = client.table("recipes").seed(
        {"dish_name": "된장찌개", "ingredients": "표준", "source": "api_standard", "approved": "Y", "view_count": 10}
    )

    result = select_standard_recipe("된장찌개", client=client)

    assert result["recipe_id"] == approved["id"]


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


def test_extract_dish_name_ignores_stt_inserted_space_over_shorter_real_dish():
    """2026-08-27 실측 리포트 — "10분잡채"(DB엔 공백 없이 저장)를 STT가 "10분 잡채"로
    중간에 공백을 넣어 인식하면, 그 안에 우연히 들어있는 더 짧은 다른 요리명("잡채",
    이것도 실제 DB에 있음)만 부분일치로 잡혀서 "10분잡채" 대신 "잡채"로 조회되는
    버그였다. 공백을 지운 버전으로도 부분일치를 시도해서 더 긴(구체적인) 이름을
    우선 채택해야 한다."""
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "10분잡채", "ingredients": "당면, 채소", "source": "api_standard"})
    client.table("recipes").seed({"dish_name": "잡채", "ingredients": "당면, 채소", "source": "api_standard"})

    assert extract_dish_name("10분 잡채 레시피", client=client) == "10분잡채"


def test_extract_dish_name_empty_utterance_returns_none():
    client = FakeSupabaseClient()
    client.table("recipes").seed({"dish_name": "부대찌개", "ingredients": "김치, 스팸", "source": "api_standard"})

    assert extract_dish_name("   ", client=client) is None
