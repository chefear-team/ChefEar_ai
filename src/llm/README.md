# src/llm/ — 로컬 LLM (EXAONE)

`LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`를 `transformers.AutoModelForCausalLM`으로 GPU 워커 프로세스에 직접 로드해, 자유발화에서 요리명 후보를 뽑고 "등록하고 싶다"는 의도를 판단하는 데 쓴다. `src/orchestration/entity_extract_llm.py`가 이 모듈을 얇게 감싼다.

| 함수 | 역할 |
|---|---|
| `load_llm()` | 모델·토크나이저 1회 로드(캐시) |
| `generate_response(prompt)` | 텍스트 생성 |
| `generate_json(prompt)` | 코드 펜스를 벗기고 JSON으로 파싱. 파싱 실패 시 `None` |

## 외부 API 배제 원칙과의 관계

과제 요건이 막는 것은 OpenAI·Anthropic·Gemini·Groq처럼 인터넷 너머 남의 서버에서 추론이 일어나는 경우다. 여기서는 가중치를 팀 GPU에 올려 프로세스 안에서 추론하므로 완전한 로컬이다. Ollama 같은 별도 서버도 두지 않는다.

## 사용 규칙

- LLM 출력은 **후보**일 뿐이고 최종 요리명은 항상 DB 실존 이름과 매칭해 결정한다(`recipe_search.py`).
- 모델이 JSON 뒤에 말을 덧붙이는 경우가 있어 `generate_json()`이 펜스·잡음을 정리한다. 그래도 실패하면 "요리명 없음, 등록 의도 아님"으로 처리한다.
- 라이선스는 EXAONE AI Model License 1.1-NC(비상업). 수업 과제라 조건을 충족한다.

테스트: `tests/test_llm_infer.py`, `tests/test_entity_extract_llm.py`(모델 mock).
