"""7.3/7.6 — 표준 레시피 선정, 발화 속 요리명 추출.

이 파일의 함수들은 전부 "DB에서 조건에 맞는 레시피를 찾는다"는 공통점이
있는데, 못 찾았을 때 절대로 답을 지어내지 않는다(1.5 원칙: 서비스 실행 중
LLM 생성 fallback 없음). 못 찾으면 그냥 "없다"고 정직하게 답한다.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

from orchestration.db import get_client

# extract_dish_name()의 3단계 중 편집거리 유사도(3번) 판정 기준값. intent_classifier.py의
# THRESHOLD와 같은 성격 — 실측 튜닝 전 임시값이다. 0.75로 하면 "부대찌개"/"부대찌게"(글자
# 하나 차이, 실제 SequenceMatcher 유사도 0.75)가 걸러져버려서, 이 프로젝트가 다루려는
# "STT가 글자 하나 잘못 들은" 케이스를 못 잡는다. 그래서 0.7로 여유를 뒀다.
FUZZY_CUTOFF = 0.7


@lru_cache(maxsize=8)
def _all_dish_names(client) -> list[str]:
    """recipes 테이블에 있는 모든 요리명을 중복 없이 가져온다."""
    names: set[str] = set()
    page_size = 1000
    start = 0
    while True:
        res = client.table("recipes").select("dish_name").range(start, start + page_size - 1).execute()
        rows = res.data
        names.update(row["dish_name"] for row in rows if row.get("dish_name"))
        if len(rows) < page_size:
            break
        start += page_size
    return list(names)


def _decompose_hangul(text: str) -> str:
    """음절 단위 한글을 초성/중성/종성 자모로 풀어헤친다(유니코드 NFD 정규화 — 한글
    완성형 음절은 초성+중성(+종성) 조합으로 알고리즘적으로 합성되므로, 표준 라이브러리
    unicodedata만으로 새 의존성 없이 분해된다).
    """
    return unicodedata.normalize("NFD", text)


def _collapse_stt_repetition(text: str) -> str:
    """faster-whisper(beam_size=1, 그리디 디코딩)가 짧은 음절 조각을 연속으로 반복
    생성하는 디코딩 아티팩트를 접는다 — 실측: "된장찌개"->"된장찌장찌개"("장찌"가 2회
    연속), "가지무침"->"가지무칔무칔무칔"("무칔"이 3회 연속) 둘 다 이 패턴.
    """
    return re.sub(r"(.{2,3})\1+", r"\1", text)


@lru_cache(maxsize=8)
def _decomposed_name_map(client) -> dict[str, str]:
    """자모 분해된 요리명 -> 원본 요리명 매핑. _all_dish_names()와 같은 client별
    캐시 전략을 그대로 따른다(같은 클라이언트로 반복 호출 시 재계산 없음, 캐시 무효화
    한계도 동일 — _all_dish_names() docstring 참고). 서로 다른 두 요리명이 자모까지
    완전히 같아지는 경우는 곧 원본 문자열이 같다는 뜻이라(NFD는 결정적/가역적 변환)
    키 충돌로 서로 다른 요리명이 묻히는 일은 없다.
    """
    return {_decompose_hangul(name): name for name in _all_dish_names(client)}


def extract_dish_name(utterance: str, client=None, fuzzy_cutoff: float = FUZZY_CUTOFF) -> str | None:
    """STT 텍스트 한 문장에서 DB에 실제로 있는 요리명을 찾아낸다."""
    client = client or get_client()
    text = utterance.strip()
    if not text:
        return None

    names = _all_dish_names(client)
    if text in names:
        return text

    candidates = [name for name in names if name and len(name) >= 2 and name in text]

    name_map = _decomposed_name_map(client)
    for candidate in (text, *text.split()):
        close = difflib.get_close_matches(_decompose_hangul(candidate), name_map.keys(), n=1, cutoff=fuzzy_cutoff)
        if close:
            candidates.append(name_map[close[0]])

    collapsed = _collapse_stt_repetition(text)
    if collapsed != text:
        candidates.extend(name for name in names if name and len(name) >= 2 and name in collapsed)
        for candidate in (collapsed, *collapsed.split()):
            close = difflib.get_close_matches(_decompose_hangul(candidate), name_map.keys(), n=1, cutoff=fuzzy_cutoff)
            if close:
                candidates.append(name_map[close[0]])

    text_no_space = re.sub(r"\s+", "", text)
    if text_no_space != text:
        candidates.extend(name for name in names if name and len(name) >= 2 and name in text_no_space)

    if candidates:
        return max(candidates, key=len)

    return None


def find_dish_name_ignoring_spaces(dish_name: str, client=None) -> str | None:
    """dish_name이 DB에 완전일치로는 없지만, 공백만 다르게 붙어서 내용은 정확히 같은
    이름이 있으면 그 DB 원본 문자열을 돌려준다.
    """
    client = client or get_client()
    target = re.sub(r"\s+", "", dish_name)
    if not target:
        return None
    for name in _all_dish_names(client):
        if re.sub(r"\s+", "", name) == target:
            return name
    return None


def find_dish_name_ignoring_repetition(dish_name: str, client=None) -> str | None:
    """dish_name이 DB에 완전일치로는 없지만, 짧은 음절 반복만 접으면 내용이 정확히
    같은 이름이 있으면 그 DB 원본 문자열을 돌려준다. find_dish_name_ignoring_spaces()와
    같은 자리에서 같은 이유로 쓰는 안전망 — fuzzy 매칭이 아니라 "반복만 접으면 정확히
    같은가"만 보므로 다른 요리로 새는 오매칭 위험이 없다.
    """
    client = client or get_client()
    collapsed = _collapse_stt_repetition(dish_name)
    if not collapsed or collapsed == dish_name:
        return None
    if collapsed in _all_dish_names(client):
        return collapsed
    return None


# 질의 접미사 목록 — 로컬 LLM이 dish_name에 "~레시피", "~만드는 법" 같은 문구를 떼지 않고
# 그대로 돌려준 경우를 잡는다(find_dish_name_stripping_query_suffix() 참고).
_QUERY_SUFFIXES_TO_STRIP = (
    "레시피 알려줘",
    "레시피알려줘",
    "만드는 법 알려줘",
    "만드는법 알려줘",
    "어떻게 만들어요",
    "어떻게 만드나요",
    "어떻게 만들어",
    "어떻게 해요",
    "어떻게 해",
    "레시피",  # 가장 짧고 포괄적이라 마지막에 검사(다른 접미사가 먼저 걸리게)
)


def find_dish_name_stripping_query_suffix(dish_name: str, client=None) -> str | None:
    """dish_name 끝에 "레시피"류 질의 접미사가 안 떼진 채 남아있어서 완전일치가
    실패했을 때, 그 접미사를 떼면 DB에 정확히 있는 이름인 경우 그 원본을 돌려준다.
    find_dish_name_ignoring_spaces()/find_dish_name_ignoring_repetition()와 같은
    자리, 같은 성격의 안전망 — 편집거리/유사도를 전혀 안 쓰고 "접미사를 뗀 결과가
    DB에 글자 그대로 있는가"만 본다. 그래서 사용자가 실제로 등록한 적 없는 새 요리를
    말했을 때(예: 존재하지 않는 "OO레시피") 엉뚱한 기존 요리로 새는 오매칭은 구조적으로
    """
    client = client or get_client()
    text = dish_name.strip()
    if not text:
        return None
    names = _all_dish_names(client)
    for suffix in _QUERY_SUFFIXES_TO_STRIP:
        if text.endswith(suffix):
            candidate = text[: -len(suffix)].strip()
            if candidate and candidate in names:
                return candidate
    return None


def find_more_specific_containing_name(dish_name: str, utterance: str, client=None) -> str | None:
    """dish_name이 이미 DB에서 찾아졌지만, 발화 원문 안에 dish_name을 포함하면서 더
    긴(더 구체적인) 다른 DB 요리명이 문자 그대로(공백만 무시) 들어있으면 그 이름을
    돌려준다.
    """
    client = client or get_client()
    text_no_space = re.sub(r"\s+", "", utterance)
    names = _all_dish_names(client)
    candidates = [
        name
        for name in names
        if name
        and len(name) > len(dish_name)
        and dish_name in name
        and re.sub(r"\s+", "", name) in text_no_space
    ]
    if candidates:
        return max(candidates, key=len)
    return None


def select_standard_recipe(dish_name: str, client=None, owner_id: str | None = None) -> dict | None:
    """요리명 하나를 받아서, 보여줄 "그 요리의 대표 레시피" 하나를 고른다."""
    client = client or get_client()
    # .eq("dish_name", ...) : dish_name이 정확히 일치하는 행만
    # .in_("source", [...]) : source가 두 값 중 하나인 행만 (SQL의 WHERE ... IN (...) 과 같음)
    # .order("created_at") : api_standard가 없을 때 "가장 먼저 등록된 것"을 결정론적으로
    # 고르기 위한 정렬 — 정렬 없이는 Supabase가 어떤 순서로 돌려줄지 보장이 없다.
    res = (
        client.table("recipes")
        .select("*")
        .eq("dish_name", dish_name)
        .in_("source", ["api_standard", "user_custom"])
        .order("created_at")
        .execute()
    )
    rows = res.data
    if not rows:
        return None  # 이 요리명 자체가 DB에 아예 없음 (6.5: 표준 데이터 밖 요리)

    approved_rows = [r for r in rows if r.get("approved") == "Y"]
    if not approved_rows:
        return {"pending": True}  # 있지만 전부 (레거시) 관리자 승인 대기 중

    candidates = [
        r
        for r in approved_rows
        if r.get("source") == "api_standard"
        or (
            owner_id is not None
            and r.get("owner_id") is not None
            and r.get("owner_id") == owner_id
        )
    ]
    if not candidates:
        return None  # 존재는 하지만 전부 남의 user_custom — 이 조회자에겐 "없음"과 동일

    # api_standard가 후보에 있으면 항상 그걸 우선(검증된 표준이라 신뢰도가 더 높음).
    # 없으면(사용자만 등록한 요리) 위 order("created_at")로 이미 정렬돼 있으므로
    # candidates[0]이 곧 "가장 먼저 등록된 승인 버전"이다.
    winner = next((r for r in candidates if r.get("source") == "api_standard"), candidates[0])

    return {
        "recipe_id": winner["id"],
        "dish_name": winner["dish_name"],
        "view_count": winner.get("view_count", 0),
        "ingredients": winner.get("ingredients", ""),
    }
