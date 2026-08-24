"""7.1.1/7.4 — 조리순서 조회 및 진행 단계 상태 전이.

이 파일은 "레시피 하나를 골랐다"는 전제 아래, 그 레시피를 실제로 1단계씩
안내하는 흐름을 담당한다. 세션 상태(지금 몇 단계인지 등)는 호출하는 쪽이
넘겨주는 dict-like 객체(실제 앱에서는 st.session_state)에 저장한다 —
substitution.py 맨 위 설명에 있는 "세션이 뭔지" 부분과 같은 개념이다.
"""
from __future__ import annotations

from orchestration.db import get_client
from orchestration.intent_classifier import FALLBACK_NEED_CONTEXT, classify_intent
from orchestration.recipe_search import extract_dish_name, search_variant_recipe, select_standard_recipe
from orchestration.registration import register_recipe
from orchestration.substitution import apply_substitution, cancel_substitution

NOT_AVAILABLE_MESSAGE = "죄송해요, 이 레시피는 아직 등록되어 있지 않아요."
DISH_NOT_FOUND_MESSAGE = "죄송해요, 그 요리는 아직 없어요."
NO_ACTIVE_CORRECTION_MESSAGE = "지금은 정정할 내용이 없어요."


def get_precomputed_steps(recipe_id: str, client=None) -> dict:
    """레시피 하나의 조리순서 "전체 목록"을 한 번에 가져온다(7.4). AC-12/AC-13.

    "precomputed"(미리 계산된)라는 이름이 붙은 이유: 이 프로젝트는 조리순서를
    그때그때 AI가 만들어내지 않고, 작업1에서 미리 DB에 다 넣어둔 실데이터를
    그냥 읽기만 한다(1.5 원칙 — LLM 실시간 생성 금지). 그래서 함수가 하는 일은
    사실 단순한 SELECT 하나뿐이다.
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
        # recipe_steps에 이 recipe_id로 된 행이 하나도 없음 = 등록 안 된 레시피.
        # AC-13: 없으면 그냥 정직하게 "없다"고 말한다(1.5 원칙, 지어내지 않음).
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


def advance_step(session: dict, direction: str, client=None) -> dict:
    """"다음"/"다시"/"이전" 발화 하나를 받아서 진행 단계를 옮긴다(7.1.1 상태 전이표).

    규칙은 딱 세 가지뿐이라 간단하다.
      다음 -> step_number를 1 늘림 (다음 단계로)
      다시 -> step_number 그대로 (같은 단계를 한 번 더 안내)
      이전 -> step_number를 1 줄임, 단 1단계에서 "이전"을 누르면 더 줄일 데가
              없으니 1단계를 유지하고 "이전 단계 없음"이라고 알려줌(AC-08)

    재료 대체로 레시피 자체가 바뀐 뒤에도(substitution.py의 apply_substitution()이
    session["current_recipe_id"]를 바꿔놓음) 이 함수는 그냥 session에 있는
    "현재" recipe_id/step_number를 기준으로 그대로 동작한다 — 그래서 재료를
    바꾼 뒤 "다음"이라고 말해도 자연스럽게 이어진다(문서 7.1.1 마지막 항목).
    """
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
    step = get_current_step(recipe_id, step_number, client=client)
    return {"step_number": step_number, "step": step, "no_previous": no_previous}


def manual_fallback(session: dict, button: str, client=None) -> dict:
    """화면의 [이전][다시][다음] 수동 버튼 처리(FR-16/AC-09).

    음성 인식이 실패했을 때(혹은 그냥 손으로 누르고 싶을 때)를 위한 대체
    경로다. classify_intent()의 임베딩 유사도 판정을 완전히 건너뛰고
    advance_step()을 바로 호출한다 — 버튼은 이미 사용자의 의도가 100% 명확하니
    "얼마나 비슷한 문장인가"를 판단할 필요 자체가 없기 때문이다.
    """
    if button not in ("이전", "다시", "다음"):
        raise ValueError(f"알 수 없는 버튼: {button}")
    return advance_step(session, button, client=client)


_DIRECTION_BY_INTENT = {"진행": "다음", "재청취": "다시", "이전": "이전"}


def handle_utterance(
    session: dict,
    utterance: str,
    *,
    dish_name: str | None = None,
    requested_ingredient: list[str] | None = None,
    excluded_ingredient: str | None = None,
    registration_step: str | None = None,
    registration_value=None,
    client=None,
) -> dict:
    """STT 결과 텍스트 하나를 받아 의도별로 라우팅하는 최종 조립 함수(7.1 진입점).

    app.py가 직접 호출할 곳은 여기 하나뿐이다: STT 텍스트를 넣으면
    classify_intent()로 의도를 가리고, 의도에 맞는 기존 함수(advance_step/
    search_variant_recipe/select_standard_recipe/register_recipe/
    cancel_substitution)로 라우팅해서 TTS에 넘길 응답을 만들어 돌려준다.

    classify_intent()는 "무슨 의도인지"만 분류하고 "무슨 요리/재료인지" 같은
    세부 정보(entity)는 추출하지 않는다. 조회 의도는 예외로, dish_name을 직접
    안 넘겨주면(None) extract_dish_name()이 utterance 자체에서 요리명을 찾아준다
    (완전일치→부분일치→편집거리 3단계, recipe_search.py 참고) — 그래서 발화
    텍스트 하나만 있어도 조회가 끝까지 된다. 나머지(재료대체/등록/정정)는 아직
    발화에서 재료명·순서 같은 걸 뽑아내는 로직이 없어서, requested_ingredient/
    excluded_ingredient/registration_step/registration_value를 여전히 호출부가
    직접 넘겨줘야 한다 — app.py가 UI 입력이나 별도 로직으로 채워서 호출하는 구조다.
    """
    client = client or get_client()
    context_recipe_id = session.get("current_recipe_id")
    result = classify_intent(utterance, context_recipe_id=context_recipe_id)
    intent = result["intent"]

    if intent == "미분류":
        return {"intent": intent, "message": result["fallback_message"]}

    if intent in _DIRECTION_BY_INTENT:
        # classify_intent()는 "다음"/"이전" 같은 발화를 context_recipe_id 유무와
        # 무관하게 진행/재청취/이전으로 분류한다(AC-01 스펙, EC-05는 재료대체에만
        # 적용됨). 그래서 아직 아무 레시피도 고른 적 없는 상태(context_recipe_id
        # 없음)에서 "다음"이 오면 여기서 걸러야 한다 — 안 그러면 advance_step()이
        # session에서 current_recipe_id를 못 찾아 KeyError로 죽는다(실측: STT/TTS
        # 텍스트 테스트 화면에서 첫 발화로 "다음"을 보냈다가 실제로 재현됨,
        # 2026-08-20). 재료대체의 EC-05와 같은 메시지로 정직하게 되묻는다.
        if context_recipe_id is None:
            return {"intent": "미분류", "message": FALLBACK_NEED_CONTEXT}
        step_result = advance_step(session, _DIRECTION_BY_INTENT[intent], client=client)
        return {"intent": intent, **step_result}

    if intent == "취소":
        return {"intent": intent, **cancel_substitution(session, client=client)}

    if intent == "재료대체":
        match = search_variant_recipe(
            context_recipe_id, requested_ingredient or [], excluded_ingredient, client=client
        )
        if match["match_type"] == "none":
            return {"intent": intent, "match_type": "none", "message": match["message"]}
        apply_substitution(session, match)
        return {"intent": intent, **match}

    if intent == "조회":
        # dish_name을 호출부가 안 넘겨주면(None) 발화 텍스트 자체에서 뽑아낸다
        # (extract_dish_name, recipe_search.py) — 넘겨주면 그 값을 그대로 우선한다
        # (기존 테스트/향후 UI가 이미 알고 있는 요리명을 직접 넘기는 경로도 계속 지원).
        resolved_dish_name = dish_name or extract_dish_name(utterance, client=client)
        if resolved_dish_name is None:
            return {"intent": intent, "message": DISH_NOT_FOUND_MESSAGE}
        found = select_standard_recipe(resolved_dish_name, owner_id=session.get("owner_id"), client=client)
        if found is None:
            return {"intent": intent, "message": DISH_NOT_FOUND_MESSAGE}
        session["current_recipe_id"] = found["recipe_id"]
        session["step_number"] = 1
        session["previous_recipe_id"] = None
        return {"intent": intent, **found}

    if intent in ("등록", "정정"):
        step = "correct_ingredient" if intent == "정정" else registration_step
        # register_recipe()는 session["registration"]이 없는 상태에서 dish_name이
        # 아닌 step으로 불리면 ValueError를 던진다(모듈 자체의 방어 로직). "정정"
        # 의도가 등록 중이 아닐 때 나오면(오분류 등) 서비스가 죽는 대신 정직하게
        # "정정할 게 없다"고 안내한다(1.5 원칙).
        if step is None:
            raise ValueError("등록 의도는 registration_step이 필요함")
        try:
            reg_result = register_recipe(session, step, registration_value, client=client)
        except ValueError:
            if intent == "정정":
                return {"intent": intent, "message": NO_ACTIVE_CORRECTION_MESSAGE}
            raise
        return {"intent": intent, **reg_result}

    raise ValueError(f"알 수 없는 intent: {intent}")
