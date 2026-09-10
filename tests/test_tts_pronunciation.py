"""tts/pronunciation.py 회귀테스트 — TTS 직전 텍스트 보정(겹받침 연음 치환, 단계 번호 한글화, 문장 종결 보정)."""
from tts.pronunciation import apply_pronunciation_fixes


def test_dalgeul_liaison_fix_applied():
    assert apply_pronunciation_fixes("닭을 손질하세요") == "달글 손질하세요. "


def test_untouched_word_containing_similar_substring_is_not_broken():
    # "닭갈비"는 "닭을"을 부분 문자열로 포함하지 않으므로 안 바뀌어야 한다.
    assert apply_pronunciation_fixes("닭갈비를 만들어봅시다") == "닭갈비를 만들어봅시다. "


def test_multiple_occurrences_all_fixed():
    assert apply_pronunciation_fixes("닭을 씻고 닭을 손질하세요") == "달글 씻고 달글 손질하세요. "


def test_sentence_without_target_word_gets_terminal_period():
    assert apply_pronunciation_fixes("약불로 5분간 끓여주세요") == "약불로 5분간 끓여주세요. "


def test_existing_sentence_end_is_kept():
    assert apply_pronunciation_fixes("된장을 풀어줍니다.") == "된장을 풀어줍니다. "
    assert apply_pronunciation_fixes("맛있게 드세요!") == "맛있게 드세요! "


def test_step_prefix_is_read_as_korean_step_number():
    assert apply_pronunciation_fixes("3. 양파를 볶아주세요") == "삼단계, 양파를 볶아주세요. "


def test_empty_text_is_returned_unchanged():
    assert apply_pronunciation_fixes("") == ""
    assert apply_pronunciation_fixes("   ") == "   "
