# Spec: 조회 실패 시 no_match 화면 제거 → 음성 안내 1회로 대체

## Why

- **페르소나**: 손이 자유롭지 않아 화면 대신 음성으로 요리명을 조회하는 사용자
- **상황**: "된장찌개 알려줘"처럼 말했는데 DB(`recipes`)에 없는 요리인 경우
- **문제**:
  1. 지금은 `no_match`라는 별도 화면(`ui/screens/register.py::screen_no_match()`)으로 전환되어 "새 레시피로 등록할래요"/"계속" 버튼이 뜨는데, 비로그인 사용자는 버튼을 눌러도 로그인 화면으로 다시 튕겨나가 혼란만 준다.
  2. 화면 전환 자체가 매번 발생해 "여기서 뭘 해야 하나" 판단 과정이 추가로 필요하다 — 음성 우선 사용자에게는 불필요한 인지 부담.
  3. `no_match` 전용 발화 핸들러(`handle_no_match()` — "초기"/"등록" 두 단어만 반응하는 좁은 창)가 별도로 존재해 유지보수 포인트가 하나 더 생긴다.
- **측정 지표**: 정량 지표 없음(주관적 흐름 단순화) — 완료 기준은 AC 통과 여부로 판단.

## Goal

- **해결 목표**: 조회 실패 시 화면 전환 없이 현재 화면(`start`)에 그대로 머무른 채, 음성 안내를 1회만 재생한다. 등록은 이후 사용자가 로그인 후 "레시피 등록"이라고 직접 말하는 기존 진입점(전역 `등록` 인텐트)으로만 이어진다.
- **성공 기준**:
  - 조회 실패 시 `st.session_state.screen`이 절대 바뀌지 않는다(`start` 유지).
  - 안내 음성 "등록되지 않은 레시피에요. 새로 등록을 원하시면 로그인 후 '레시피 등록'이라고 말씀해 주세요."가 정확히 1회 재생된다.
  - 안내 음성이 재생되는 동안 마이크 입력은 인식되지 않는다(기존 `_arm_tts_mute()`/`_mic_muted()` 그대로 재사용 — 재생 길이만큼 자동 차단, 새 메커니즘 불필요).
  - 실패한 조회는 `chat_log`에 남지 않는다 — 같은 요리를 반복해서 물어봐도 대화 기록이 쌓이지 않는다.
- **Out of Scope**:
  - 재료대체 실패 처리 — 재료대체 기능 자체를 폐기하므로 해당 없음(`docs/specs/remove_ingredient_substitution.md` 참고, 이 스펙과 별도로 진행).
  - "레시피 등록" 발화의 로그인 게이팅/등록 플로우 — 이미 구현되어 있음(`ui/dispatch.py::_block_register_if_not_logged_in()`, `intent_classifier.py`의 전역 `등록` 인텐트). 이번 스펙에서 안 건드림.
  - `pending_dish_name` 프리필(추정 요리명으로 등록 화면 미리 채우기) — 이번에 없앤다. 되살리는 건 별도 스펙.
  - `AGENTS.md`/PRD 등 제품 문서 갱신 — 이번 스펙 범위 밖, 최종 단계에서 한 번에 처리.

## What

**Happy Path**

1. 사용자가 `start` 화면에서 요리명을 발화한다("김치말이국수 알려줘").
2. `dispatch.py`가 `handle_utterance()`를 호출 → `pipeline.py`의 `조회` 분기가 DB에서 못 찾음 → `{"intent": "조회", "message": DISH_NOT_FOUND_MESSAGE}` 반환.
3. `dispatch.py`가 `chat_log`에 아무것도 남기지 않고, `goto()` 없이 `speak(새_안내_문구)`를 1회 호출한다.
4. `speak()` 재생 길이만큼 마이크가 자동으로 뮤트된다(`_arm_tts_mute()`, 기존 동작 그대로).
5. 재생이 끝나면 `start` 화면 그대로, 마이크가 재개되어 사용자가 바로 다른 요리명을 말할 수 있다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 연속으로 계속 없는 요리만 말함 | 매번 동일 안내 음성 재생, 누적/카운트 없음 |
| EC-02 | 기존 `no_match`처럼 "hidden=True로 캐싱 → 도착 화면이 재생" 패턴을 쓰지 않음 | 도착 화면이 없으므로 `speak()`를 `hidden=False`로 직접 호출해 그 자리에서 들려준다 — 재생 중 다른 이유로 rerun이 나도 이 호출을 다시 트는 로직은 없다(no_match의 캐시-재생 패턴과 다른 점, 의도적) |
| EC-03 | 비로그인 상태에서 조회 실패 | 로그인 여부와 무관하게 항상 같은 안내(안내 문구 자체에 "로그인 후"가 포함돼 있음) |
| EC-04 | 조회 실패 직후 사용자가 실제로 "레시피 등록"이라고 말함 | 이 스펙과 무관 — 기존 전역 `등록` 인텐트 경로로 그대로 처리됨(비로그인이면 `_block_register_if_not_logged_in()`이 다시 안내) |
| EC-05 | `ui/dispatch.py`의 재료대체 실패 경로(`match_type == "none"`, 현재 514~521줄) | 재료대체 기능 자체가 삭제되므로 이 경로 자체가 사라진다(`docs/specs/remove_ingredient_substitution.md`) — 이 스펙 구현 시점에 그 스펙이 아직 안 끝났다면, 일단 이 분기의 `goto("no_match")`도 같이 지우고 그 자리에서 기존 `NOT_FOUND_MESSAGE`를 그대로 `speak()`로 들려주는 임시 처리로 둔다 |

## How

**1. `orchestration/pipeline.py`**

```python
DISH_NOT_FOUND_MESSAGE = "등록되지 않은 레시피에요. 새로 등록을 원하시면 로그인 후 '레시피 등록'이라고 말씀해 주세요."
```

**2. `ui/dispatch.py`** — `intent == "조회"` 분기(현재 429~440줄)

기존:
```python
if "message" in result:  # DISH_NOT_FOUND_MESSAGE — 표준 데이터 밖(시나리오 D)
    st.session_state.chat_log.append(("user", text))
    st.session_state.pending_dish_name = dish_name_guess
    speak(result["message"], hidden=True)
    goto("no_match")
    return
```

변경 후:
```python
if "message" in result:  # DISH_NOT_FOUND_MESSAGE — 표준 데이터 밖(시나리오 D)
    speak(result["message"])
    return
```

(`chat_log` 기록 없음, `pending_dish_name` 없음, `goto()` 없음, `hidden=True` 아님 — 재생을 대신해줄 도착 화면이 없으므로 이번엔 직접 들려줘야 한다.)

**3. `ui/screens/register.py`**
- `screen_no_match()`, `handle_no_match()` 삭제.

**4. `app.py`**
- import 목록에서 `screen_no_match`, `handle_no_match` 제거.
- `SCREENS` 딕셔너리에서 `"no_match": screen_no_match` 항목 삭제.
- `elif screen == "no_match": ...` 분기(약 381~388줄) 삭제.

**5. `ui/session.py`**
- `pending_dish_name` 초기화 라인 삭제(다른 곳에서 더 안 쓰면).

**6. 테스트**
- `tests/test_pipeline.py`, `tests/integration_scenario_test.py` 등에서 `no_match` 화면 전환을 기대하는 케이스를 "같은 화면 유지 + 메시지만 반환"으로 갱신.

## AC (Given-When-Then)

**AC-01 · 조회 실패 시 화면 유지**
- GIVEN: 사용자가 `start` 화면에 있고 DB에 없는 요리명을 발화함
- WHEN: `handle_utterance()`가 `{"intent": "조회", "message": ...}`를 반환함
- THEN: `st.session_state.screen`은 그대로 `"start"`이고 `goto()`가 호출되지 않는다

**AC-02 · 새 안내 문구 1회 재생**
- GIVEN: 위와 동일 상황
- WHEN: `dispatch.py`가 결과를 처리함
- THEN: `speak()`가 정확히 "등록되지 않은 레시피에요. 새로 등록을 원하시면 로그인 후 '레시피 등록'이라고 말씀해 주세요."로 1회 호출된다(`hidden=False`)

**AC-03 · 재생 중 마이크 차단**
- GIVEN: 안내 음성이 `speak()`로 재생 중
- WHEN: 그 재생이 끝나기 전에 마이크 프레임이 들어옴
- THEN: `_mic_muted()`가 `True`를 반환해 해당 프레임이 발화로 처리되지 않는다(기존 로직 그대로 재사용됨을 확인)

**AC-04 · 대화 기록 미기록**
- GIVEN: 조회 실패가 발생함
- WHEN: 해당 턴이 끝남
- THEN: `st.session_state.chat_log`의 길이가 처리 전과 동일하다(user/ai 어느 쪽도 추가되지 않음)

**AC-05 · no_match 화면 도달 불가**
- GIVEN: 저장소 전체 코드
- WHEN: `goto("no_match")` 호출부를 검색함
- THEN: 한 곳도 없다 — `SCREENS` 딕셔너리에도 `"no_match"` 키가 존재하지 않는다
