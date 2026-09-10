# Spec: 마이레시피(내가 등록한 레시피 목록/수정/삭제) 재도입

> 2026-09-01 구현(홍민하), 스펙은 2026-09-10 커밋 이력을 바탕으로 사후 작성.

## Why

- `remove_user_accounts.md`(08-27)로 계정과 함께 마이레시피 화면이 삭제됐다.
- `user_accounts_google_login.md`(09-01)로 로그인이 돌아오면서 "내가 등록한 레시피를 다시 보고 고칠 수 있어야 한다"는 요구가 되살아났다. 등록 직후 오타를 발견해도 고칠 방법이 없던 것이 실사용에서 가장 큰 불편이었다.

## Goal

- 로그인한 사용자가 자신이 등록한 `user_custom` 레시피를 목록으로 보고, 재료·순서를 수정하고, 삭제할 수 있다.
- 성공 기준: 등록 → 마이레시피에서 확인 → 수정 후 조회 시 반영 → 삭제 후 조회 불가. `pytest` 그린.
- Out of Scope: 다른 사용자의 레시피 열람, 공유, 정렬/검색.

## What

1. `start` 화면 상단 계정 영역에 "마이레시피" 진입 버튼(로그인 상태에서만 노출).
2. `my_recipes` 화면: 본인 `owner_id`의 레시피를 최신순으로 카드 목록 표시. 각 카드에 수정/삭제 버튼.
3. `edit_recipe` 화면: 요리명은 고정, 재료(`|` 구분)와 순서(줄 단위) 텍스트 폼으로 수정. 순서의 "N. " 접두어는 폼에 채울 때 떼고 저장할 때 다시 붙인다.
4. 삭제는 확인 버튼 2단계. `recipe_steps`는 `on delete cascade`로 함께 삭제.
5. 이 두 화면에서는 상시 마이크 자유발화를 받지 않는다(텍스트 폼이 주 입력). "처음으로"류 발화만 처리.

## How

- `src/ui/screens/my_recipes.py`: `screen_my_recipes()`, `screen_edit_recipe()`.
- `src/orchestration/registration.py`: `update_recipe()`, `delete_recipe()`가 `owner_id` 일치를 검사한다.
- `src/orchestration/recipe_search.py`: 본인 소유 레시피 목록 조회 헬퍼.
- 테스트: `tests/test_my_recipes.py`.

## AC

- AC-1 로그인 사용자 A가 등록한 레시피는 A의 마이레시피에만 나타난다.
- AC-2 수정 후 같은 요리명으로 조회하면 수정된 재료·순서가 안내된다.
- AC-3 삭제 후 조회하면 "등록되지 않은 레시피" 안내가 나온다.
- AC-4 다른 사용자 B의 `recipe_id`로 수정/삭제를 시도하면 거부된다(`tests/test_my_recipes.py`의 wrong_owner 케이스).
