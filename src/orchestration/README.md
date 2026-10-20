# src/orchestration/ — 오케스트레이션 로직

의도분류·레시피 검색·단계 전이·등록·DB 연결을 담당하는 계층. 세션을 dict 인자로 받는 형태라 웹·서버 없이 dict만으로 테스트한다(`tests/`). API 서버(`server/chefear_api/service.py`)가 이 계층을 그대로 호출한다.

| 파일 | 주요 함수 | 역할 |
|---|---|---|
| `pipeline.py` | `handle_utterance()`, `advance_step()`, `get_precomputed_steps()`, `manual_fallback()` | 발화 하나를 의도별로 라우팅, 다음/다시/이전 상태 전이(1단계에서 이전은 유지), 조회 실패 안내 |
| `intent_classifier.py` | `classify_intent()` | `jhgan/ko-sroberta-multitask` 임베딩 코사인 유사도. 기준 예문 110개(`data/intent_examples/기준예문.csv`), threshold 0.5 + margin 0.05. 의도: 조회/등록/진행/재청취/이전/감탄사/미분류 |
| `entity_extract_llm.py` | `extract_intent_llm()`, `extract_dish_name_llm()` | 로컬 LLM(EXAONE)으로 자유발화에서 요리명 후보와 등록 의도 추출. 실패 시 안전한 기본값. **리뉴얼 서비스 경로에서는 호출하지 않음**(정확도 A/B용으로 코드와 테스트만 유지) |
| `recipe_search.py` | `extract_dish_name()`, `select_standard_recipe()`, `find_dish_name_ignoring_spaces()`, `find_dish_name_ignoring_repetition()`, `find_more_specific_containing_name()` | DB 실존 요리명으로 완전일치→부분일치→자모 편집거리 보정, 공백 무시·반복 축약 안전망. 표준 선정은 `api_standard` 또는 조회자 본인 소유(`owner_id`)만 후보 |
| `registration.py` | `register_recipe()`, `save_recipe()`, `update_recipe()`, `delete_recipe()` | 등록 상태 기계(요리명→재료→순서→확인). `save_recipe()`는 `owner_id` 없으면 거부, `approved='Y'`로 즉시 저장, 순서 텍스트에 용어 자동 태깅 |
| `term_dict.py` | `resolve_for_tts()`, `resolve_for_display()`, `auto_tag_terms()` | `[TERM:용어]` 태그를 음성용(설명 삽입)/화면용(용어만)으로 변환, 사용자 등록 텍스트에 자동 태깅 |
| `db.py` / `mock_client.py` | `get_client()`, `load_env()` | Supabase 클라이언트. 자격증명 없으면 인메모리 mock으로 자동 폴백 |
| `load_500_recipes.py` | — | 500건 CSV → `recipes`/`recipe_steps` 적재(현재 데이터). 사전에 `db/migrate_500_recipes_step1_truncate.sql` 실행 |
| `load_data.py` | — | 초기 60,282건 적재 스크립트(09-01 이후 사용 안 함, 이력 보존) |

## 리뉴얼에서 제거한 것

로컬 계정(`auth.py`), GPU 프로세스 워커 풀(`gpu_worker_pool.py`), 관리자 화자검증(`speaker_verify.py`)은 서버리스 구조에서 쓰이지 않아 제거했다. 계정은 Supabase Auth, 추론은 Modal GPU 함수가 맡는다. 제거 이유와 이전 구조(GIL 때문에 프로세스 풀을 썼던 이력)는 `docs/decisions.md`와 README 6장 ③·⑦.

## 외부 LLM API 원칙

이 폴더에서 LLM을 쓰는 곳은 `entity_extract_llm.py`뿐이고, `src/llm/infer.py`가 직접 로드한 EXAONE을 호출한다. 네트워크로 외부 서버에 텍스트를 보내지 않는다. 서비스 경로에서는 이 모듈을 호출하지 않는다.
