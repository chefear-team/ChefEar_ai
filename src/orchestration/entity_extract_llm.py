"""자유발화에서 요리명을 뽑는 로컬 LLM 기반 경로 — `entity_extract.py`(정규식)와 별개.

`entity_extract.py`의 `extract_dish_name()`은 고정 접미사를 `rstrip`으로 잘라내는
방식이라 "위 문형 밖의 표현은 놓칠 수 있다"는 v1 한계가 파일 자체에 명시돼 있다
(`entity_extract.py:14`). 이 파일은 그 한계를 로컬 LLM(GPU 데스크탑에 직접 로드한
EXAONE-3.5-2.4B-Instruct, `llm/infer.py`)으로 보완한다. `entity_extract.py` 자체는
건드리지 않는다 — `app.py`의 호출 지점만 이 함수로 바꿔서 실제 서비스 흐름에 연결한다
(`docs/specs/llm_dish_name_extract.md` 참고).
"""
from __future__ import annotations

import re

from llm.infer import generate_json

# few-shot 두 개(요리명 있음/없음)로 출력 형식을 고정한다 — 모델이 JSON 밖에 다른 말을
#덧붙이면 client.py의 json.loads()가 실패해서 안전하게 None으로 처리된다(EC-03).
#
# 발화 예시에 띄어쓰기를 다 뺀 것은 의도적이다(2026-08-20) — 실측에서 "소고기미역국
# 레시피 궁금해"처럼 복합 요리명에 공백이 있으면 LLM이 "소고기"를 버리고 "미역국"만
# 뽑는 경우가 있었다. 실제 입력도 extract_dish_name_llm()에서 띄어쓰기를 다 제거한
# 뒤에 넣으므로, few-shot 예시도 같은 형태(공백 없음)로 맞춰야 패턴이 일치한다.
_PROMPT_TEMPLATE = """너는 한국어 요리 음성 비서의 일부다. 아래 사용자 발화에서 "요리명"과 "새 레시피를 등록하고 싶다는 의도"를 함께 판단해라.

규칙:
- 발화에 특정 요리 이름이 있으면 그 요리명만 뽑는다. 조사/어미/부가 표현은 제거한다.
- 요리명이 여러 단어로 이루어진 복합어면(예: "소고기미역국") 절대 일부만 자르지 말고 전체를 통째로 뽑는다.
- 발화에 요리명이 없거나(잡담, "다음"/"멈춰" 같은 진행 명령 등) 불확실하면 dish_name을 null로 답한다. 모르면 지어내지 말고 반드시 null로 답한다.
- 발화가 "새 레시피를 등록하고 싶다"는 의도를 명확히 담고 있으면(예: "등록해줘", "등록할래", "새로 등록하고 싶어") wants_register를 true로, 아니면 false로 답한다. 요리명을 물어보는 조회 발화("된장찌개 어떻게 만들어?")는 등록 의도가 아니다 — false로 답한다.
- 반드시 아래 JSON 형식으로만 답한다. 다른 말은 절대 덧붙이지 않는다.

형식: {{"dish_name": "<요리명>" 또는 null, "wants_register": true 또는 false}}

예시:
발화: "된장찌개어떻게만들어?"
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
    """로컬 LLM 호출 한 번으로 "요리명"과 "등록하고 싶다는 의도"를 같이 뽑는다.

    2026-08-22 추가 — classify_intent()(임베딩 유사도)가 "등록" 같은 짧은 단일 발화를
    "진행"/"이전"과 헷갈려서 margin 미충족으로 미분류 처리하는 사례가 실측 확인됐다
    (`data/intent_examples/기준예문.csv` 보강으로 그 구체 사례는 해결했지만, 임베딩
    분류기가 커버 못하는 표현은 여전히 나올 수 있음). extract_dish_name_llm()이
    이미 매 발화마다 LLM을 호출하고 있으므로, 새 LLM 호출을 늘리는 대신 같은
    프롬프트/응답에 wants_register 필드 하나만 얹어서 재사용한다.

    반환값: {"dish_name": str | None, "wants_register": bool}. LLM 실패/timeout/형식
    오류면 둘 다 안전한 기본값({"dish_name": None, "wants_register": False})으로
    돌아간다 — 그럴듯하게 지어내지 않는다(1.5 원칙과 같은 정직성, AC-02/AC-03).

    LLM에 넘기기 전 띄어쓰기를 전부 제거한다(2026-08-20) — "소고기미역국" 같은 복합
    요리명이 STT 결과에서 "소고기 미역국"처럼 공백이 섞여 나오면, 그 공백을 단어
    경계로 오인해서 LLM이 뒷부분만("미역국") 뽑는 문제가 실측으로 확인됐다. 화면
    표시/로그용 원문(utterance)은 그대로 두고, LLM에 넣는 사본에만 적용한다
    (`tts/pronunciation.py`의 apply_pronunciation_fixes()와 같은 "원문은 안 건드리고
    모델에 넣는 사본만 가공" 패턴).
    """
    utterance = utterance.strip()
    if not utterance:
        return {"dish_name": None, "wants_register": False}

    utterance_for_llm = re.sub(r"\s+", "", utterance)
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
