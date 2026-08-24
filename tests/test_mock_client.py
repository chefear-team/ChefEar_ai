"""db.get_client()의 mock 폴백 — 강사 체크리스트 4번("백엔드 골격, 가짜 응답 먼저").

이 파일만 유일하게 client 인자를 안 넘기고 함수를 부른다 — 나머지 테스트 파일들은
전부 FakeSupabaseClient()를 직접 만들어서 넘기지만(테스트 격리를 위해), 여기서는
"자격증명이 없을 때 정말로 자동 폴백이 되는지" 자체를 확인해야 하므로 일부러
client를 생략해서 orchestration.db.get_client()가 실제로 호출되게 만든다.
"""
import pytest

from orchestration import db
from orchestration.mock_client import FakeSupabaseClient
from orchestration.recipe_search import search_by_ingredient_content, search_variant_recipe, select_standard_recipe


@pytest.fixture(autouse=True)
def _no_supabase_credentials(monkeypatch):
    """이 테스트 파일 안에서는 SUPABASE_URL/KEY를 강제로 비워서 mock 폴백 경로를 타게 한다.

    load_env()도 같이 no-op으로 막아야 한다 — 실제 .env 파일이 있으면(이제 이
    프로젝트엔 있음) delenv로 지워도 get_client()가 호출하는 load_env()가
    os.environ.setdefault()로 파일에서 다시 채워 넣어서 delenv가 무의미해진다.
    """
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setattr(db, "load_env", lambda *args, **kwargs: None)
    db._mock_client_singleton.cache_clear()  # 테스트끼리 가짜 DB 상태가 새지 않게 매번 초기화


def test_get_client_returns_mock_when_no_credentials():
    client = db.get_client()
    assert isinstance(client, FakeSupabaseClient)


def test_get_client_with_allow_mock_false_raises_without_credentials():
    with pytest.raises(RuntimeError):
        db.get_client(allow_mock=False)


def test_scenario_a_select_standard_recipe_returns_seeded_doenjang():
    """문서 5장 시나리오 A: "된장찌개 어떻게 만들어?" """
    result = select_standard_recipe("된장찌개")
    assert result is not None
    assert result["dish_name"] == "된장찌개"


def test_scenario_b_ingredient_substitution_exact_name_match():
    """문서 5장 시나리오 B: 된장찌개 진행 중 "바지락 넣어도 돼?" -> 바지락된장찌개."""
    base = select_standard_recipe("된장찌개")
    result = search_variant_recipe(base["recipe_id"], ["바지락"])
    assert result["match_type"] == "exact_name"
    assert result["result_dish_name"] == "바지락된장찌개"


def test_6_4_ingredient_content_match_when_no_exact_name_exists():
    """문서 6.4 실측 사례: "새우+바지락 둘 다" -> 이름 매칭 실패 -> 해물된장찌개로 재료 내용 매칭."""
    base = select_standard_recipe("된장찌개")
    result = search_by_ingredient_content(base["recipe_id"], ["새우", "바지락"])
    assert result["match_type"] == "ingredient_content"
    assert result["result_dish_name"] == "해물된장찌개"
