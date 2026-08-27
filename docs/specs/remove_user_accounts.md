# Spec: 일반 사용자 계정 시스템(로그인/회원가입/마이레시피) 전체 제거

## Why

- **상황**: 로그인/회원가입/마이레시피/edit_recipe 화면은 Streamlit 화면 전환 잔상(streamlit/streamlit#8360, `src/app.py`/`src/README.md`에 여러 번 기록된 미해결 버그) 계열 문제를 계속 일으켜왔고(`my_recipes.py`의 "삭제 버튼 누르면 잔상" 리포트 등), 팀이 이 기능 라인 자체를 유지보수 부담으로 판단해 걷어내기로 함.
- **문제**:
  1. 계정 시스템(`orchestration/auth.py`, `users` 테이블)과 쿠키 익명 식별(`orchestration/identity.py`, FR-08)이 둘 다 "이게 누구 것인지"를 가리는 데 쓰이는데, 곧 도입할 관리자 승인(Y/N) 모델에서는 "등록한 사람이 누구인지"를 아예 추적하지 않기로 함(별도 스펙 `admin_recipe_approval.md`) — 그러면 이 둘은 유지할 이유가 없는 죽은 코드가 된다.
  2. 등록 진입 4곳(`ui/dispatch.py`의 `_REGISTER_WORD` 문자열 매칭 / LLM `wants_register` / `handle_utterance()` ValueError / `classify_intent()`의 `등록` 의도)이 전부 `_block_register_if_not_logged_in()`으로 로그인을 요구하는데, 로그인 자체가 없어지면 이 게이트가 등록을 원천 차단하는 버그가 된다("등록"이라고 말해도 "로그인 후 이용해 주세요"만 반복 재생됨).
- **측정 지표**: 정량 지표 없음(스코프 축소 + 버그 예방) — AC 통과로 판단.

## Goal

- **해결 목표**: 일반 사용자에게 계정/로그인 개념을 완전히 없앤다. 레시피 등록은 로그인 여부와 무관하게 누구나 음성으로 바로 진입할 수 있다(공개 여부는 이 스펙이 아니라 `admin_recipe_approval.md`의 승인 워크플로우가 담당).
- **성공 기준**:
  - `SCREENS` 딕셔너리에 `"login"`/`"my_recipes"`/`"edit_recipe"`가 없다.
  - "등록"이라는 단어/의도가 인식되면 로그인 여부 확인 없이 바로 `register_intro`/`register_dish_name`으로 진입한다.
  - "로그인 후 이용해 주세요" 문구가 코드 어디에도 남지 않는다.
  - `pytest` 전체가 그린이다.
- **Out of Scope**:
  - 관리자 인증/레시피 승인 워크플로우 — `docs/specs/admin_recipe_approval.md`에서 다룸.
  - DB 스키마 변경 — `users` 테이블, `recipes.owner_id` 컬럼 둘 다 **그대로 둔다**(DROP 안 함). `owner_id`는 나중에 구글 OAuth 등을 붙일 때 같은 컬럼에 새 식별자(구글 `sub`/`email`)를 넣어 재사용할 수 있어서 스키마를 건드릴 필요가 없다 — 이번엔 그 컬럼을 **채우는 코드만** 제거한다.
  - 구글 OAuth 로그인 도입 여부 — 아직 결정 안 됨, 보류 중(별도로 다시 논의).

## What

**Happy Path**

1. 사용자가 아무 때나 "레시피 등록해줘" 같은 발화를 한다.
2. 로그인 여부를 묻지 않고 바로 `register_intro` 화면으로 진입한다.
3. `register_dish_name` → `register_ingredients` → `register_steps` → `complete` 순으로 기존 등록 플로우를 그대로 밟는다.
4. `register_recipe()`가 저장하는 행의 `owner_id`는 항상 `None`이다(누가 등록했는지 추적하지 않음).

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 기존에 "로그인 후 이용해 주세요"가 뜨던 4개 진입 경로 전부 | 게이트 자체가 없으므로 전부 그냥 통과 |
| EC-02 | 기존에 로그인 상태면 `select_standard_recipe()`가 "내가 등록한 user_custom" 우선 노출하던 로직 | 이 스펙에서 `owner_id` 매개변수/분기를 제거만 하고, "무엇을 대신 노출할지"(승인 Y/N 기준)는 `admin_recipe_approval.md`에서 구현 — 두 스펙이 순서대로 적용된다는 전제 |
| EC-03 | 새로고침해도 로그인 유지되던 쿠키(`chefear_user_id`) | 로그인 자체가 없으므로 해당 없음 |
| EC-04 | 기존 배포에 이미 존재하는 `users` 행/로그인했던 계정 | 테이블을 그대로 두므로 데이터 자체는 안 사라짐 — 그냥 아무 코드도 그 테이블을 안 읽음(원하면 나중에 수동 정리) |

## How (파일별 변경)

1. **삭제**: `ui/screens/my_recipes.py` (전체 — `screen_login()`, `screen_my_recipes()`, `screen_edit_recipe()`가 이 파일 하나에 다 있음)
2. **삭제**: `orchestration/auth.py` (계정 생성/인증/해시 로직 전체 — `create_user`, `authenticate_user`, `get_user_by_id`, `hash_password` 등)
3. **삭제**: `orchestration/identity.py` (쿠키 익명 UUID 전체 — `get_or_create_anon_id()`, `build_cookie_manager()`)
4. **`ui/session.py`**
   - 삭제: `login()`, `logout()`, `restore_login_from_cookie()`, `get_owner_id()`, `_LOGIN_COOKIE_KEY`
   - `init_state()`에서 `current_user`, `editing_recipe_id`, `confirm_delete_id` 초기화 라인 삭제
   - `_DEFAULT_PIPELINE_SESSION`에서 `"owner_id": None` 삭제
5. **`ui/dispatch.py`**
   - `_block_register_if_not_logged_in()` 함수 정의(64~94줄) 삭제
   - 호출부 4곳 삭제: 191줄, 343줄, 381줄, 544줄
   - `get_owner_id()` 호출부 삭제: 197줄, 217줄, 345줄, 383줄
6. **`ui/screens/register.py`**
   - `get_owner_id()` 호출부 삭제: 176줄, 211줄
7. **`orchestration/registration.py`**
   - `register_recipe()`가 `owner_id=session.get("owner_id")`를 넘기던 부분을 `owner_id=None`으로 고정(혹은 파라미터 자체를 지우고 항상 `None`으로 insert)
8. **`orchestration/recipe_search.py`**
   - `select_standard_recipe()`의 `owner_id` 매개변수와 그 분기(347~356줄) 삭제 — 어떤 필터를 대신 넣을지는 `admin_recipe_approval.md`에서 구현
9. **`app.py`**
   - import에서 `screen_login`, `screen_my_recipes`, `screen_edit_recipe`, `restore_login_from_cookie` 제거
   - `SCREENS` 딕셔너리에서 `"login"`, `"my_recipes"`, `"edit_recipe"` 항목 삭제
   - `restore_login_from_cookie()` 호출(262줄 부근) 삭제
   - `current_user`/`_LOGIN_BUTTON_HIDDEN_SCREENS`/브랜드 로그인 버튼 렌더링 블록(281~305줄) 삭제 — 이 자리는 `admin_recipe_approval.md`의 화자식별 트리거로 대체됨(버튼 자체가 없어짐)
   - `elif screen == "login":`, `elif screen in ("my_recipes", "edit_recipe"):` 마이크 처리 분기(417~430줄) 삭제
10. **의존성**: `requirements-main.txt`에서 `streamlit-cookies-manager` 제거
10-1. **환경변수**: `.env.example`, `.env.example.local`에서 `COOKIE_SECRET` 항목 삭제(identity.py 삭제로 더 이상 안 쓰임)
11. **테스트**: `tests/test_identity.py` 등 관련 테스트 삭제, `test_recipe_search.py`/`test_pipeline.py`/`test_registration.py`에서 `owner_id`/로그인 관련 케이스 정리

## AC (Given-When-Then)

**AC-01 · 로그인 관련 화면 전부 제거**
- GIVEN: `app.py`의 `SCREENS` 딕셔너리
- WHEN: 키 목록을 확인함
- THEN: `"login"`, `"my_recipes"`, `"edit_recipe"`가 없다

**AC-02 · 로그인 없이 등록 진입**
- GIVEN: 로그인 개념 자체가 없는 상태(=항상)
- WHEN: 사용자가 "레시피 등록해줘"라고 말함
- THEN: 바로 `register_intro` 화면으로 진입한다(안내 음성 "로그인 후 이용해 주세요"가 나오지 않는다)

**AC-03 · "로그인 후 이용해 주세요" 문구 완전 제거**
- GIVEN: 저장소 전체 코드
- WHEN: 이 문자열을 검색함
- THEN: 어디에도 없다

**AC-04 · 계정/쿠키 모듈 삭제 확인**
- GIVEN: 저장소 전체
- WHEN: `orchestration/auth.py`, `orchestration/identity.py`, `ui/screens/my_recipes.py` 존재 여부를 확인함
- THEN: 세 파일 다 존재하지 않는다

**AC-05 · owner_id는 항상 None으로 저장**
- GIVEN: 신규 레시피 등록이 완료됨
- WHEN: `recipes` 테이블에 저장된 행을 확인함
- THEN: `owner_id` 컬럼 값이 `null`이다(컬럼 자체는 존재)

**AC-06 · 테스트 스위트 그린**
- GIVEN: 위 변경 전부 적용됨
- WHEN: `pytest`를 전체 실행함
- THEN: 실패 0건
