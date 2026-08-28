"""classify_intent() 테스트 — 문서 7.2 AC-01/AC-02/AC-10, EC-01~05."""
from orchestration.intent_classifier import FALLBACK_UNCLASSIFIED, THRESHOLD, _pick_intent, classify_intent


def test_ac01_next_utterance_classified_as_progress():
    result = classify_intent("다음")
    assert result["intent"] == "진행"
    assert result["similarity_score"] >= THRESHOLD


def test_ac02_ambiguous_utterance_returns_unclassified_without_crash():
    result = classify_intent("어… 그거…")
    assert result["intent"] == "미분류"
    assert "fallback_message" in result


def test_ec04_empty_utterance_skips_classification():
    result = classify_intent("")
    assert result == {
        "intent": "미분류",
        "similarity_score": 0.0,
        "fallback_message": "다시 말씀해주세요.",
    }


# 2026-08-27 — 재료대체 기능 자체를 삭제했다(remove_ingredient_substitution.md).
# "재료대체"가 VALID_INTENTS에서 완전히 빠져서 기준예문.csv에 그 카테고리 행이
# 있어도 _load_examples()가 걸러내므로, "바지락 넣어도 돼?" 같은 발화는 구조적으로
# 다시는 "재료대체"로 분류될 수 없다 — 아래 두 테스트는 항상 일반
# 미분류(FALLBACK_UNCLASSIFIED)로 떨어진다는 걸 확인한다 — context_recipe_id 유무와
# 무관하게 동일하다(예전엔 있고 없고에 따라 다른 메시지가 나갔음).
def test_ec05_substitution_intent_without_context_falls_to_unclassified():
    result = classify_intent("바지락 넣어도 돼?", context_recipe_id=None)
    assert result["intent"] == "미분류"
    assert result["fallback_message"] == FALLBACK_UNCLASSIFIED


def test_ec05_substitution_intent_with_context_also_falls_to_unclassified():
    result = classify_intent("바지락 넣어도 돼?", context_recipe_id="recipe-123")
    assert result["intent"] == "미분류"
    assert result["fallback_message"] == FALLBACK_UNCLASSIFIED


# 2026-08-26 요청 — 조리 3단계("돼지고기와 새우젓을 손질해주세요") 중에 "돼지고기과?"라고만
# 말했더니 "돼지고기"를 새 요리명으로 보고 완전히 새로운 조회가 시작돼 조리가 처음부터
# 리셋된 실측 리포트. 처음엔 "한 단어짜리 발화만" 막았는데, 재요청으로 원칙이 바뀌었다:
# "레시피 전환이 되면 안 된다, 절대로" — 조리 중엔("이미 어떤 레시피를 진행 중" =
# context_recipe_id 있음) "조회"가 아무리 명확한 문장이어도("된장찌개로 바꿔줘") 무조건
# 막는다. 다른 레시피를 원하면 "처음"으로 돌아가 초기 화면에서 다시 검색해야 한다 —
# 그게 유일한 전환 경로다(reset_to_start()/is_home_word()는 이 함수를 안 거치는
# 별개 경로라 여전히 정상 동작함).
def test_dish_lookup_mid_cooking_is_always_ignored_even_bare_name():
    result = classify_intent("돼지고기", context_recipe_id="recipe-123")
    assert result["intent"] == "미분류"


def test_dish_lookup_mid_cooking_is_always_ignored_even_explicit_switch_request():
    result = classify_intent("된장찌개로 바꿔줘", context_recipe_id="recipe-123")
    assert result["intent"] == "미분류"


def test_dish_lookup_without_context_still_works_as_normal_search():
    # 조리 중이 아니면(아직 아무 레시피도 안 고른 첫 조회) 정상적인 사용법이라
    # 그대로 "조회"로 통과해야 한다 — 위 두 테스트와 대비.
    result = classify_intent("된장찌개", context_recipe_id=None)
    assert result["intent"] == "조회"


def test_ec03_ambiguous_resume_phrase_prioritized_as_progress():
    result = classify_intent("다시 진행해")
    assert result["intent"] == "진행"


# 2026-08-26 요청 — "등록"은 조리 중(context_recipe_id 있음)엔 무시하고, 아직
# 레시피를 안 고른 첫 화면(context_recipe_id 없음)에서만 인정한다.
def test_register_intent_with_context_is_ignored_mid_cooking():
    result = classify_intent("이 레시피 등록해줘", context_recipe_id="recipe-123")
    assert result["intent"] == "미분류"


def test_register_intent_without_context_is_classified():
    result = classify_intent("이 레시피 등록해줘", context_recipe_id=None)
    assert result["intent"] == "등록"


# --- 아래는 _pick_intent()에 합성 점수를 직접 넣어 threshold/margin 로직만 단위테스트 ---


def test_ac10_close_top1_top2_within_margin_returns_unclassified():
    ranked = [
        ("진행", (0.60, "다음")),
        ("재청취", (0.58, "다시")),  # 차이 0.02 < MARGIN(0.05)
    ]
    result = _pick_intent(ranked, context_recipe_id=None)
    assert result["intent"] == "미분류"


def test_pick_intent_below_threshold_returns_unclassified():
    ranked = [("진행", (THRESHOLD - 0.1, "다음"))]
    result = _pick_intent(ranked, context_recipe_id=None)
    assert result["intent"] == "미분류"


def test_pick_intent_clear_winner_above_margin_is_classified():
    ranked = [
        ("진행", (0.90, "다음")),
        ("재청취", (0.50, "다시")),  # 차이 0.4 >= MARGIN
    ]
    result = _pick_intent(ranked, context_recipe_id=None)
    assert result["intent"] == "진행"
    assert result["matched_example"] == "다음"
