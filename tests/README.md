# tests/ — 테스트

두 종류가 섞여 있다. pytest가 자동 수집하는 단위테스트와, 사람이 직접 실행하는 GPU 벤치마크·진단 스크립트.

## 단위테스트 (`pytest tests/`, 119개, GPU·DB 불필요)

| 파일 | 대상 |
|---|---|
| `conftest.py` | `src/`를 `sys.path`에 등록 |
| `fake_supabase.py` | 인메모리 Supabase 대체(`orchestration/mock_client.py` 재사용) |
| `test_pipeline.py` | 발화 라우팅, 단계 전이(다음/다시/이전, 1단계에서 이전 유지), 조회 실패 안내 |
| `test_intent_classifier.py` | threshold/margin 판정, 조리 중 조회·등록 무시 |
| `test_recipe_search.py` | 요리명 3단계 보정, 공백 무시·반복 축약, 소유자 필터 |
| `test_registration.py` | 등록 상태 기계, `owner_id` 없는 저장 거부, 용어 자동 태깅 |
| `test_auth.py` | 로컬 가입/로그인, 구글 로그인 행 재사용, 세션 토큰 |
| `test_my_recipes.py` | 목록/수정/삭제, 타인 레시피 접근 거부 |
| `test_entity_extract_llm.py` / `test_llm_infer.py` | 로컬 LLM 출력 파싱(모델은 mock) |
| `test_speaker_verify.py` | 화자검증 embed/verify/enroll(임베딩 mock), 관리자 진입 발화 감지 |
| `test_tts_pronunciation.py` | TTS 직전 텍스트 보정(겹받침 치환, 단계 번호 한글화, 종결 보정) |
| `test_mock_client.py` / `test_theme.py` | mock 폴백, 표시용 문자열 유틸 |

2026-09-10 기준 119개 전부 통과.

## 수동 실행 스크립트

| 파일 | 용도 | 요구 |
|---|---|---|
| `integration_scenario_test.py` | 시나리오 A~D + 반복 질의를 `handle_utterance()`로 순차 실행(31/31 PASS, 08-16) | 실제 Supabase |
| `tts_stt_roundtrip_test.py` | TTS 합성 → STT 재인식 CER. `--phase synthesize`/`transcribe` 분리 실행 | GPU, `HF_TOKEN` |
| `tts_cpu_inference_test.py` | TTS CPU/GPU 추론 속도, 5초 목표 판정 | qwen_tts |
| `test_ui.py` | STT→LLM→DB→TTS를 화면에서 단계별로 확인하는 Streamlit 앱(`streamlit run tests/test_ui.py`) | GPU |
| `test-audio/` | 수동 확인용 음성 샘플 |

개발 초반의 통합 테스트 체크리스트와 이슈 일지는 저장소에서 제외했다(요약은 `docs/decisions.md`).
