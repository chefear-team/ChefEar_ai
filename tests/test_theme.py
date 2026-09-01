"""ui/theme.py의 순수 로직 헬퍼 테스트 — 사용자 리포트(2026-09-01, 긴 유저명이
브랜드 버튼/마이레시피 배지를 늘어뜨리는 문제) 기반."""
from theme import truncate_display_name


def test_short_name_unchanged():
    assert truncate_display_name("hong") == "hong"
    assert truncate_display_name("abcdefghi") == "abcdefghi"  # 정확히 9자는 그대로


def test_long_name_truncated_to_9_chars_plus_ellipsis():
    assert truncate_display_name("hlkm1667hehe@gmail.com") == "hlkm1667h..."
    assert truncate_display_name("abcdefghij") == "abcdefghi..."
