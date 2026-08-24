"""tts/pronunciation.py 테스트 — "닭을" 겹받침 연음 오발음 패치(2026-08-19 실측 확인)."""
from tts.pronunciation import apply_pronunciation_fixes


def test_dalgeul_liaison_fix_applied():
    assert apply_pronunciation_fixes("닭을 손질하세요") == "달글 손질하세요"


def test_untouched_word_containing_similar_substring_is_not_broken():
    # "닭갈비"는 "닭을"을 부분 문자열로 포함하지 않으므로 안 바뀌어야 함.
    assert apply_pronunciation_fixes("닭갈비를 만들어봅시다") == "닭갈비를 만들어봅시다"


def test_multiple_occurrences_all_fixed():
    assert (
        apply_pronunciation_fixes("닭을 씻고 닭을 손질하세요")
        == "달글 씻고 달글 손질하세요"
    )


def test_sentence_without_target_word_is_unchanged():
    assert apply_pronunciation_fixes("약불로 5분간 끓여주세요") == "약불로 5분간 끓여주세요"
