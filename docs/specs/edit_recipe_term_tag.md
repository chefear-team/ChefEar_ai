# Spec: 마이레시피 수정 시 [TERM:...] 태그가 별도 단계로 분리되는 버그 수정

> 2026-10-09 작성. 흐름 캡처 중 수정 화면(`docs/images/flow/16_edit_recipe.jpg`)에서 발견했다.

## Why

- **페르소나**: 로그인해서 자기 레시피를 등록한 뒤 마이레시피에서 오타를 고치는 사용자
- **상황**: 등록할 때 "조려주세요", "어슷썰기" 같은 표현이 있으면 `save_recipe()`가 `auto_tag_terms()`로 단계 문장 뒤에 줄바꿈 + `[TERM:용어]` 태그를 붙여 저장한다(예: `3. 중불에서 15분간 조려주세요.\n[TERM:조리다]`).
- **문제**:
  1. 수정 화면은 단계들을 줄바꿈으로 이어 붙여 텍스트 칸에 채우기 때문에, 태그가 독립된 한 줄로 보인다.
  2. 저장할 때 줄 단위로 다시 나누므로, **아무것도 안 바꾸고 저장해도** 태그 줄이 별도 단계가 된다. 재현 결과: 4단계 → 5단계(`4. [TERM:조리다]`), 원래 3단계에서는 태그가 사라진다.
  3. 조리 중 그 단계는 화면에 `4.`만 보이고, 음성은 용어 설명("조리다란 …이에요.")만 읽는다. 단계 표시도 `n / 5`로 틀어진다.
  4. `update_recipe()`는 `auto_tag_terms()`를 부르지 않아서, 수정으로 새로 넣은 문장에는 용어 태그가 붙지 않는다.
- **측정 지표**: 수정 화면에서 변경 없이 저장했을 때 단계 수·단계 문장이 저장 전과 같다. 태그만 있는 단계가 0건이다.

## Goal

- **해결 목표**: 용어 태그를 "사용자가 고치는 텍스트"에서 빼고, 저장할 때마다 문장에서 다시 만든다. 등록(`save_recipe`)과 수정(`update_recipe`)이 같은 규칙으로 태그를 붙인다.
- **성공 기준**: 아래 AC 전부 통과 + `pytest tests/` 그린.
- **Out of Scope**:
  - 이미 이 버그로 쪼개져 저장된 행을 일괄 정리하는 마이그레이션(다음 수정·저장 때 EC-04로 자연 복구됨)
  - `api_standard` 500건 데이터(마이레시피에서 수정 대상이 아님)
  - 용어 사전(`TERM_PATTERNS`, `TERM_DICT`) 추가·변경
  - 수정 화면의 UI 배치 변경

## What

**Happy Path**
1. 사용자가 마이레시피에서 레시피의 수정(연필) 버튼을 누른다.
2. 조리 순서 칸에는 단계마다 한 줄씩, `N. ` 접두어와 `[TERM:...]` 태그가 모두 빠진 문장만 채워진다.
3. 사용자가 문장을 고치거나 그대로 두고 저장한다.
4. 저장 시 각 줄을 한 단계로 보고, `save_recipe()`와 같은 방식(`auto_tag_terms()`)으로 태그를 다시 붙여 `N. 문장[\n[TERM:...]]` 형태로 저장한다.
5. 조리 화면·음성은 등록 직후와 같은 결과를 낸다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 한 단계에 태그가 여러 개(`\n[TERM:a]\n[TERM:b]`) | 채울 때 모두 제거, 저장 시 문장에서 감지되는 만큼 다시 붙음 |
| EC-02 | 사용자가 텍스트 칸에 `[TERM:x]`만 있는 줄을 직접 입력 | 저장 시 태그를 걷어낸 뒤 빈 줄이 되면 단계로 만들지 않음 |
| EC-03 | 수정으로 용어 표현을 지움(예: "조려주세요" → "끓여주세요") | 저장 시 그 문장에서 감지되지 않으므로 태그도 붙지 않음 |
| EC-04 | 이미 버그로 `N. [TERM:x]`만 남은 행이 있는 레시피 | 채울 때 빈 문장이 되어 줄에서 빠짐 → 저장하면 해당 단계가 사라지고 순번이 다시 매겨짐 |
| EC-05 | 수정으로 새 용어 표현을 넣음(예: "어슷썰기 해주세요") | 저장 시 `[TERM:어슷썰기]`가 붙음(등록과 동일) |
| EC-06 | 순서 칸을 전부 비우고 저장 | 기존 동작 유지(단계 0건 저장). 이 스펙에서 바꾸지 않음 |

## How

- `src/ui/screens/my_recipes.py`
  - 순수 함수 `_prefill_instructions(steps: list[dict]) -> str`를 추가한다. 각 `step_text`에 `resolve_for_display()` → `_strip_step_prefix()` → `strip()`을 적용하고, 빈 문자열은 버린 뒤 `"\n"`으로 잇는다.
  - 순수 함수 `_parse_instructions(text: str) -> list[str]`를 추가한다. 줄 단위로 나눠 각 줄에 `resolve_for_display()` → `strip()`을 적용하고, 빈 줄은 버린다.
  - `screen_edit_recipe()`의 `instructions_text` 기본값은 `_prefill_instructions(steps)`, 저장 시 `instructions`는 `_parse_instructions(instructions_text)`를 쓴다.
- `src/orchestration/registration.py`
  - `update_recipe()`의 `step_text`를 `f"{i}. {auto_tag_terms(text)}"`로 바꾼다(`save_recipe()` 125행과 동일).
- `src/orchestration/term_dict.py`는 바꾸지 않는다. `resolve_for_display()`의 패턴(`\n?\[TERM:...\]`)을 그대로 쓴다.
- DB 스키마 변경 없음.
- 테스트: `tests/test_my_recipes.py`(`_prefill_instructions`, `_parse_instructions`)와 `tests/test_registration.py`(`update_recipe` 태깅, 왕복 저장)에 추가한다. `FakeSupabaseClient` 사용.

## AC (Given-When-Then)

**AC-01 · 변경 없이 저장해도 단계가 그대로**
- GIVEN: `save_recipe()`로 단계 4개(`"감자와 양파를 한입 크기로 썰어주세요."`, `"냄비에 감자를 넣고 간장, 설탕, 물 한 컵을 부어주세요."`, `"중불에서 15분간 조려주세요."`, `"물엿과 참기름을 넣고 윤기가 나게 섞어주세요."`)를 저장함
- WHEN: 저장된 단계로 `_prefill_instructions()` → `_parse_instructions()` → `update_recipe()`를 실행
- THEN: 단계는 4개이고, 각 `step_text`가 저장 직후와 정확히 같다(3단계는 `"3. 중불에서 15분간 조려주세요.\n[TERM:조리다]"`)

**AC-02 · 수정 칸에 태그가 보이지 않음**
- GIVEN: AC-01과 같은 레시피
- WHEN: `_prefill_instructions(steps)`
- THEN: 결과에 `"[TERM:"`이 없고, 줄 수가 4다

**AC-03 · 수정으로 넣은 용어 표현에 태그가 붙음**
- GIVEN: 저장된 레시피
- WHEN: 한 단계를 `"양파를 어슷썰기 해주세요."`로 바꿔 `update_recipe()`
- THEN: 그 단계의 `step_text`에 `"[TERM:어슷썰기]"`가 들어 있다

**AC-04 · 용어 표현을 지우면 태그도 사라짐**
- GIVEN: 3단계가 `"...조려주세요.\n[TERM:조리다]"`인 레시피
- WHEN: 3단계를 `"중불에서 15분간 끓여주세요."`로 바꿔 `update_recipe()`
- THEN: 3단계 `step_text`에 `"[TERM:"`이 없다

**AC-05 · 이미 쪼개진 행은 다음 저장 때 복구됨**
- GIVEN: 단계가 `["1. 가", "2. 나", "3. 조려주세요.", "4. [TERM:조리다]", "5. 다"]`로 저장된 레시피
- WHEN: `_prefill_instructions()` → `_parse_instructions()` → `update_recipe()`
- THEN: 단계는 4개이고, 태그만 있는 단계가 없으며, 3단계에는 `"[TERM:조리다]"`가 다시 붙어 있다

**AC-06 · 태그만 있는 줄은 단계가 되지 않음**
- GIVEN: 수정 칸 텍스트 `"가\n[TERM:조리다]\n나"`
- WHEN: `_parse_instructions(text)`
- THEN: 결과는 `["가", "나"]`

**AC-07 · 회귀 없음**
- GIVEN: 이 변경을 적용한 상태
- WHEN: `pytest tests/`
- THEN: 기존 테스트를 포함해 전부 통과
