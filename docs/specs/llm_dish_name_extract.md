# Spec — 로컬 LLM 기반 요리명 추출

## Why

- **페르소나**: 요리 경험이 거의 없어 화면을 보지 않고 음성만으로 레시피를 진행하는 사용자
- **상황**: 사용자가 자유발화로 요리명을 말하면(예: "된장찌개 어떻게 만들어", "오늘 김치볶음밥 할래") STT 텍스트에서 요리명만 뽑아 `recipes.dish_name`과 매칭해야 다음 단계(조리순서 조회)로 넘어갈 수 있다.
- **문제**:
  1. 현재 `extract_dish_name()`(`src/orchestration/entity_extract.py`)은 고정 접미사 목록을 `rstrip`으로 잘라내는 규칙 기반이라, 파일 자체에 "v1 한계: 위 문형 밖의 표현은 놓칠 수 있다"고 명시돼 있음.
  2. 문형이 다르거나(예: 접미사 목록에 없는 표현) 조사가 붙는 방식이 다르면 요리명 추출이 실패하고, 그 뒤 `dish_name` 매칭 자체를 시도할 수 없음.
- **측정 지표**: TBD — 정규식 버전 대비 요리명 인식 성공률 실측 후 팀 확정 필요(아직 baseline 수치 없음, 지어내지 않음).

## Goal

- **해결 목표**: 로컬 LLM(EXAONE-3.5-2.4B-Instruct, GPU 데스크탑에 `transformers`로 직접 로드)으로 STT 텍스트에서 요리명 후보를 추출하고, `app.py`의 실제 발화 처리 흐름(`process_utterance()`)에 연결해 **STT → LLM 추출 → `dish_name` 매칭/`recipe_steps` 조회 → TTS 음성 출력**까지 실제로 동작하는 하나의 파이프라인으로 완성한다.
- **성공 기준**: TBD — 실측 데이터 확보 후 정량 기준(정확도, 응답속도 등) 확정 필요. 최소 조건으로 다음은 확정: 모델이 형식을 어긴 응답을 하거나 로드/추론이 실패해도 `extract_dish_name_llm()` 자체는 예외 없이 `None` 반환하고 서비스가 죽지 않음.
- **Out of Scope**:
  - `entity_extract.py`의 기존 정규식 함수(`extract_dish_name()`, `extract_substitution_ingredients()`) 자체의 코드 변경 — 파일은 그대로 두고, `app.py`의 요리명 추출 호출 지점만 LLM 경로로 연결
  - ~~`docs/decisions.md`/`AGENTS.md`의 "로컬 LLM 허용" 문구 갱신~~ **해결(2026-08-21)**: 문서를 다시 확인해보니 로컬 LLM 사용은 이미 허용돼 있었고(AGENTS.md 1.5 원칙은 외부 API 호출만 금지, 로컬 추론은 대상 아님), 강사님도 로컬 LLM 사용을 추천했음을 팀이 확인함 — 더 이상 보류 항목 아님
  - 오픈라우터(OpenRouter) 등 외부 LLM API의 런타임 호출 — **2026-08-20 재확인**: OpenRouter API 키 사용은 실제 추론이 OpenRouter 클라우드 서버에서 일어나 AGENTS.md 1.5 원칙("외부 LLM API 런타임 호출 금지")에 해당하므로 채택하지 않음. 모델 탐색 용도로만 썼고 런타임엔 쓰지 않음. (강사가 대면으로 "오픈라우터를 쓰라"고 언급했다는 회고가 있었으나, 이 문서 작성 시점엔 팀 내 확인이 안 된 상태라 AGENTS.md에 이미 명시된 "외부 LLM API 금지" 원칙을 기준으로 판단함 — 강사 확인 후 뒤집힐 수 있는 항목)

## What

**Happy Path**
1. 사용자 발화 → STT 텍스트 확보 (`stt.infer.stt_transcribe`, 기존 경로)
2. `app.py`의 `process_utterance()`가 STT 텍스트를 `extract_dish_name_llm(text)`(`src/orchestration/entity_extract_llm.py`, 신규)에 전달
3. 내부적으로 `src/llm/infer.py`가 GPU 데스크탑 프로세스 안에 직접 로드된 EXAONE-3.5-2.4B-Instruct(`transformers.AutoModelForCausalLM`)로 추론
4. LLM이 요리명 후보 문자열(또는 "없음")을 반환
5. 후보 문자열을 기존 `recipe_search.py`의 `dish_name` 매칭 함수에 그대로 전달 (신규 코드 없음, 기존 경로 재사용)
6. 매칭된 `recipes.id`(UUID)로 `pipeline.get_precomputed_steps(recipe_id)` 호출 → `recipe_steps` 조회 (기존 경로 재사용)
7. 조회된 조리순서 텍스트를 기존 `speak()`(`tts.infer.tts_synthesize`, `src/app.py:120-123`)로 넘겨 음성으로 출력 — 신규 코드 없음, 기존 TTS 경로 재사용

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 모델 로드/추론 자체가 실패(GPU 메모리 부족, 모델 파일 없음 등) | 설정 문제이므로 예외를 그대로 올려서 개발 중 바로 드러나게 함(`generate_response`/`load_llm`) — 단, 이게 실제 서비스 중 발생하면 EC-05로 이어짐 |
| EC-02 | LLM이 "요리명 없음"으로 응답(잡담/다른 의도 발화) | `None` 반환, 그럴듯한 요리명을 지어내지 않음(AGENTS.md 원칙과 동일한 정직성 유지) |
| EC-03 | LLM이 형식을 어긴 응답(JSON 파싱 실패 등) | 파싱 실패 시 `None` 반환 + 로그, 서비스는 죽지 않음(`generate_json`) |
| EC-04 | LLM이 추출한 문자열이 `dish_name`과 매칭 안 됨(존재하지 않는 요리) | 기존 매칭 실패 처리 경로 그대로 사용(신규 로직 없음) |
| EC-05 | `app.py` 실사용 중 EC-01(로드/추론 실패)이 발생 | 아직 미해결 — `process_utterance()`가 `extract_dish_name_llm()` 호출을 try/except로 감싸지 않고 있어서, 실제 배포 전에 `speak()`의 실패 처리(EC-05, 화면엔 표시하고 음성만 실패 알림)와 같은 패턴으로 보완이 필요함(TODO, 실제 GPU 배포/테스트 시 확정) |

## How

```
src/llm/infer.py 내부 (GPU 데스크탑 프로세스 안, 네트워크 호출 없음)

model = AutoModelForCausalLM.from_pretrained(
    "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
    trust_remote_code=True, device_map="cuda:0", dtype=torch.bfloat16,
)
tokenizer.apply_chat_template([...]) -> model.generate(...) -> 텍스트 디코딩 -> json.loads()

기대 출력(모델이 생성하는 텍스트를 JSON으로 파싱, 예시):
{ "dish_name": "된장찌개" }   // 요리명 있음
{ "dish_name": null }         // 요리명 없음(잡담 등)
```

- 모델: `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct` (HF 공식 리포, `trust_remote_code=True` 필요)
- 배포: GPU 데스크탑(RTX 5070) 프로세스 안에 직접 로드 — 별도 서버/네트워크 계층 없음(2026-08-20, Ollama 검토 후 폐기 — 팀이 임의로 프레임워크를 정하지 말고 사용자가 지정한 방식을 따르기로 함)
- `src/llm/infer.py`: `load_llm()`(지연 로드+전역 캐시, `tts/infer.py`의 `load_tts_model()`과 동일한 패턴) / `generate_response(prompt)` / `generate_json(prompt) -> dict | None`
- `src/orchestration/entity_extract_llm.py`: `extract_dish_name_llm(text: str) -> str | None` — `llm/infer.py`의 `generate_json()`을 얇게 감싸는 함수, `entity_extract.py`와 완전히 분리된 별도 파일
- 환경변수: `LLM_MODEL_REPO`(기본값 `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`) — `tts/infer.py`의 `HF_TTS_MODEL_REPO` 패턴과 동일
- `app.py` 연결 지점: `process_utterance()`(`src/app.py:209-292`) 내 기존 `extract_dish_name()` 호출부(`src/app.py:215`)를 `extract_dish_name_llm()`으로 교체 완료
- 의존성: 이 저장소에 이미 고정된 `transformers==4.57.3`(requirements-main.txt/requirements-stt.txt, STT 학습용으로 확정된 버전)을 그대로 재사용 — 새 의존성 추가 없음. **주의(2026-08-21 실측)**: `transformers>=5.0`이 깔린 venv에서 로드하면 EXAONE 원격 코드의 `_tied_weights_keys`가 구버전 형식(리스트)이라 v5의 tied-weights 처리(딕셔너리 기대, `modeling_utils.py`의 `get_expanded_tied_weights_keys()`)와 안 맞아서 `AttributeError`로 로드 자체가 깨짐 — 새 venv를 팔 땐 반드시 `transformers==4.57.3`으로 고정할 것(`requirements-main.txt` 그대로 설치하면 자동으로 맞음)
- 오류 처리 경계: `generate_response()`/`load_llm()`은 로드·추론 실패를 예외로 그대로 올린다(설정 문제는 개발 중 바로 드러나야 함). `generate_json()`은 그 위에서 "모델이 JSON 형식을 어긴 경우"만 잡아서 `None`으로 바꾼다. **EC-05 참고**: `process_utterance()`가 `extract_dish_name_llm()` 호출을 아직 try/except로 감싸지 않아서, 로드·추론 자체가 실패하면 지금은 `app.py`까지 예외가 그대로 올라간다 — 실제 GPU 배포/테스트 후 보완 필요(TODO)

## AC (Given-When-Then)

**AC-01 · 정상 발화에서 요리명 추출**
- GIVEN: GPU 데스크탑에 EXAONE 모델이 정상 로드됨
- WHEN: `extract_dish_name_llm("된장찌개 어떻게 만들어")` 호출
- THEN: `"된장찌개"` 문자열 반환 (또는 팀이 합의한 정규화 형태), 예외 발생 없음

**AC-02 · 요리명이 없는 발화**
- GIVEN: GPU 데스크탑에 EXAONE 모델이 정상 로드됨
- WHEN: 요리와 무관한 발화(예: "잠깐 멈춰줘") 전달
- THEN: `None` 반환, 임의의 요리명을 지어내지 않음

**AC-03 · 모델이 형식을 어긴 응답을 했을 때 안전한 폴백**
- GIVEN: 모델이 JSON이 아닌 텍스트를 생성함
- WHEN: `extract_dish_name_llm(text)` 호출
- THEN: 예외 없이 `None` 반환, 호출부(app.py)가 크래시하지 않음(`generate_json()` 단위 테스트로 검증됨, `tests/test_llm_infer.py`)

**AC-04 · 기존 dish_name 매칭 파이프라인과의 연동**
- GIVEN: `extract_dish_name_llm()`이 유효한 요리명 문자열을 반환
- WHEN: 그 문자열을 기존 `recipe_search.py`의 매칭 함수에 전달
- THEN: 정규식 경로(`extract_dish_name()`)가 만들어내는 문자열과 동일한 방식으로 `dish_name` 매칭 및 `recipe_steps` 조회까지 이어짐(신규 코드 변경 없이 기존 경로 그대로 동작)

**AC-05 · STT→LLM→DB→TTS 전체 파이프라인 동작**
- GIVEN: GPU 데스크탑에 EXAONE 모델이 정상 로드됐고, 발화된 요리명이 `recipes.dish_name`에 존재함
- WHEN: 사용자가 마이크로 요리명을 말하고 `process_utterance()`가 실행됨
- THEN: STT 텍스트 → `extract_dish_name_llm()` → `dish_name` 매칭 → `recipe_steps` 조회 → `speak()`(TTS)로 조리순서가 음성 출력됨
- **부분 검증(2026-08-21 갱신)**: 실제 GPU 데스크탑(RTX 5070, 전용 venv `~/.venvs/chefear`)에서 `load_ct2_model()`(STT)·`load_llm()`(EXAONE)·`load_tts_model()`(TTS)·`get_client()`(DB)를 순서대로 직접 로드해서 넷 다 정상 동작 확인함(각각 7.4s/6.6s/13.7s, DB는 즉시). **다만 이건 모델 로드까지만 확인한 것** — 실제 마이크 발화 → `process_utterance()` → `extract_dish_name_llm()` → `dish_name` 매칭 → `recipe_steps` 조회 → TTS 출력까지 이어지는 전체 흐름(이 AC가 원래 요구하는 것)은 아직 미검증. `generate_json()`의 파싱 로직은 모킹으로 검증됨(`tests/test_llm_infer.py`, `tests/test_entity_extract_llm.py`). `tests/test_ui.py`(`streamlit run tests/test_ui.py` 또는 `./run_local.sh`)로 실제 발화 업로드까지 확인 필요
