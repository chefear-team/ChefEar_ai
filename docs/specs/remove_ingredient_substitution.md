# Spec: 재료대체 기능 전체 제거

## Why

- **상황**: 재료대체(조리 중 "바지락 넣어도 돼?"/"새우 빼줘"처럼 말하면 현재 레시피를 다른 재료 조합의 변형 레시피로 바꿔주는 기능, 되돌리기용 "취소" 인텐트 포함)를 팀이 실제로는 쓰지 않기로 함 — 원래부터 안 쓰는 기능(사용자 확인).
- **문제**:
  1. `AGENTS.md` 프로젝트 개요에 "재료 대체까지 그 자리에서 반영받는"이라는 문구로 헤드라인 기능처럼 적혀 있지만, 실사용 계획이 없어 유지보수 부담만 남아 있다.
  2. `ui/dispatch.py`의 백그라운드 job이 조회/등록 여부와 무관하게 **매 발화마다** `extract_substitution_ingredients()`를 실행한다 — 로컬 LLM 호출은 이미 조리 중이면 스킵하도록 고쳐졌는데(2026-08-26), 이 정규식 기반 추출은 그대로 남아 불필요한 연산이 계속 돈다.
  3. `intent_classifier.py`의 `VALID_INTENTS`/EC-05 특수분기, `orchestration/substitution.py` 모듈 전체가 실제로는 안 쓰이는 코드로 남는다.
- **측정 지표**: 정량 지표 없음(스코프 축소) — 완료 기준은 AC 통과 + 관련 테스트 그린.

## Goal

- **해결 목표**: "재료대체"/"취소"(되돌리기) 관련 코드·인텐트·UI 경로를 저장소에서 완전히 제거한다. 사용자가 조리 중 재료 대체성 발화를 해도 그 인텐트로는 절대 분류되지 않고 일반 미분류 재질문으로 처리된다.
- **성공 기준**:
  - `orchestration/substitution.py` 파일이 삭제된다.
  - `intent_classifier.VALID_INTENTS`에 `"재료대체"`, `"취소"`가 없다.
  - "바지락 넣어도 돼?"류 발화가 더 이상 `재료대체`로 분류될 수 없다(기준예문 자체가 로드 안 되므로 구조적으로 불가능).
  - 관련 테스트가 삭제/갱신되어 `pytest` 전체가 그린이다.
- **Out of Scope**:
  - `recipe_search.py`의 `select_standard_recipe()` 및 이름 보정 체인(공백 무시/반복 무시/접미사 제거 교정) — 이건 `조회` 전용 로직이라 그대로 유지한다. `search_variant_recipe()`/`search_by_ingredient_content()`만 제거 대상(재료대체 전용, 다른 호출부 없음을 확인함).
  - `AGENTS.md`/PRD 등 제품 문서에서 "재료 대체" 언급 수정 — 최종 단계에서 한 번에 처리(`docs/specs/dish_not_found_voice_notice.md`와 동일하게 유예).
  - `data/intent_examples/기준예문.csv`에서 `재료대체`/`취소` 행 삭제 — `VALID_INTENTS` 필터링으로 이미 무시되므로 선택 사항(정리하면 좋지만 필수는 아님).

## What

**Happy Path (기능 제거 후 동작)**

1. 사용자가 조리 중 "새우 빼고 만들어줘"라고 말한다.
2. `classify_intent()`는 더 이상 `재료대체` 예문이 없으므로(`VALID_INTENTS`에서 제외) 남은 인텐트들과만 유사도를 비교한다.
3. 대부분 threshold(0.5)/margin(0.05) 미달로 `미분류` 처리 → `FALLBACK_UNCLASSIFIED`("죄송해요, 잘 이해하지 못했어요...") 안내.
4. `cooking_step` 화면은 그대로 유지된다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 재배포 전 세션에 이미 `previous_recipe_id`가 남아있던 사용자 | 세션은 `st.session_state`(서버 메모리)라 재배포 시 자동 초기화됨 — 별도 마이그레이션 불필요 |
| EC-02 | `"취소"`라는 단어가 다른 맥락(예: 등록 중 취소)으로 쓰일 가능성 | 현재 `취소` 인텐트는 재료대체 되돌리기 전용이고 다른 기능과 무관함(사용자 확인: "원래 쓰지 않는 기능"). 등록 취소 같은 별도 기능이 필요해지면 새 스펙으로 분리 |
| EC-03 | 테스트 스위트에 남아있는 substitution 관련 fixture/mock | `tests/test_substitution.py` 삭제, `test_recipe_search.py`/`test_pipeline.py`/`test_mock_client.py`/`test_intent_classifier.py`/`integration_scenario_test.py` 내 관련 케이스 제거 또는 "미분류로 처리됨" 기준으로 갱신 |

## How (파일별 변경)

1. **삭제**: `orchestration/substitution.py` (전체 — `apply_substitution()`, `cancel_substitution()`)

2. **`orchestration/recipe_search.py`**
   - `search_variant_recipe()`, `search_by_ingredient_content()`, `NOT_FOUND_MESSAGE` 삭제 (다른 호출부 없음 — 확인됨, 오직 `pipeline.py`의 재료대체 분기에서만 호출됨)

3. **`orchestration/pipeline.py`**
   - import에서 `search_variant_recipe`, `apply_substitution`, `cancel_substitution` 제거
   - `handle_utterance()`의 `if intent == "취소":`(173~174줄), `if intent == "재료대체":`(176~183줄) 분기 삭제
   - 함수 시그니처에서 `requested_ingredient`, `excluded_ingredient` 파라미터 삭제(더 이상 아무도 안 채움)
   - `조회` 분기의 `session["previous_recipe_id"] = None`(236줄) 삭제

4. **`orchestration/intent_classifier.py`**
   - `VALID_INTENTS`에서 `"재료대체"`, `"취소"` 제거
   - `_pick_intent()`의 EC-05 특수분기(147~152줄, `top_intent == "재료대체" and not context_recipe_id`) 삭제

5. **`orchestration/entity_extract.py`**
   - `extract_substitution_ingredients()` 삭제(파일 상단 설명 주석 중 관련 부분도 정리)

6. **`ui/dispatch.py`**
   - `_compute()` 백그라운드 job에서 `job["requested"]`/`job["excluded"]` 계산 블록(287~291줄) 삭제
   - `handle_utterance()` 호출부에서 `requested_ingredient=job["requested"], excluded_ingredient=job["excluded"]` 인자 삭제
   - `if intent == "재료대체":`(514~525줄), `if intent == "취소":`(527~535줄) 분기 삭제
   - `_INTENT_DISPLAY_LABEL`에서 `"취소": "취소"` 항목 삭제

7. **`ui/session.py`**
   - `"previous_recipe_id": None` 초기값 삭제

8. **`data/intent_examples/기준예문.csv`** (선택)
   - `재료대체`/`취소` 행 삭제 — 안 지워도 `VALID_INTENTS` 필터로 무시되지만, 죽은 데이터로 남기지 않으려면 같이 정리 권장

9. **테스트**
   - `tests/test_substitution.py` 삭제
   - `tests/test_recipe_search.py`, `tests/test_pipeline.py`, `tests/test_mock_client.py`, `tests/test_intent_classifier.py`, `tests/integration_scenario_test.py`에서 재료대체/취소 관련 케이스 제거 또는 "미분류로 처리됨" 기준으로 갱신

## AC (Given-When-Then)

**AC-01 · VALID_INTENTS에서 제거됨**
- GIVEN: `intent_classifier.py` 로드
- WHEN: `VALID_INTENTS`를 확인함
- THEN: `"재료대체"`, `"취소"`가 포함되어 있지 않다

**AC-02 · 재료대체 발화가 재료대체로 분류될 수 없음**
- GIVEN: 조리 중(`context_recipe_id` 있음), "새우 빼줘" 같은 재료대체성 발화
- WHEN: `classify_intent()` 호출
- THEN: 반환된 `intent`가 `"재료대체"`일 수 없다(기준예문 자체가 로드되지 않으므로 구조적으로 불가능) — 미분류 또는 다른 의도로 분류됨

**AC-03 · handle_utterance가 재료대체/취소 intent를 처리하는 코드를 안 가짐**
- GIVEN: `pipeline.py` 소스
- WHEN: `handle_utterance()` 본문을 확인함
- THEN: `"취소"`, `"재료대체"`를 비교하는 분기가 존재하지 않는다

**AC-04 · 모듈 삭제 확인**
- GIVEN: 저장소 전체
- WHEN: `orchestration/substitution.py` 존재 여부를 확인함
- THEN: 파일이 존재하지 않는다

**AC-05 · 테스트 스위트 그린**
- GIVEN: 위 변경 전부 적용됨
- WHEN: `pytest`를 전체 실행함
- THEN: 실패 0건 (관련 테스트는 삭제/갱신 완료 상태)
