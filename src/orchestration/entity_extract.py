"""자유발화에서 요리명을 뽑아내는 규칙 기반 v1.

`classify_intent()`는 의도만 분류하고 세부 정보(요리명)는 추출하지 않는다
(`handle_utterance()`의 docstring 참고) — 원래 app.py가 채워야 할 몫으로 남겨져 있던
부분이다. LLM은 런타임에서 못 쓰므로(1.5 원칙), 임베딩도 아닌 순수 문자열 연산(정규식/
토큰 분리)만 쓴다 — 응답시간에 영향 없음(마이크로초~밀리초 단위, STT/TTS 병목과 무관).

extract_dish_name(): "조회" 의도 — data/intent_examples/기준예문.csv의
"{요리명} 어떻게 만들어?" 고정 템플릿에 근거해 접미사를 잘라낸다.

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
