"""사용자가 입력한 글자의 검증·정리·공격 문구 차단. 서비스에 들어오는 모든 글자(채팅, 음성 인식 결과, 등록 폼,
마이레시피 수정, TTS)는 이 모듈을 한 번 거친다.

방어는 겹겹이다. 이 모듈은 그중 입력 쪽 층이고, 아래는 구조로 이미 막혀 있다.
  - DB 조회는 전부 supabase-py 의 `.eq()` 같은 파라미터 방식이라 사용자 글자가 SQL·PostgREST 필터 문법으로 해석되지 않는다.
  - 화면은 React 가 글자를 이스케이프해서 그리므로 저장된 `<script>` 가 실행되지 않는다.
  - 새 서버는 LLM 을 쓰지 않아 프롬프트 주입 대상이 없다(그래도 문구는 막아 두어 나중에 LLM 을 붙여도 안전하게 한다).
  - 로그인 전용, 분당 요청 제한, 본인 소유 레시피만 접근(IDOR 방지).

여기서 하는 일:
  1) 정리: 유니코드 정규화, 제어문자·보이지 않는 문자(제로폭, 양방향 제어) 제거, 공백 정리
  2) 제한: 필드별 최대 길이, 목록 개수, 문자열이 아닌 값 거부
  3) 차단: 명백한 공격 문구(스크립트·SQL·명령·템플릿·프롬프트 주입)는 처리하지 않고 버린다
"""
from __future__ import annotations

import re
import unicodedata


class InputRejected(Exception):
    """입력이 규칙에 맞지 않을 때. code 는 API 가 그대로 돌려주는 짧은 영문 코드다."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# 필드별 최대 길이(글자 수)와 목록 최대 개수
MAX_UTTERANCE = 200
MAX_DISH_NAME = 80
MAX_INGREDIENT = 60
MAX_INGREDIENTS = 40
MAX_STEP = 200
MAX_STEPS = 30
MAX_TTS = 600

# 제로폭·양방향 제어·소프트 하이픈 등 눈에 안 보이지만 글자를 속이는 문자
_INVISIBLE = dict.fromkeys(
    map(ord, "​‌‍‎‏‪‫‬‭‮⁠⁦⁧⁨⁩﻿­"),
    None,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """유니코드 정규화, 보이지 않는 문자·제어문자 제거, 공백(줄바꿈 포함)을 한 칸으로."""
    t = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    t = _CONTROL.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


def clean(value: object, *, max_len: int, field: str) -> str:
    """문자열만 받는다. 정리한 글자를 돌려주고, 너무 길거나 문자열이 아니면 InputRejected."""
    if not isinstance(value, str):
        raise InputRejected("invalid_input")
    text = normalize(value)
    if len(text) > max_len:
        raise InputRejected(f"{field}_too_long")
    return text


def clean_list(value: object, *, max_items: int, max_len: int, field: str) -> list[str]:
    """문자열 목록. 빈 항목은 버리고, 개수·길이를 제한한다."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise InputRejected("invalid_input")
    if len(value) > max_items * 2:  # 빈 항목이 섞여도 터무니없는 크기는 먼저 거절
        raise InputRejected(f"{field}_too_many")
    items = [clean(x, max_len=max_len, field=field) for x in value]
    items = [x for x in items if x]
    if len(items) > max_items:
        raise InputRejected(f"{field}_too_many")
    return items


# ---------------------------------------------------------------------------
# 명백한 공격 문구. 요리 이야기에 나올 일이 거의 없는 형태만 잡는다(오탐을 피하려고 느슨한 단어는 쓰지 않는다).
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "script",
        re.compile(
            r"<\s*/?\s*(script|iframe|img|svg|object|embed|style|link|meta|body|html|form|input|video|audio|base)\b"
            r"|\bon[a-z]{3,}\s*=|javascript\s*:|vbscript\s*:|data\s*:\s*text/html",
            re.I,
        ),
    ),
    (
        "sql",
        re.compile(
            r"\bunion\b\s+(all\s+)?\bselect\b"
            r"|\b(drop|truncate|alter)\s+(table|database|schema)\b"
            r"|;\s*(drop|delete|insert|update|select|exec)\b"
            r"|['\"]\s*(or|and)\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+"
            r"|\b(or|and)\s+\d+\s*=\s*\d+"
            r"|\bpg_sleep\s*\(|\bsleep\s*\(\s*\d|\binformation_schema\b|\bpg_catalog\b|/\*.*\*/"
            r"|--\s*$",
            re.I,
        ),
    ),
    (
        "command",
        re.compile(
            r"\$\(|`[^`]*`|\|\s*(sh|bash|zsh|cmd|powershell)\b|;\s*(rm|curl|wget|cat|nc|chmod|sudo)\b"
            r"|\brm\s+-rf\b|\.\./|\.\.\\|/etc/(passwd|shadow)|\bc:\\windows\b|\bcmd(\.exe)?\s*/c\b",
            re.I,
        ),
    ),
    ("template", re.compile(r"\{\{.*?\}\}|\$\{.*?\}|<%.*?%>|\{%.*?%\}")),
    (
        "prompt",
        re.compile(
            r"ignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)"
            r"|disregard\s+(all\s+|the\s+)?(previous|prior|above)"
            r"|(reveal|show|print|repeat)\s+(your\s+|the\s+)?(system\s+)?prompt"
            r"|\bsystem\s*prompt\b|\bdeveloper\s*mode\b|\bjailbreak\b|\bDAN\s+mode\b|\byou\s+are\s+now\b"
            r"|(이전|위의|앞의|기존|지금까지의)\s*(지시|명령|프롬프트|규칙|설정)\S*\s*(을|를)?\s*(모두\s*)?(무시|잊어|취소)"
            r"|시스템\s*프롬프트|프롬프트\s*(를|을)?\s*(알려|보여|출력)|탈옥",
            re.I,
        ),
    ),
]


def suspicious(text: str) -> str | None:
    """공격 문구로 보이면 어떤 종류인지(script/sql/command/template/prompt)를, 아니면 None."""
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            return name
    return None


def log_blocked(kind: str, field: str, text: str) -> None:
    """차단 기록. 줄바꿈으로 로그를 속이지 못하게 repr 로, 길이도 잘라서 남긴다."""
    print(f"[guard] 차단 kind={kind} field={field} text={text[:60]!r}", flush=True)


def check_text(value: object, *, max_len: int, field: str) -> str:
    """정리 + 길이 제한 + 공격 문구 차단을 한 번에. 차단되면 InputRejected('invalid_text')."""
    text = clean(value, max_len=max_len, field=field)
    kind = suspicious(text)
    if kind:
        log_blocked(kind, field, text)
        raise InputRejected("invalid_text")
    return text
