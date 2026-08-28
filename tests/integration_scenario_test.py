"""ChefEar 오케스트레이션 통합테스트 — tests/integration_test.md 시나리오 A~D 자동 실행.

수동 체크리스트(tests/integration_test.md)에 적힌 handle_utterance() 호출들을 그대로
코드로 옮겨서 순차 실행하고, 문서의 THEN(기대값)과 실제 결과를 비교해 PASS/FAIL을
출력한다. pytest가 아니라 사람이 결과를 보고 tests/integration_test.md의 체크박스를
채우는 데 참고하는 읽기 전용 진단 스크립트다 — 실제 DB 데이터에 따라 결과가 달라질 수
있어서(예: 표준 데이터에 "바지락된장찌개"가 정확히 그 이름으로 있는지) FAIL이 떠도
자동으로 "버그"라고 단정하지 않고 detail을 보고 사람이 판단한다.

실행 전 준비: .env에 SUPABASE_URL/SUPABASE_KEY 필요(실제 DB 연결, allow_mock=False).

실행:
    uv run --with sentence-transformers==5.6.1 --with supabase==2.31.0 --python 3.12 \\
        python tests/integration_scenario_test.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_results = []  # (label, passed) 누적 — 마지막 요약용


def check(label: str, condition: bool, detail=None) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail is not None else ""))
    _results.append((label, bool(condition)))
    return condition


def run_scenario_a(handle_utterance, get_current_step, client):
    print("\n=== 시나리오 A — 조회 및 진행 ===")
    session = {}

    r = handle_utterance(session, "된장찌개 어떻게 만들어?", dish_name="된장찌개", client=client)
    check("A-1 intent == 조회", r.get("intent") == "조회", r)
    check("A-1 current_recipe_id 채워짐", bool(session.get("current_recipe_id")))
    check("A-1 step_number == 1", session.get("step_number") == 1)

    if not session.get("current_recipe_id"):
        print("  -> current_recipe_id가 없어 A-2 이후는 건너뜀(된장찌개가 DB에 없을 수 있음)")
        return

    step1 = get_current_step(session["current_recipe_id"], 1, client=client)
    check("A-2 1단계 텍스트 존재", bool(step1 and step1.get("text")), step1)

    r = handle_utterance(session, "다음", client=client)
    check("A-3 intent == 진행", r.get("intent") == "진행", r)
    check("A-3 step_number == 2", session.get("step_number") == 2)
    step2_text = (r.get("step") or {}).get("text")
    check("A-3 1단계와 다른 문장", bool(step1) and step2_text != step1.get("text"), step2_text)

    r = handle_utterance(session, "다시", client=client)
    check("A-4 intent == 재청취", r.get("intent") == "재청취", r)
    check("A-4 step_number 그대로(2)", session.get("step_number") == 2)

    r = handle_utterance(session, "이전", client=client)
    check("A-5 intent == 이전", r.get("intent") == "이전", r)
    check("A-5 step_number == 1", session.get("step_number") == 1)

    # A-6: 예외 없이 끝까지 "다음"을 반복할 수 있는지만 확인(안전장치로 최대 30회)
    count, last = 0, None
    try:
        for _ in range(30):
            last = handle_utterance(session, "다음", client=client)
            count += 1
            if last.get("step") is None:  # 더 이상 단계가 없음 = 끝까지 도달
                break
        check("A-6 예외 없이 진행", True, f"{count}회 진행 후 step={last.get('step')}")
    except Exception as e:
        check("A-6 예외 없이 진행", False, f"{count}회째 예외 발생: {e}")


# 2026-08-27 — 시나리오 B/C(진행 중 재료 대체)는 재료대체 기능 자체가 삭제되면서
# (remove_ingredient_substitution.md) 없앴다. handle_utterance()가 더 이상
# requested_ingredient 인자를 받지 않고, classify_intent()도 "재료대체"를 절대
# 돌려주지 않는다.


def run_scenario_d(handle_utterance, client):
    print("\n=== 시나리오 D — 표준 데이터 밖 요리 → 신규 등록 유도 ===")
    session = {}

    r = handle_utterance(session, "은하수비빔밥 어떻게 만들어?", dish_name="은하수비빔밥", client=client)
    check("D-1 intent == 조회", r.get("intent") == "조회", r)
    check(
        "D-1 없다고 정직 안내",
        r.get("message") == "등록되지 않은 레시피에요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요.",
        r.get("message"),
    )
    check("D-1 current_recipe_id 안 생김", "current_recipe_id" not in session)

    r = handle_utterance(
        session,
        "새 레시피 등록하고 싶어",
        registration_step="dish_name",
        registration_value="은하수비빔밥",
        client=client,
    )
    check("D-2 intent == 등록", r.get("intent") == "등록", r)
    check("D-2 재료 묻는 prompt", "재료" in (r.get("prompt") or ""), r.get("prompt"))
    check("D-2 dish_name 세션에 저장됨", (session.get("registration") or {}).get("dish_name") == "은하수비빔밥")


def run_ac15(handle_utterance, client, n=15):
    print(f"\n=== AC-15 반복 질의 일관성 (n={n}) ===")

    a1_ids = set()
    for _ in range(n):
        session = {}
        handle_utterance(session, "된장찌개 어떻게 만들어?", dish_name="된장찌개", client=client)
        a1_ids.add(session.get("current_recipe_id"))
    check(f"A-1 반복 {n}회 모두 동일 recipe_id", len(a1_ids) == 1, a1_ids)


def main():
    from orchestration.db import get_client
    from orchestration.pipeline import get_current_step, handle_utterance

    client = get_client(allow_mock=False)

    for scenario in (
        lambda: run_scenario_a(handle_utterance, get_current_step, client),
        lambda: run_scenario_d(handle_utterance, client),
        lambda: run_ac15(handle_utterance, client),
    ):
        try:
            scenario()
        except Exception as e:
            print(f"  !! 시나리오 실행 중 예외: {e}")

    n_pass = sum(1 for _, ok in _results if ok)
    print(f"\n=== 요약: {n_pass}/{len(_results)} PASS ===")
    for label, ok in _results:
        if not ok:
            print(f"  FAIL: {label}")

    print("\n결과를 tests/integration_test.md의 해당 체크박스에 옮겨 적으세요.")


if __name__ == "__main__":
    main()
