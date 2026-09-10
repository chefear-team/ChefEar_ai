"""자유발화에서 요리명 후보와 등록 의도를 뽑는 로컬 LLM 기반 추출기.

정규식으로 고정 문형("~어떻게 만들어")만 잘라내던 초기 방식은 문형 밖 표현을 놓쳤다.
이 모듈은 GPU에 직접 로드한 EXAONE-3.5-2.4B-Instruct(`llm/infer.py`)로 그 한계를 보완한다.
LLM 결과는 후보일 뿐이고 최종 요리명은 `recipe_search.extract_dish_name()`이 DB 실존 이름과
매칭해 결정한다(`docs/specs/llm_dish_name_extract.md`).
"""
from __future__ import annotations

import re

from llm.infer import generate_json

_PROMPT_TEMPLATE = """너는 한국어 요리 음성 비서의 일부다. 아래 사용자 발화에서 "요리명"과 "새 레시피를 등록하고 싶다는 의도"를 함께 판단해라.

규칙:
- 발화에 특정 요리 이름이 있으면 그 요리명만 뽑는다. 조사/어미/부가 표현은 제거한다.
- 요리명이 여러 단어로 이루어진 복합어면(예: "소고기미역국") 절대 일부만 자르지 말고 전체를 통째로 뽑는다.
- 발화에 요리명이 없거나(잡담, "다음"/"멈춰" 같은 진행 명령 등) 불확실하면 dish_name을 null로 답한다. 모르면 지어내지 말고 반드시 null로 답한다.
- 발화가 "새 레시피를 등록하고 싶다"는 의도를 명확히 담고 있으면(예: "등록해줘", "등록할래", "새로 등록하고 싶어") wants_register를 true로, 아니면 false로 답한다. 요리명을 물어보는 조회 발화("된장찌개 어떻게 만들어?")는 등록 의도가 아니다 — false로 답한다.
- 반드시 아래 JSON 형식으로만 답한다. 다른 말은 절대 덧붙이지 않는다.

형식: {{"dish_name": "<요리명>" 또는 null, "wants_register": true 또는 false}}

예시:
발화: "된장찌개어떻게만들어"
답: {{"dish_name": "된장찌개", "wants_register": false}}

발화: "소고기미역국레시피궁금해"
답: {{"dish_name": "소고기미역국", "wants_register": false}}

발화: "김치볶음밥레시피알려줘"
답: {{"dish_name": "김치볶음밥", "wants_register": false}}

발화: "다음단계로넘어가줘"
답: {{"dish_name": null, "wants_register": false}}

발화: "이거잠깐멈춰줘"
답: {{"dish_name": null, "wants_register": false}}

발화: "등록해줘"
답: {{"dish_name": null, "wants_register": true}}

발화: "새레시피등록하고싶어"
답: {{"dish_name": null, "wants_register": true}}

이제 아래 발화를 처리해라.
발화: "{utterance}"
답:"""


def extract_intent_llm(utterance: str) -> dict:
    """로컬 LLM 호출 한 번으로 "요리명"과 "등록하고 싶다는 의도"를 같이 뽑는다."""
    utterance = utterance.strip()
    if not utterance:
        return {"dish_name": None, "wants_register": False}

    utterance_for_llm = re.sub(r"\s+", "", utterance.rstrip("?!.,~ "))
    result = generate_json(_PROMPT_TEMPLATE.format(utterance=utterance_for_llm))
    if not result:
        return {"dish_name": None, "wants_register": False}

    dish_name = result.get("dish_name")
    dish_name = dish_name.strip() if isinstance(dish_name, str) and dish_name.strip() else None
    return {"dish_name": dish_name, "wants_register": result.get("wants_register") is True}


def extract_dish_name_llm(utterance: str) -> str | None:
    """extract_intent_llm()의 dish_name만 돌려준다 — 기존 호출부(app.py 등)와의 하위 호환용.

    서버 실패/timeout/형식 오류/불확실 응답이면 전부 None — 그럴듯한 요리명을 지어내지
    않는다(1.5 원칙과 같은 정직성, AC-02/AC-03). 호출부는 None을 "요리명 없음"으로
    그대로 처리하면 된다.
    """
    return extract_intent_llm(utterance)["dish_name"]
