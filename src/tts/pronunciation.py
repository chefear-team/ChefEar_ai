"""TTS에 넘기기 직전 텍스트에만 적용하는 발음 보정."""

from __future__ import annotations

import re

PRONUNCIATION_FIXES: dict[str, str] = {
    "닭을": "달글",
}

_PATTERN = re.compile("|".join(re.escape(k) for k in PRONUNCIATION_FIXES))

_STEP_NUMBER_WORDS: dict[int, str] = {
    1: "일", 2: "이", 3: "삼", 4: "사", 5: "오",
    6: "육", 7: "칠", 8: "팔", 9: "구", 10: "십",
    11: "십일", 12: "십이", 13: "십삼", 14: "십사", 15: "십오",
    16: "십육", 17: "십칠", 18: "십팔", 19: "십구", 20: "이십",
}
_STEP_PREFIX_PATTERN = re.compile(r"^\s*(\d{1,2})\.\s*")


def _replace_step_prefix(match: re.Match[str]) -> str:
    word = _STEP_NUMBER_WORDS.get(int(match.group(1)))
    if word is None:
        return match.group(0)  # 매핑 밖 숫자(21+) — 안전하게 원문 그대로 둔다
    return f"{word}단계, "


_SENTENCE_END_CHARS = (".", "!", "?", "…")


def apply_pronunciation_fixes(text: str) -> str:
    """TTS에 넘기기 직전에만 적용 — 화면 표시·로그·DB에 쓰이는 원문은 건드리지 않는다."""

    text = _STEP_PREFIX_PATTERN.sub(_replace_step_prefix, text, count=1)

    if PRONUNCIATION_FIXES:
        text = _PATTERN.sub(lambda m: PRONUNCIATION_FIXES[m.group(0)], text)

    stripped = text.rstrip()
    if not stripped:
        return text

    if not stripped.endswith(_SENTENCE_END_CHARS):
        stripped += "."

    return stripped + " "
