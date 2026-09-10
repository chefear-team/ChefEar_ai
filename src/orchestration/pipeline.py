"""7.1.1/7.4 — 조리순서 조회 및 진행 단계 상태 전이.

이 파일은 "레시피 하나를 골랐다"는 전제 아래, 그 레시피를 실제로 1단계씩
안내하는 흐름을 담당한다. 세션 상태(지금 몇 단계인지 등)는 호출하는 쪽이
넘겨주는 dict-like 객체(실제 앱에서는 st.session_state)에 저장한다.
"""
from __future__ import annotations

from orchestration.db import get_client
from orchestration.intent_classifier import FALLBACK_NEED_CONTEXT, classify_intent
from orchestration.recipe_search import (
    extract_dish_name,
    find_dish_name_ignoring_repetition,
    find_dish_name_ignoring_spaces,
    find_dish_name_stripping_query_suffix,
    find_more_specific_containing_name,
    select_standard_recipe,
)
from orchestration.registration import register_recipe

NOT_AVAILABLE_MESSAGE = "죄송해요, 이 레시피는 아직 등록되어 있지 않아요."
DISH_NOT_FOUND_MESSAGE = "등록되지 않은 레시피에요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요."
PENDING_MESSAGE = "등록 심사 중인 레시피예요. 승인되면 바로 조회할 수 있어요."


def get_precomputed_steps(recipe_id: str, client=None) -> dict:
    """레시피 하나의 조리순서 "전체 목록"을 한 번에 가져온다(7.4). AC-12/AC-13.

    "precomputed"(미리 계산된)라는 이름이 붙은 이유: 이 프로젝트는 조리순서를
    그때그때 AI가 만들어내지 않고, 작업1에서 미리 DB에 다 넣어둔 실데이터를
    그냥 읽기만 한다(1.5 원칙 — LLM 실시간 생성 금지). 그래서 함수가 하는 일은
    사실 단순한 SELECT 하나뿐이다.

    text에 담긴 값은 [TERM:용어] 태그가 그대로 남아있는 원본이다 — 여기서
    resolve하지 않는다. 호출부(ui/screens/cooking.py)가 TTS로 읽을 땐
    resolve_for_tts(), 화면에 자막으로 낼 땐 resolve_for_display()를 각각
    거쳐서 써야 한다(term_dict.py 참고).
    """
    client = client or get_client()
    res = (
        client.table("recipe_steps")
        .select("*")
        .eq("recipe_id", recipe_id)
        .order("step_number")  # 1단계, 2단계, 3단계 순서로 정렬해서 받는다
        .execute()
    )
    if not res.data:
        return {"available": False, "ingredients_only": False, "message": NOT_AVAILABLE_MESSAGE}

    return {
        "available": True,
        "steps": [{"step_number": r["step_number"], "text": r["step_text"]} for r in res.data],
        "source": res.data[0]["source"],  # 모든 단계가 같은 레시피 소속이라 source도 동일함
    }


def get_current_step(recipe_id: str, step_number: int, client=None) -> dict | None:
    """레시피의 "딱 한 단계"만 콕 집어서 가져온다. get_precomputed_steps()가
    "전체 목록"을 가져오는 것과 달리, 이건 "지금 몇 단계인지"가 이미 정해진
    상태에서 그 단계 텍스트만 필요할 때 쓴다(advance_step()이 이 함수를 부른다).

    text는 여기서도 마찬가지로 [TERM:용어] 태그가 남은 원본 그대로 반환한다 —
    resolve는 항상 호출부(cooking.py)의 몫이다.
    """
    client = client or get_client()
    res = (
        client.table("recipe_steps")
        .select("*")
        .eq("recipe_id", recipe_id)
        .eq("step_number", step_number)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    return {"step_number": row["step_number"], "text": row["step_text"], "source": row["source"]}


def advance_step(
    session: dict, direction: str, client=None, steps: list[dict] | None = None
) -> dict:
    """"다음"/"다시"/"이전" 발화 하나를 받아서 진행 단계를 옮긴다(7.1.1 상태 전이표)."""
    recipe_id = session["current_recipe_id"]
    step_number = session.get("step_number", 1)  # 아직 한 번도 안 정해졌으면 1단계부터
    no_previous = False

    if direction == "다음":
        step_number += 1
    elif direction == "다시":
        pass  # step_number를 안 바꾸는 것 자체가 "그대로 다시 안내"를 의미함
    elif direction == "이전":
        if step_number <= 1:
            no_previous = True  # AC-08: 1단계 유지 + 이전 단계 없음 안내
        else:
            step_number -= 1
    else:
        raise ValueError(f"알 수 없는 방향: {direction}")

    session["step_number"] = step_number  # 다음 호출을 위해 세션에 반영
    step = None
    if steps:
        step = next((s for s in steps if s.get("step_number") == step_number), None)
    if step is None:
        step = get_current_step(recipe_id, step_number, client=client)
    return {"step_number": step_number, "step": step, "no_previous": no_previous}


def manual_fallback(session: dict, button: str, client=None, steps: list[dict] | None = None) -> dict:
    """화면의 [이전][다시][다음] 수동 버튼 처리(FR-16/AC-09).

    음성 인식이 실패했을 때(혹은 그냥 손으로 누르고 싶을 때)를 위한 대체
    경로다. classify_intent()의 임베딩 유사도 판정을 완전히 건너뛰고
    advance_step()을 바로 호출한다 — 버튼은 이미 사용자의 의도가 100% 명확하니
    "얼마나 비슷한 문장인가"를 판단할 필요 자체가 없기 때문이다.
    """
    if button not in ("이전", "다시", "다음"):
        raise ValueError(f"알 수 없는 버튼: {button}")
    return advance_step(session, button, client=client, steps=steps)


_DIRECTION_BY_INTENT = {"진행": "다음", "재청취": "다시", "이전": "이전"}


def handle_utterance(
    session: dict,
    utterance: str,
    *,
    dish_name: str | None = None,
    registration_step: str | None = None,
    registration_value=None,
    client=None,
    steps: list[dict] | None = None,
    owner_id: str | None = None,
) -> dict:
    """STT 결과 텍스트 하나를 받아 의도별로 라우팅하는 최종 조립 함수(7.1 진입점)."""
    client = client or get_client()
    context_recipe_id = session.get("current_recipe_id")
    result = classify_intent(utterance, context_recipe_id=context_recipe_id)
    intent = result["intent"]

    if intent == "미분류":
        return {"intent": intent, "message": result["fallback_message"]}

    if intent in _DIRECTION_BY_INTENT:
        if context_recipe_id is None:
            return {"intent": "미분류", "message": FALLBACK_NEED_CONTEXT}
        step_result = advance_step(session, _DIRECTION_BY_INTENT[intent], client=client, steps=steps)
        return {"intent": intent, **step_result}

    if intent == "조회":
        # dish_name을 호출부가 안 넘겨주면(None) 발화 텍스트 자체에서 뽑아낸다
        # (extract_dish_name, recipe_search.py) — 넘겨주면 그 값을 그대로 우선한다
        # (기존 테스트/향후 UI가 이미 알고 있는 요리명을 직접 넘기는 경로도 계속 지원).
        resolved_dish_name = dish_name or extract_dish_name(utterance, client=client)
        if resolved_dish_name is None:
            return {"intent": intent, "message": DISH_NOT_FOUND_MESSAGE}
        found = select_standard_recipe(resolved_dish_name, client=client, owner_id=owner_id)
        if found is None:
            space_corrected = find_dish_name_ignoring_spaces(resolved_dish_name, client=client)
            if space_corrected and space_corrected != resolved_dish_name:
                found = select_standard_recipe(space_corrected, client=client, owner_id=owner_id)
        if found is None:
            repetition_corrected = find_dish_name_ignoring_repetition(resolved_dish_name, client=client)
            if repetition_corrected and repetition_corrected != resolved_dish_name:
                found = select_standard_recipe(repetition_corrected, client=client, owner_id=owner_id)
        if found is None:
            suffix_corrected = find_dish_name_stripping_query_suffix(resolved_dish_name, client=client)
            if suffix_corrected and suffix_corrected != resolved_dish_name:
                found = select_standard_recipe(suffix_corrected, client=client, owner_id=owner_id)
        if found is None:
            return {"intent": intent, "message": DISH_NOT_FOUND_MESSAGE}
        if found.get("pending"):
            return {"intent": intent, "message": PENDING_MESSAGE}
        more_specific = find_more_specific_containing_name(found["dish_name"], utterance, client=client)
        if more_specific:
            upgraded = select_standard_recipe(more_specific, client=client, owner_id=owner_id)
            if upgraded is not None and not upgraded.get("pending"):
                found = upgraded
            elif upgraded is not None and upgraded.get("pending"):
                return {"intent": intent, "message": PENDING_MESSAGE}
        session["current_recipe_id"] = found["recipe_id"]
        session["step_number"] = 1
        return {"intent": intent, **found}

    if intent == "등록":
        if registration_step is None:
            raise ValueError("등록 의도는 registration_step이 필요함")
        reg_result = register_recipe(
            session, registration_step, registration_value, client=client, owner_id=owner_id
        )
        return {"intent": intent, **reg_result}

    raise ValueError(f"알 수 없는 intent: {intent}")
