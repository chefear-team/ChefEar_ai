# Spec: 등록은 로그인 필수, 등록 레시피는 등록자 본인에게만 노출

> 2026-09-02 구현(홍민하, 보안 보강 09-08), 스펙은 2026-09-10 커밋 이력을 바탕으로 사후 작성.

## Why

- `admin_recipe_approval.md`의 "관리자 승인 후 공개" 모델은 관리자가 매번 검수해야 등록분이 쓸모 있어져, 등록한 본인조차 승인 전엔 자기 레시피를 조리에 못 쓰는 문제가 있었다.
- 로그인이 재도입되면서 "누가 등록했는지"를 알 수 있게 됐으므로, 공개 범위를 관리자 승인 대신 **소유자 기준**으로 가르는 것이 단순하고 안전하다.

## Goal

- 신규 등록은 로그인 사용자만 가능하고, 저장 즉시 등록자 본인에게 조회·조리 가능하다.
- 다른 사용자와 비로그인 조회자에게는 보이지 않는다. `api_standard`(500건 표준 데이터)는 전체 공개 유지.
- 성공 기준: 사용자 A 등록 → A 조회 성공 / B 조회 시 "등록되지 않은 레시피" / 비로그인 조회 시 동일. `pytest` 그린.
- Out of Scope: 공개 전환(공유) 기능, 관리자 승인으로 전체 공개하는 경로.

## What

1. `dispatch.py`의 "등록" 진입: 비로그인이면 로그인 화면으로 보내고 안내한다.
2. `save_recipe()`: `owner_id`가 없으면 저장을 거부한다. `approved='Y'`로 즉시 저장.
3. `select_standard_recipe()`: 후보는 `approved='Y'`이면서 (`api_standard` 또는 `owner_id == 현재 사용자`)인 행만.
4. 파이프라인(`handle_utterance`)은 세션의 `owner_id`를 검색·저장 함수에 전달한다. GPU 워커 프로세스 경계를 넘길 때도 세션 식별 정보를 함께 넘긴다.
5. 관리자 페이지는 `approved='N'`인 레거시 행만 다룬다. 신규 등록은 이 상태로 들어오지 않는다.

## How

- `src/orchestration/registration.py::save_recipe()`, `src/orchestration/recipe_search.py::select_standard_recipe()`, `src/orchestration/pipeline.py`, `src/ui/dispatch.py`.
- 09-08 보안 보강: 파이프라인 `owner_id` 누락, 비로그인 노출, IDOR(타인 `recipe_id` 수정/삭제), 저장 가드 결함 수정.
- 테스트: `tests/test_recipe_search.py`(소유자 필터, 표준 데이터 전체 공개), `tests/test_my_recipes.py`(타인 소유 접근 거부), `tests/test_auth.py`(계정).

## AC

- AC-1 비로그인 상태에서 "등록"이라고 말하면 로그인 화면으로 이동한다.
- AC-2 A가 등록한 레시피는 A에게 즉시 조회되고 B·비로그인에게는 조회되지 않는다.
- AC-3 표준 500건은 로그인 여부와 무관하게 조회된다.
- AC-4 `owner_id` 없는 저장 요청은 거부된다.
