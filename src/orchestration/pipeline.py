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
        # recipe_steps에 이 recipe_id로 된 행이 하나도 없음 = 등록 안 된 레시피.
        # AC-13: 없으면 그냥 정직하게 "없다"고 말한다(1.5 원칙, 지어내지 않음).
        # 2026-09-01 — 60,282건 API 데이터를 걷어내고 큐레이션된 500개 표준
        # 레시피로 교체한 뒤로는, 이 분기가 걸리는 경우는 사실상 "사용자가
        # 등록한 지 얼마 안 돼 아직 조리순서가 없는" user_custom 레시피뿐이다
        # (500개는 recipe_steps까지 이미 다 같이 적재됐음 — load_500_recipes.py
        # 참고). 옛날처럼 "표준 데이터인데 조리순서가 없는" 흔한 경우는 더 이상
        # 없다.
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
    """"다음"/"다시"/"이전" 발화 하나를 받아서 진행 단계를 옮긴다(7.1.1 상태 전이표).

    규칙은 딱 세 가지뿐이라 간단하다.
      다음 -> step_number를 1 늘림 (다음 단계로)
      다시 -> step_number 그대로 (같은 단계를 한 번 더 안내)
      이전 -> step_number를 1 줄임, 단 1단계에서 "이전"을 누르면 더 줄일 데가
              없으니 1단계를 유지하고 "이전 단계 없음"이라고 알려줌(AC-08)

    steps: 호출부(ui/dispatch.py)가 레시피 조회 시 이미 한 번에 다 받아둔 전체
    조리순서 목록(ui/recipe_view.py::refresh_recipe_view()가 채우는
    st.session_state.recipe_view["steps"]). 주어지면 여기서 해당 step_number를
    찾아 쓰고 get_current_step()의 Supabase 왕복을 건너뛴다 — 2026-08-27 실측
    리포트("'다시'라고 말할 때마다 뭔가 다시 조회/생성하는 느낌이다") 원인 확인:
    음성 파일 자체는 이미 speak()가 경로 존재 여부로 재합성을 건너뛰고 있었지만,
    "다시"는 step_number가 그대로인데도 이 함수가 매번 DB에 새로 물어보고
    있었다 — 그 불필요한 네트워크 왕복이 체감 지연의 실제 원인이었다. steps에
    해당 단계가 없으면(호출부가 안 넘겼거나 목록이 비정상인 경우) 기존처럼
    DB에서 안전하게 가져온다 — steps 인자를 안 넘기는 기존 호출부/테스트는
    동작이 전혀 안 바뀐다.
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
) -> dict:
    """STT 결과 텍스트 하나를 받아 의도별로 라우팅하는 최종 조립 함수(7.1 진입점).

    app.py가 직접 호출할 곳은 여기 하나뿐이다: STT 텍스트를 넣으면
    classify_intent()로 의도를 가리고, 의도에 맞는 기존 함수(advance_step/
    select_standard_recipe/register_recipe)로 라우팅해서 TTS에 넘길 응답을
    만들어 돌려준다.

    classify_intent()는 "무슨 의도인지"만 분류하고 "무슨 요리인지" 같은 세부
    정보(entity)는 추출하지 않는다. 조회 의도는 예외로, dish_name을 직접
    안 넘겨주면(None) extract_dish_name()이 utterance 자체에서 요리명을 찾아준다
    (완전일치→부분일치→편집거리 3단계, recipe_search.py 참고) — 그래서 발화
    텍스트 하나만 있어도 조회가 끝까지 된다. 등록은 아직 발화에서 순서 같은
    걸 뽑아내는 로직이 없어서, registration_step/registration_value를 여전히
    호출부가 직접 넘겨줘야 한다 — app.py가 UI 입력이나 별도 로직으로 채워서
    호출하는 구조다.

    steps: "진행"/"재청취"/"이전" 의도일 때만 advance_step()으로 그대로
    전달한다 — 넘기면 그 함수가 DB 재조회 없이 여기서 찾아 쓴다(advance_step()
    문서 참고).
    """
    client = client or get_client()
    context_recipe_id = session.get("current_recipe_id")
    result = classify_intent(utterance, context_recipe_id=context_recipe_id)
    intent = result["intent"]

    if intent == "미분류":
        return {"intent": intent, "message": result["fallback_message"]}

    if intent in _DIRECTION_BY_INTENT:
        # classify_intent()는 "다음"/"이전" 같은 발화를 context_recipe_id 유무와
        # 무관하게 진행/재청취/이전으로 분류한다(AC-01 스펙). 그래서 아직 아무
        # 레시피도 고른 적 없는 상태(context_recipe_id 없음)에서 "다음"이 오면
        # 여기서 걸러야 한다 — 안 그러면 advance_step()이 session에서
        # current_recipe_id를 못 찾아 KeyError로 죽는다(실측: STT/TTS 텍스트
        # 테스트 화면에서 첫 발화로 "다음"을 보냈다가 실제로 재현됨, 2026-08-20).
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
        found = select_standard_recipe(resolved_dish_name, client=client)
        # 2026-08-26 — dish_name(로컬 LLM 추측)이 완전일치 실패하면 extract_dish_name()으로
        # 발화 원문을 한 번 더 보정 시도하는 안전망을 잠깐 넣었다가 되돌렸다. "우리엄마가
        # 만든 된장찌개."처럼 DB 문자열과 토씨 하나 다른 진짜 매칭 실패는 구해줬지만,
        # extract_dish_name()의 "후보 중 가장 긴 것을 채택"(길이만 보고 매칭 신뢰도는
        # 안 봄) 결함이 이 경로로 새로 노출돼서, "초코민트 된장찌개"(존재하지 않는 요리)
        # 같은 발화가 편집거리 0.7대의 약한 매칭으로 "토마토된장찌개"(엉뚱한 실제 요리)에
        # 매칭되는 더 나쁜 문제가 실측 확인됐다 — 정직하게 "없다"고 답해야 할 발화가
        # 그럴듯한 다른 요리로 둔갑하는 건 1.5 원칙 위반이라 더 심각하다고 판단해 되돌림.
        #
        # 2026-08-26 — 위와는 다른, 안전하게 확인된 안전망 하나만 별도로 추가한다.
        # "실제 DB에 등록한 '고등어 라테'가 조회 안 됨" 재현/원인 확정: extract_intent_llm()
        # 이 LLM에 넘기기 전 띄어쓰기를 전부 지우는 전처리 때문에(그쪽 문서 참고) dish_name이
        # 종종 공백 없이("고등어라테") 온다 — DB엔 원문 그대로("고등어 라테") 저장돼 있어서
        # 완전일치가 실패했다. find_dish_name_ignoring_spaces()는 편집거리 유사도가 아니라
        # "공백만 빼면 내용이 정확히 같은가"만 보므로(recipe_search.py 문서 참고), 위에서
        # 되돌린 것과 달리 다른 요리로 새는 오매칭 위험이 구조적으로 없다.
        if found is None:
            space_corrected = find_dish_name_ignoring_spaces(resolved_dish_name, client=client)
            if space_corrected and space_corrected != resolved_dish_name:
                found = select_standard_recipe(space_corrected, client=client)
        if found is None:
            # 2026-08-26 추가 — 위 공백 안전망과 나란히, LLM이 준 dish_name이 STT
            # 반복 아티팩트를 그대로 옮긴 경우(예: "된장찌장찌개") 대응. fuzzy 매칭이
            # 아니라 "반복만 접으면 정확히 같은가"만 보므로 오매칭 위험 없음
            # (find_dish_name_ignoring_repetition() 문서 참고).
            repetition_corrected = find_dish_name_ignoring_repetition(resolved_dish_name, client=client)
            if repetition_corrected and repetition_corrected != resolved_dish_name:
                found = select_standard_recipe(repetition_corrected, client=client)
        if found is None:
            # 2026-08-27 추가 — 위 두 안전망과 나란히, LLM이 "레시피"류 질의 접미사를
            # dish_name에서 못 떼고 그대로 돌려준 경우(예: "멸치볶음레시피") 대응.
            # 편집거리/유사도 전혀 없이 "접미사를 뗀 결과가 DB에 글자 그대로 있는가"만
            # 보므로(find_dish_name_stripping_query_suffix() 문서 참고), 위에서 되돌린
            # fuzzy 매칭과 달리 다른 요리로 새는 오매칭 위험이 구조적으로 없다 — 사용자가
            # 실제로 등록한 적 없는 새 요리("OO레시피"라는 이름 자체가 그 사람만의 것일
            # 수도 있음)라면 접미사를 떼도 DB에 없으니 그대로 "없다"고 정직하게 답한다.
            suffix_corrected = find_dish_name_stripping_query_suffix(resolved_dish_name, client=client)
            if suffix_corrected and suffix_corrected != resolved_dish_name:
                found = select_standard_recipe(suffix_corrected, client=client)
        if found is None:
            return {"intent": intent, "message": DISH_NOT_FOUND_MESSAGE}
        if found.get("pending"):
            # 2026-08-27 추가 — 관리자 승인 대기 중인 user_custom 레시피
            # (recipes.approved == 'N'). select_standard_recipe()가 승인된 후보가
            # 하나도 없을 때 이 신호를 돌려준다(recipe_search.py 문서 참고) —
            # "아예 없음"과 구분해서 안내한다. {"pending": True}에는 "dish_name"이
            # 없으므로 아래 승격 로직보다 반드시 먼저 걸러야 한다(실측: KeyError).
            return {"intent": intent, "message": PENDING_MESSAGE}
        # 2026-08-27 추가 — 실측 리포트: "10분잡채"(DB)를 로컬 LLM이 "잡채"(이것도
        # DB에 있는 별개 요리)로만 추측해서 짧은 쪽이 먼저 성공해버리면, 위 안전망들은
        # found가 이미 None이 아니라서 전혀 발동하지 않는다 — "잡채"도 정직하게
        # 존재하는 매칭이라 실패로 안 잡힘. 발화 원문에 이미 찾은 이름을 포함하는 더
        # 구체적인 다른 DB 이름이 문자 그대로(공백만 무시) 들어있으면 그쪽으로
        # 승격한다(recipe_search.py::find_more_specific_containing_name() 문서 참고,
        # 편집거리 전혀 안 써서 위에서 되돌린 fuzzy 매칭 문제와는 오매칭 위험 성격이
        # 다름).
        more_specific = find_more_specific_containing_name(found["dish_name"], utterance, client=client)
        if more_specific:
            upgraded = select_standard_recipe(more_specific, client=client)
            if upgraded is not None and not upgraded.get("pending"):
                found = upgraded
            elif upgraded is not None and upgraded.get("pending"):
                # 2026-08-28 실측 리포트 — "10분 잡채 레시피 알려줘"라고 했는데 승인된
                # 별개 요리 "잡채"가 나옴. 사용자가 발화에 직접 넣은 더 구체적인 이름
                # ("10분잡채")이 DB에 있지만 승인 대기 중이면, 덜 구체적인 다른 승인
                # 레시피로 조용히 바꿔치기하지 말고 "심사 중"이라고 정직하게 안내한다
                # (1.5 원칙 — 지어내지 않음). 이 이름은 fuzzy가 아니라 발화에 글자 그대로
                # 들어있는 경우만 잡히므로(find_more_specific_containing_name() 문서 참고)
                # "사용자가 그 요리를 지목했다"가 확실하다.
                return {"intent": intent, "message": PENDING_MESSAGE}
        session["current_recipe_id"] = found["recipe_id"]
        session["step_number"] = 1
        return {"intent": intent, **found}

    if intent == "등록":
        if registration_step is None:
            raise ValueError("등록 의도는 registration_step이 필요함")
        reg_result = register_recipe(session, registration_step, registration_value, client=client)
        return {"intent": intent, **reg_result}

    raise ValueError(f"알 수 없는 intent: {intent}")
