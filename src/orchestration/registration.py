"""7.5 — register_recipe()(다단계 세션형)/save_recipe(). FR-06/EC-14~17/AC-06.

## 왜 함수가 하나가 아니라 두 개(register_recipe / save_recipe)인가

신규 레시피 등록은 한 번의 대화로 끝나지 않는다. "무슨 요리야?" -> "된장찌개요"
-> "재료는?" -> "두부, 감자요" -> "재료를 다시 읽어드릴게요: 두부, 감자.
맞나요?" -> "응" -> "순서는?" -> ... 이렇게 여러 번 왔다갔다 하는 대화(세션)를
거친 뒤에야 마지막에 딱 한 번 DB에 저장된다.

그래서 이 파일을 두 층으로 나눴다.
  - register_recipe(): "지금 대화가 어디까지 왔는지"를 세션에 계속 쌓아두는
    역할. 사용자가 뭐라고 말할 때마다 한 번씩 호출된다. DB에는 아직 아무것도
    안 쓴다.
  - save_recipe(): 사용자가 최종 확인("이대로 저장할까요?" -> "응")까지
    끝냈을 때 딱 한 번, 실제로 DB에 쓰는 역할. register_recipe()가 마지막에
    이 함수를 대신 호출해준다.

이렇게 나눠두면 save_recipe()만 따로 떼서 "그냥 재료·순서가 이미 다 준비된
레시피 하나를 저장하고 싶을 때"도 재사용할 수 있다(실제로 tests/test_registration.py의
EC-17 테스트가 그렇게 save_recipe()만 직접 부른다).
"""
from __future__ import annotations

from orchestration.db import get_client


def _ingredient_summary(ingredients: list[str]) -> str:
    """재료 확인 체크포인트에서 사용자에게 읽어줄 문장을 만든다(FR-06)."""
    return "재료를 확인할게요: " + ", ".join(ingredients) + ". 맞나요?"


def _final_summary(ingredients: list[str], instructions: list[str]) -> str:
    """최종 확인 체크포인트에서 재료+순서를 전부 읽어줄 문장을 만든다(FR-06)."""
    steps_text = " ".join(f"{i}. {t}" for i, t in enumerate(instructions, start=1))
    return "재료와 순서를 확인할게요. 재료: " + ", ".join(ingredients) + f". 순서: {steps_text} 이대로 저장할까요?"


def register_recipe(session: dict, step: str, value=None, client=None) -> dict:
    """등록 대화 한 턴을 처리한다. step 값에 따라 하는 일이 완전히 달라지는
    "상태 기계(state machine)" 형태의 함수다 — 지금 세션이 어느 단계에
    있느냐에 따라 같은 함수를 다르게 호출해가며 쓴다.

    step의 종류:
      "dish_name"        : 등록 시작, 요리명 받기
      "ingredients"       : 재료 목록 받기 (여러 턴에 나눠 말해도 계속 누적됨)
      "correct_ingredient": 재료 확인 중 사용자가 정정 요청("문어 말고 낙지야")
      "instructions"      : 조리 순서 받기 (역시 여러 턴 누적 가능)
      "confirm"           : 최종 확인 완료 -> 진짜로 저장
      "abort"             : 등록 중간에 사용자가 그만두겠다고 함
    """
    if step == "dish_name":
        # 등록의 첫 턴. 이전에 진행 중이던 등록 정보가 있었더라도 새로 시작하면
        # 덮어쓴다(요리명, 재료, 순서를 담을 빈 상자를 새로 만드는 것).
        session["registration"] = {"dish_name": value, "ingredients": [], "instructions": []}
        return {"prompt": f"{value}에 들어가는 재료를 알려주세요."}

    # dish_name 이후의 모든 step은 session["registration"]이 이미 있다는 걸 전제로 한다.
    reg = session.get("registration")
    if reg is None:
        raise ValueError("dish_name 단계 없이 등록을 진행할 수 없음")

    if step == "ingredients":
        # EC-15: "재료가 두부요" "아 감자도요" 처럼 한 번에 다 안 말하고 여러 턴에
        # 걸쳐 말할 수도 있어서, 기존 목록을 지우지 않고 extend(추가)한다.
        reg["ingredients"].extend(value)
        return {"checkpoint": "ingredients", "summary": _ingredient_summary(reg["ingredients"])}

    if step == "correct_ingredient":
        # EC-14: 재료 확인 체크포인트에서 "문어 말고 낙지야"처럼 정정이 들어온 경우.
        # 문서는 "FR-07(재료대체)과 동일 로직"이라고 하는데, 여기서는 아직 DB에
        # 저장도 안 한 임시 목록이라 recipe_search.py처럼 DB를 검색할 필요가
        # 없다 — 그냥 이 자리에서 문자열만 old -> new로 바꿔치기하면 된다.
        old, new = value["old"], value["new"]
        reg["ingredients"] = [new if item == old else item for item in reg["ingredients"]]
        return {"checkpoint": "ingredients", "summary": _ingredient_summary(reg["ingredients"])}

    if step == "instructions":
        reg["instructions"].extend(value)  # 재료와 마찬가지로 여러 턴 누적 허용
        return {
            "checkpoint": "final",
            "summary": _final_summary(reg["ingredients"], reg["instructions"]),
        }

    if step == "abort":
        # EC-16: "그만할래" -> 지금까지 모은 정보를 전부 버리고, DB에는 아무것도 안 씀.
        session["registration"] = None
        return {"aborted": True}

    if step == "confirm":
        # AC-06: 재료 확인 체크포인트 + 최종 확인 체크포인트 둘 다 사용자가
        # "응"이라고 답한 뒤에야 파이프라인이 이 step으로 호출한다.
        # 여기서 처음이자 마지막으로 실제 DB 저장(save_recipe)이 일어난다.
        result = save_recipe(
            dish_name=reg["dish_name"],
            ingredients=reg["ingredients"],
            instructions=reg["instructions"],
            source="user_custom",  # 신규 등록은 항상 사용자 버전
            origin_id=None,
            owner_id=session.get("owner_id"),  # 작업3: 쿠키 UUID (누구 레시피인지)
            client=client,
        )
        session["registration"] = None  # 저장 끝났으니 임시 등록 상태는 정리
        return result

    raise ValueError(f"알 수 없는 step: {step}")


def save_recipe(
    dish_name: str,
    ingredients: list[str],
    instructions: list[str],
    source: str = "user_custom",
    origin_id: str | None = None,
    owner_id: str | None = None,
    client=None,
) -> dict:
    """레시피 하나를 실제로 recipes/recipe_steps 테이블에 저장한다(7.5 확정 저장).

    EC-17: 이미 같은 요리명으로 저장된 user_custom이 있어도 "덮어쓰기"를 하지
    않는다. 그냥 매번 새 recipe_id로 insert만 한다(UPSERT나 "존재하면 UPDATE"
    같은 로직이 전혀 없음) — 그래서 사용자가 같은 요리를 여러 버전으로 저장해도
    전부 별도의 행으로 남는다.

    owner_id(작업3, 쿠키 UUID): user_custom을 저장할 때 "이건 누구 것인지"를
    같이 남긴다. load_data.py로 적재하는 api_standard 데이터는 owner_id가
    항상 None이다(특정 개인 소유가 아니라 모두를 위한 표준 데이터라서).
    """
    client = client or get_client()
    # .insert({...}) 는 딕셔너리 하나(행 하나)를 즉시 넣고, .execute().data는
    # "방금 insert된 행들"의 리스트를 돌려준다. 우리는 한 행만 넣었으니 [0]으로
    # 그 행 하나를 꺼낸다 — 이때 id(recipe_id)는 DB가 자동으로 만들어준
    # 값이라 우리가 미리 알 수 없고, 이렇게 insert 결과에서 읽어와야 한다.
    recipe = (
        client.table("recipes")
        .insert(
            {
                "dish_name": dish_name,
                "ingredients": ", ".join(ingredients),  # 리스트를 콤마로 이어붙여 텍스트 컬럼에 저장
                "source": source,
                "origin_id": origin_id,
                "owner_id": owner_id,
            }
        )
        .execute()
        .data[0]
    )
    recipe_id = recipe["id"]

    # 순서 목록(instructions)은 recipe_steps 테이블에 "1단계, 2단계, ..."로 나눠 저장한다.
    # enumerate(instructions, start=1) 은 (1, 첫 문장), (2, 두 번째 문장), ... 을 만들어준다.
    step_payload = [
        {"recipe_id": recipe_id, "step_number": i, "step_text": text, "source": source}
        for i, text in enumerate(instructions, start=1)
    ]
    if step_payload:  # 혹시 순서가 하나도 없으면 빈 insert를 보내지 않는다
        client.table("recipe_steps").insert(step_payload).execute()

    return {"recipe_id": recipe_id, "saved": True}


def update_recipe(
    recipe_id: str,
    dish_name: str,
    ingredients: list[str],
    instructions: list[str],
    client=None,
) -> dict:
    """이미 저장된 user_custom 레시피 한 건을 제자리에서 고친다(마이 레시피 화면의 "수정").

    save_recipe()는 일부러 매번 새 행을 insert만 하고 절대 덮어쓰지 않는다(EC-17) —
    "새 버전으로 등록"과 "이미 있는 내 레시피를 고치기"는 다른 동작이라서 함수도
    나눴다. recipe_steps는 통째로 지우고 다시 넣는다 — 조리순서는 몇 단계짜리로
    바뀔지 몰라서(늘거나 줄 수 있음) 행 단위로 하나씩 맞춰 UPDATE하는 것보다
    delete-then-insert가 훨씬 단순하고, on delete cascade와 달리 recipes 행 자체는
    안 건드리므로 recipe_id/created_at/owner_id 등은 그대로 유지된다.
    """
    client = client or get_client()
    client.table("recipes").update(
        {"dish_name": dish_name, "ingredients": ", ".join(ingredients)}
    ).eq("id", recipe_id).execute()

    client.table("recipe_steps").delete().eq("recipe_id", recipe_id).execute()
    step_payload = [
        {"recipe_id": recipe_id, "step_number": i, "step_text": text, "source": "user_custom"}
        for i, text in enumerate(instructions, start=1)
    ]
    if step_payload:
        client.table("recipe_steps").insert(step_payload).execute()

    return {"recipe_id": recipe_id, "updated": True}


def delete_recipe(recipe_id: str, client=None) -> dict:
    """user_custom 레시피 한 건을 완전히 지운다(마이 레시피 화면의 "삭제").

    recipe_steps부터 먼저 지운다 — schema.sql의 on delete cascade가 recipes 삭제 시
    딸린 recipe_steps도 자동으로 지워주긴 하지만, 여기서 명시적으로 먼저 지워서 그
    설정 여부에 기대지 않고 항상 같은 순서로 정리되게 한다.
    """
    client = client or get_client()
    client.table("recipe_steps").delete().eq("recipe_id", recipe_id).execute()
    client.table("recipes").delete().eq("id", recipe_id).execute()
    return {"recipe_id": recipe_id, "deleted": True}
