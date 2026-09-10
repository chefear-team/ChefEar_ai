# src/orchestration/ — 오케스트레이션 로직

의도분류·레시피 검색·단계 전이·등록·계정·GPU 워커 풀·DB 연결을 담당하는 계층. Streamlit 세션(`st.session_state`)을 dict 인자로 받는 형태라 Streamlit 없이 dict만으로 테스트한다(`tests/`).

| 파일 | 주요 함수 | 역할 |
|---|---|---|
| `pipeline.py` | `handle_utterance()`, `advance_step()`, `get_precomputed_steps()`, `manual_fallback()` | 발화 하나를 의도별로 라우팅, 다음/다시/이전 상태 전이(1단계에서 이전은 유지), 조회 실패 안내 |
| `intent_classifier.py` | `classify_intent()` | `jhgan/ko-sroberta-multitask` 임베딩 코사인 유사도. 기준 예문 110개(`data/intent_examples/기준예문.csv`), threshold 0.5 + margin 0.05. 의도: 조회/등록/진행/재청취/이전/감탄사/미분류 |
| `entity_extract_llm.py` | `extract_intent_llm()`, `extract_dish_name_llm()` | 로컬 LLM(EXAONE)으로 자유발화에서 요리명 후보와 등록 의도 추출. 실패 시 안전한 기본값 |
| `recipe_search.py` | `extract_dish_name()`, `select_standard_recipe()`, `find_dish_name_ignoring_spaces()`, `find_dish_name_ignoring_repetition()`, `find_more_specific_containing_name()` | DB 실존 요리명으로 완전일치→부분일치→자모 편집거리 보정, 공백 무시·반복 축약 안전망. 표준 선정은 `api_standard` 또는 조회자 본인 소유(`owner_id`)만 후보 |
| `registration.py` | `register_recipe()`, `save_recipe()`, `update_recipe()`, `delete_recipe()` | 등록 상태 기계(요리명→재료→순서→확인). `save_recipe()`는 `owner_id` 없으면 거부, `approved='Y'`로 즉시 저장, 순서 텍스트에 용어 자동 태깅 |
| `auth.py` | `signup_local()`, `login_local()`, `login_or_create_google()`, `create_session_token()`, `resolve_session_token()` | 로컬 가입(`sha256(username)`)·구글 로그인(`sha256(google_sub)`), 세션 토큰 |
| `gpu_worker_pool.py` | `submit_stt()`, `submit_tts()`, `submit_llm_extract()`, `submit_handle_utterance()`, `warmup()` | 별도 프로세스 워커(기본 3, `spawn`)에서 GPU 추론. `BrokenProcessPool` 시 풀 자동 재생성 |
| `term_dict.py` | `resolve_for_tts()`, `resolve_for_display()`, `auto_tag_terms()` | `[TERM:용어]` 태그를 음성용(설명 삽입)/화면용(용어만)으로 변환, 사용자 등록 텍스트에 자동 태깅 |
| `speaker_verify.py` | `embed()`, `verify()`, `enroll()`, `remove_admin()` | 관리자 화자검증(ECAPA-TDNN, CPU). 성문은 `data/admin_voiceprints.json` |
| `db.py` / `mock_client.py` | `get_client()`, `load_env()` | Supabase 클라이언트. 자격증명 없으면 인메모리 mock으로 자동 폴백 |
| `load_500_recipes.py` | — | 500건 CSV → `recipes`/`recipe_steps` 적재(현재 데이터). 사전에 `db/migrate_500_recipes_step1_truncate.sql` 실행 |
| `load_data.py` | — | 초기 60,282건 적재 스크립트(09-01 이후 사용 안 함, 이력 보존) |

## 왜 프로세스 풀인가

Streamlit은 세션마다 스레드를 쓰지만 모두 같은 GIL을 공유한다. STT·TTS·LLM 추론이 GIL을 오래 붙들면 상시 마이크의 오디오 드레인 스레드가 굶어 "Queue overflow"가 난다. 락을 여러 개로 쪼개도 GIL은 그대로라 재현됐고, 프로세스는 각자 GIL을 가지므로 워커 프로세스로 옮겼다. CUDA는 `fork`와 맞지 않아 `spawn`을 쓰고, 자식이 `src/`를 import할 수 있게 `PYTHONPATH`를 미리 넣는다.

## 외부 LLM API 원칙

이 폴더에서 LLM을 쓰는 곳은 `entity_extract_llm.py`뿐이고, `src/llm/infer.py`가 팀 GPU에 직접 로드한 EXAONE을 호출한다. 네트워크로 외부 서버에 텍스트를 보내지 않는다.
