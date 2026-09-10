# -*- coding: utf-8 -*-
"""500개 레시피(규칙 기반 생성 조리순서)를 recipes/recipe_steps에 적재한다."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from orchestration.db import get_client  # noqa: E402

CSV_PATH = PROJECT_ROOT / "docs" / "한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv"

# "1. 문장..." 처럼 줄 맨 앞의 "숫자. "를 단계 구분자로 쓴다. 이 구분자가 나온 줄부터
# 다음 구분자 직전까지(그 사이에 낀 [TERM:...] 줄 포함)가 한 단계다.
_STEP_START_RE = re.compile(r"^\d+\.\s")


def split_steps(cooking_steps_text: str) -> list[str]:
    """COOKING_STEPS 컬럼 원문을 "숫자. " 기준으로 단계별 텍스트로 쪼갠다.

    각 단계 텍스트는 "1. 문장.\n[TERM:용어]"처럼 뒤따르는 [TERM:...] 줄을 그대로
    포함한 원본 그대로다 — 여기서 resolve하지 않는다(3단계 지시사항: "step_text는
    태그 포함 원본 그대로 저장").
    """
    lines = cooking_steps_text.splitlines()
    steps: list[list[str]] = []
    for line in lines:
        if _STEP_START_RE.match(line):
            steps.append([line])
        elif steps:
            # 아직 첫 단계 시작 전(빈 줄 등)이면 조용히 버림 — 실제 데이터엔 안 나타남
            steps[-1].append(line)
    return ["\n".join(chunk) for chunk in steps]


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV를 찾을 수 없음: {CSV_PATH}")

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[load_500] CSV {len(rows)}행 읽음: {CSV_PATH.name}")

    client = get_client(allow_mock=False)  # 진짜 DB 필수 — mock에 적재해봐야 의미없음(db.py 문서 참고)

    recipe_payload = [
        {
            "dish_name": row["CKG_NM"].strip(),
            "ingredients": row["CKG_MTRL_CN"].strip(),
            "source": "api_standard",
            "approved": "Y",
        }
        for row in rows
    ]

    print(f"[load_500] recipes {len(recipe_payload)}건 insert 중...")
    inserted_recipes = client.table("recipes").insert(recipe_payload).execute().data
    print(f"[load_500] recipes insert 완료: {len(inserted_recipes)}건")

    # dish_name -> recipe_id 매핑(방금 insert된 행들의 반환값 기준 — 중복 dish_name이
    # 없다는 건 이미 CSV 검증에서 확인됨).
    recipe_id_by_name = {r["dish_name"]: r["id"] for r in inserted_recipes}

    step_payload = []
    for row in rows:
        dish_name = row["CKG_NM"].strip()
        recipe_id = recipe_id_by_name[dish_name]
        step_texts = split_steps(row["COOKING_STEPS"])
        for i, step_text in enumerate(step_texts, start=1):
            step_payload.append(
                {
                    "recipe_id": recipe_id,
                    "step_number": i,
                    "step_text": step_text,
                    "source": "rule_generated",
                }
            )

    print(f"[load_500] recipe_steps {len(step_payload)}건 insert 중...")
    BATCH = 500
    for start in range(0, len(step_payload), BATCH):
        batch = step_payload[start : start + BATCH]
        client.table("recipe_steps").insert(batch).execute()
        print(f"[load_500]   {start + len(batch)}/{len(step_payload)}")

    print("[load_500] 완료.")
    print(f"[load_500] recipes: {len(inserted_recipes)}건, recipe_steps: {len(step_payload)}건")


if __name__ == "__main__":
    main()
