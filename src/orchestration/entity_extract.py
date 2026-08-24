"""자유발화에서 요리명/재료명을 뽑아내는 규칙 기반 v1.

`classify_intent()`는 의도만 분류하고 세부 정보(요리명/재료명)는 추출하지 않는다
(`handle_utterance()`의 docstring 참고) — 원래 app.py가 채워야 할 몫으로 남겨져 있던
부분이다. LLM은 런타임에서 못 쓰므로(1.5 원칙), 임베딩도 아닌 순수 문자열 연산(정규식/
토큰 분리)만 쓴다 — 응답시간에 영향 없음(마이크로초~밀리초 단위, STT/TTS 병목과 무관).

두 종류를 지원한다:
  - extract_dish_name(): "조회" 의도 — data/intent_examples/기준예문.csv의
    "{요리명} 어떻게 만들어?" 고정 템플릿에 근거해 접미사를 잘라낸다.
  - extract_substitution_ingredients(): "재료대체" 의도 — 기준예문 3개 문형
    ("애호박 빼고 바지락 넣어도 괜찮아?" 등)에 근거한 토큰 기반 추출.

v1 한계: 위 문형 밖의 표현은 놓칠 수 있다. threshold/margin(OI-09)과 같은 성격의
"실측 후 확정" 항목 — 실사용 데이터가 쌓이면 규칙을 보강해야 한다.
"""
from __future__ import annotations

# ============================================================
# 조회: 요리명 추출
# ============================================================

# data/intent_examples/기준예문.csv "요리명_조회문장" 카테고리가 전부 이 접미사로 끝난다.
# 실사용에서 나올 법한 변형(만드는 법/레시피/어떻게 해)도 같이 넣어둠 — 넓은 것부터 검사.
_QUERY_SUFFIXES = (
    "어떻게 만들어요",
    "어떻게 만드나요",
    "어떻게 만들어",
    "만드는 법 알려줘",
    "만드는법 알려줘",
    "레시피 알려줘",
    "어떻게 해요",
    "어떻게 해",
)


def extract_dish_name(utterance: str) -> str:
    """"된장찌개 어떻게 만들어?" -> "된장찌개". 접미사가 없으면 발화 전체를 그대로 돌려준다
    (요리명만 짧게 말한 경우도 대응하기 위함)."""
    text = utterance.strip().rstrip("?!. ")
    for suffix in sorted(_QUERY_SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


# ============================================================
# 재료대체: 요청/제외 재료 추출
# ============================================================

# 어간(stem)만 확인 — 한국어 활용어미(도/줘/요/까 등)가 뒤에 더 붙어도 startswith로 잡힘.
_REQUEST_STEMS = ("넣어", "추가해", "바꿔", "바뀌", "넣고")
_EXCLUDE_STEMS = ("빼고", "빼줘", "빼주", "말고", "제외")

# 조사(길이 긴 것부터 검사해야 "으로"가 "로"만 잘리는 일이 없음)
_JOSA_SUFFIXES = (
    "으로", "이랑", "까지", "부터", "에서", "한테", "마저", "조차", "라도",
    "랑", "와", "과", "도", "은", "는", "이", "가", "을", "를", "로", "만", "의",
)

# 마커 앞에 붙는 필러(그 자체는 재료명이 아님) — "문어랑 성게 같이 넣어도"의 "같이" 등
_STOPWORDS = {"같이", "함께", "도", "돼", "될까", "괜찮아", "돼요"}


def _strip_josa(word: str) -> str:
    for josa in sorted(_JOSA_SUFFIXES, key=len, reverse=True):
        if word.endswith(josa) and len(word) > len(josa):
            return word[: -len(josa)]
    return word


def _extract_span(tokens: list[str], start: int, end: int) -> list[str]:
    """tokens[start:end] 구간에서 조사를 뗀 뒤 불용어를 제외한 후보 명사만 뽑는다.

    불용어 체크를 조사 제거 전/후 둘 다 한다 — "같이"는 그 자체가 불용어인데, 조사 제거
    로직이 "이"를 어미로 오인해서 "같"으로 잘못 잘라버리면 원래 불용어 검사를 피해가기
    때문(실측으로 발견, 2026-08-19).
    """
    result = []
    for tok in tokens[start:end]:
        raw = tok.rstrip("?!.,")
        if raw in _STOPWORDS:
            continue
        clean = _strip_josa(raw)
        if clean and clean not in _STOPWORDS:
            result.append(clean)
    return result


def extract_substitution_ingredients(utterance: str) -> tuple[list[str], str | None]:
    """"애호박 빼고 바지락 넣어도 괜찮아?" -> (["바지락"], "애호박").

    마커(넣어/바꿔/빼고 등) 어간이 나오는 토큰 직전 구간을, 그 마커가 요청인지 제외인지에
    따라 requested_ingredient/excluded_ingredient로 분류한다. 마커가 여러 개면 각각
    직전 미소비 구간만 취해서(last_index로 추적) 중복 소비를 막는다.
    """
    tokens = utterance.strip().split()
    requested: list[str] = []
    excluded: str | None = None
    last_index = -1

    for i, tok in enumerate(tokens):
        stem_tok = tok.rstrip("?!.,")
        if any(stem_tok.startswith(s) for s in _EXCLUDE_STEMS):
            span = _extract_span(tokens, last_index + 1, i)
            if span:
                excluded = span[-1]
            last_index = i
        elif any(stem_tok.startswith(s) for s in _REQUEST_STEMS):
            span = _extract_span(tokens, last_index + 1, i)
            requested.extend(span)
            last_index = i

    return requested, excluded
