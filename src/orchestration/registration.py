"""7.5 — register_recipe()(다단계 세션형)/save_recipe(). FR-06/EC-14~17/AC-06."""
from __future__ import annotations

import re

from orchestration.db import get_client
from orchestration.term_dict import auto_tag_terms


def _normalize_dish_name(value):
    """등록/수정 양쪽에서 DB에 저장하기 직전 dish_name을 정리한다."""
    if not isinstance(value, str):
        return value
    text = value.strip().rstrip("?!.,~ ")
    return re.sub(r"\s+", "", text)


def _ingredient_summary(ingredients: list[str]) -> str:
    """재료 확인 체크포인트에서 사용자에게 읽어줄 문장을 만든다(FR-06)."""
    return "재료를 확인할게요: " + ", ".join(ingredients) + ". 맞나요?"


def _final_summary(ingredients: list[str], instructions: list[str]) -> str:
    """최종 확인 체크포인트에서 재료+순서를 전부 읽어줄 문장을 만든다(FR-06)."""
    steps_text = " ".join(f"{i}. {t}" for i, t in enumerate(instructions, start=1))
    return "재료와 순서를 확인할게요. 재료: " + ", ".join(ingredients) + f". 순서: {steps_text} 이대로 저장할까요?"


def register_recipe(session: dict, step: str, value=None, client=None, owner_id: str | None = None) -> dict:
    """등록 대화 한 턴을 처리한다. step 값에 따라 하는 일이 완전히 달라지는
    "상태 기계(state machine)" 형태의 함수다 — 지금 세션이 어느 단계에
    있느냐에 따라 같은 함수를 다르게 호출해가며 쓴다.

    step의 종류:
      "dish_name"    : 등록 시작, 요리명 받기
      "ingredients"  : 재료 목록 받기 (여러 턴에 나눠 말해도 계속 누적됨)
      "instructions" : 조리 순서 받기 (역시 여러 턴 누적 가능)
      "confirm"      : 최종 확인 완료 -> 진짜로 저장
      "abort"        : 등록 중간에 사용자가 그만두겠다고 함
    """
    if step == "dish_name":
        # 등록의 첫 턴. 이전에 진행 중이던 등록 정보가 있었더라도 새로 시작하면
        # 덮어쓴다(요리명, 재료, 순서를 담을 빈 상자를 새로 만드는 것).
        # _normalize_dish_name() 문서 참고 — trailing 문장부호 제거 + 공백 전부 제거.
        dish_name = _normalize_dish_name(value)
        session["registration"] = {"dish_name": dish_name, "ingredients": [], "instructions": []}
        return {"prompt": f"{dish_name}에 들어가는 재료를 알려주세요."}

    # dish_name 이후의 모든 step은 session["registration"]이 이미 있다는 걸 전제로 한다.
    reg = session.get("registration")
    if reg is None:
        raise ValueError("dish_name 단계 없이 등록을 진행할 수 없음")

    if step == "ingredients":
        # EC-15: "재료가 두부요" "아 감자도요" 처럼 한 번에 다 안 말하고 여러 턴에
        # 걸쳐 말할 수도 있어서, 기존 목록을 지우지 않고 extend(추가)한다.
        reg["ingredients"].extend(value)
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
        if owner_id is None:
            raise ValueError("등록에는 로그인이 필요합니다")
        result = save_recipe(
            dish_name=reg["dish_name"],
            ingredients=reg["ingredients"],
            instructions=reg["instructions"],
            source="user_custom",  # 신규 등록은 항상 사용자 버전
            origin_id=None,
            client=client,
            owner_id=owner_id,
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
    client=None,
    owner_id: str | None = None,
) -> dict:
    """레시피 하나를 실제로 recipes/recipe_steps 테이블에 저장한다(7.5 확정 저장)."""
    if source == "user_custom" and not owner_id:
        raise ValueError("등록에는 로그인이 필요합니다")
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
                "ingredients": "|".join(ingredients),
                "source": source,
                "origin_id": origin_id,
                "approved": "Y",
                "owner_id": owner_id,
            }
        )
        .execute()
        .data[0]
    )
    recipe_id = recipe["id"]

    step_payload = [
        {"recipe_id": recipe_id, "step_number": i, "step_text": f"{i}. {auto_tag_terms(text)}", "source": source}
        for i, text in enumerate(instructions, start=1)
    ]
    if step_payload:  # 혹시 순서가 하나도 없으면 빈 insert를 보내지 않는다
        client.table("recipe_steps").insert(step_payload).execute()

    # 새로 등록된 요리명이 _all_dish_names() lru_cache에 즉시 반영되게 비운다 —
    # 안 비우면 같은 프로세스·같은 client에서 신규 등록 직후 조회가 불가하다.
    try:
        from orchestration.recipe_search import _all_dish_names, _decomposed_name_map

        _all_dish_names.cache_clear()
        _decomposed_name_map.cache_clear()
    except Exception:  # noqa: BLE001 — 캐시 무효화 실패가 저장을 막으면 안 됨
        pass

    return {"recipe_id": recipe_id, "saved": True}


def update_recipe(
    recipe_id: str,
    dish_name: str,
    ingredients: list[str],
    instructions: list[str],
    client=None,
    owner_id: str | None = None,
) -> dict:
    """이미 저장된 user_custom 레시피 한 건을 제자리에서 고친다(마이레시피 화면의 "수정",
    docs/specs/my_recipes.md).
    """
    client = client or get_client()
    if owner_id is not None:
        rows = client.table("recipes").select("id,owner_id").eq("id", recipe_id).execute().data or []
        if not rows:
            raise ValueError("레시피를 찾을 수 없습니다")
        if rows[0].get("owner_id") != owner_id:
            raise PermissionError("본인이 등록한 레시피만 수정할 수 있습니다")
    client.table("recipes").update(
        {"dish_name": _normalize_dish_name(dish_name), "ingredients": "|".join(ingredients)}
    ).eq("id", recipe_id).execute()

    client.table("recipe_steps").delete().eq("recipe_id", recipe_id).execute()
    step_payload = [
        {"recipe_id": recipe_id, "step_number": i, "step_text": f"{i}. {auto_tag_terms(text)}", "source": "user_custom"}
        for i, text in enumerate(instructions, start=1)
    ]
    if step_payload:
        client.table("recipe_steps").insert(step_payload).execute()

    return {"recipe_id": recipe_id, "updated": True}


def delete_recipe(recipe_id: str, client=None, owner_id: str | None = None) -> dict:
    """레시피 한 건을 완전히 지운다(관리자 페이지의 "삭제" — admin_recipe_approval.md,
    마이레시피의 "삭제" — my_recipes.md).

    recipe_steps부터 먼저 지운다 — schema.sql의 on delete cascade가 recipes 삭제 시
    딸린 recipe_steps도 자동으로 지워주긴 하지만, 여기서 명시적으로 먼저 지워서 그
    설정 여부에 기대지 않고 항상 같은 순서로 정리되게 한다.

    owner_id를 넘기면(마이레시피 경로) 소유권을 확인하고, 남의 레시피면 지우지 않고
    PermissionError를 올린다 — IDOR 방지. owner_id를 안 넘기면(관리자 경로) 기존처럼
    소유권 확인 없이 지운다.
    """
    client = client or get_client()
    if owner_id is not None:
        rows = client.table("recipes").select("id,owner_id").eq("id", recipe_id).execute().data or []
        if not rows:
            raise ValueError("레시피를 찾을 수 없습니다")
        if rows[0].get("owner_id") != owner_id:
            raise PermissionError("본인이 등록한 레시피만 삭제할 수 있습니다")
    client.table("recipe_steps").delete().eq("recipe_id", recipe_id).execute()
    client.table("recipes").delete().eq("id", recipe_id).execute()
    return {"recipe_id": recipe_id, "deleted": True}
