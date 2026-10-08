"""ui/theme.py의 순수 로직 헬퍼 테스트 — 사용자 리포트 기반.
"""
from theme import truncate_display_name


def test_short_name_unchanged():
    assert truncate_display_name("hong") == "hong"
    assert truncate_display_name("abcdefghi") == "abcdefghi"  # 정확히 9자는 그대로


def test_long_name_truncated_to_9_chars_plus_ellipsis():
    assert truncate_display_name("longname1234@example.com") == "longname1..."
    assert truncate_display_name("abcdefghij") == "abcdefghi..."
