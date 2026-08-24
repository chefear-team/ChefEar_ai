# src/orchestration/ — 담당: 김승욱 (A, 오케스트레이션/통합 주관)

## 이 폴더가 하는 일

의도분류·조리순서 조회·재료대체·신규등록·DB 연결을 담당하는 순수 로직 계층. 대부분 LLM 없이
sentence-transformers 임베딩 유사도 + Supabase 실데이터 조회로 동작한다. **AGENTS.md 1.5 원칙이
막는 건 "서비스 실행 중 외부 LLM API 호출"이지 로컬 LLM 자체가 아니다** — `entity_extract_llm.py`
(2026-08-20 추가)는 GPU 데스크탑 프로세스 안에 직접 로드한 로컬 LLM(EXAONE)을 쓰는 유일한
예외이고, 네트워크로 남의 서버에 텍스트를 보내지 않으므로 이 원칙에 걸리지 않는다(`docs/specs/llm_dish_name_extract.md`
Why 참고). Streamlit 세션(`st.session_state`)을 함수 인자로 받는 형태라 Streamlit 없이도 dict만으로 테스트 가능.

## 파일별 상태 (확인: 2026-08-21)

| 파일 | 상태 | 역할 |
|---|---|---|
| `db.py` | 완성 | `get_client()` — Supabase 자격증명 없으면 자동으로 `mock_client.py`로 폴백 |
| `mock_client.py` | 완성 | 강사 체크리스트 4번용 가짜 Supabase 클라이언트, 문서 5장 시나리오 시드 데이터 포함 |
| `identity.py` | 완성 | 쿠키 기반 익명 UUID(`get_or_create_anon_id`), FR-08 |
| `intent_classifier.py` | 완성 | `classify_intent()` — `jhgan/ko-sroberta-multitask` 임베딩 유사도, `THRESHOLD` 상수 |
| `recipe_search.py` | 완성 | `select_standard_recipe` / `search_variant_recipe` / `search_by_ingredient_content` |
| `substitution.py` | 완성 | `apply_substitution` / `cancel_substitution`(롤백, AC-11) |
| `registration.py` | 완성 | `register_recipe`(다단계 세션) / `save_recipe`(최종 저장) |
| `load_data.py` | 완성 | CSV → Supabase 적재 CLI. `python src/orchestration/load_data.py --csv <경로> [--dry-run]` |
| `pipeline.py` | 완성 | `get_precomputed_steps`/`get_current_step`/`advance_step`/`manual_fallback`(7.4/7.1.1) + `handle_utterance()`(STT 텍스트 → `classify_intent()` → 의도별 라우팅 → 응답, `app.py`가 호출할 최종 진입점) |
| `entity_extract.py` | 신규(2026-08-19), **재료명 추출만 `app.py`가 사용 중** | 자유발화에서 요리명/재료명을 뽑는 규칙 기반 v1(`extract_dish_name`/`extract_substitution_ingredients`) — `classify_intent()`는 의도만 분류하고 세부 정보는 안 뽑아서, 원래 `app.py`가 채워야 했던 부분. 정규식/토큰 분리만 씀. **`extract_dish_name()`은 2026-08-20부로 `app.py`가 더 이상 안 부름**(아래 `entity_extract_llm.py`로 교체), 파일 자체는 그대로 남아있음(회귀 비교용) |
| `entity_extract_llm.py` | **신규(2026-08-20)** | 요리명 추출을 로컬 LLM(EXAONE-3.5-2.4B-Instruct, `../llm/infer.py`)으로 하는 신규 경로 — `extract_dish_name_llm(text) -> str \| None`. `entity_extract.py`의 규칙 기반 한계(문형 밖 표현을 놓침)를 보완. 실패/형식오류/불확실 응답이면 전부 `None`(지어내지 않음). `app.py`가 요리명 추출에 이 함수를 사용(재료명 추출은 여전히 `entity_extract.py`). 상세: `docs/specs/llm_dish_name_extract.md`, `../llm/README.md` |

## 진행 방법

1. `.env`에 `SUPABASE_URL`/`SUPABASE_KEY`를 채우면 코드 수정 없이 mock → 실제 DB로 자동 전환된다(`db.py` docstring 참고).
2. `data/standard/`의 표준 레시피 CSV를 `load_data.py --csv`로 적재한다(현재 DB엔 LLM 생성 조리과정 60,196건 적재 완료, `../../db/README.md` 참고).
3. `pipeline.py`의 `handle_utterance(session, utterance, ...)`가 `app.py`에서 호출할 최종 진입점이다. 주의할 점: `classify_intent()`는 의도만 분류하고 요리명·재료명 같은 세부 정보(entity)는 추출하지 않는다(이 프로젝트에 그런 NLU 로직이 따로 없음) — 그래서 `조회`(`dish_name`)/`재료대체`(`requested_ingredient`/`excluded_ingredient`)/`등록`(`registration_step`/`registration_value`) 의도는 그 값을 호출부(`app.py`)가 직접 채워서 넘겨야 한다.
4. STT(`src/stt/infer.py`)는 모델 확정·평가 완료, 다만 배포용 단일 발화 함수(`stt_transcribe()`, faster-whisper 변환)는 아직 정리 필요([../stt/README.md](../stt/README.md) 참고). TTS(`src/tts/infer.py`)는 `tts_synthesize(text) -> (waveform, sample_rate)`가 작성 완료됐다([../tts/README.md](../tts/README.md) 참고) — `handle_utterance()`의 텍스트 응답을 이 함수에 넘기고 반환값을 `st.audio()`로 재생하면 된다.

## 테스트

`tests/test_pipeline.py`, `test_intent_classifier.py`, `test_recipe_search.py`, `test_registration.py`,
`test_substitution.py`, `test_identity.py`, `test_mock_client.py` — 전부 `FakeSupabaseClient`로 격리해서 검증한다.
실제 Supabase(PostgREST) 연동 자체는 자격증명 확보 후 별도로 확인해야 한다(mock으로는 잡히지 않음).

```
pytest tests/ -k "not tts_cpu_inference"
```

2026-08-18 재확인(main 브랜치): 50/50 PASS. `pipeline.py`의 `match_type: "none"` 필드는 main에
이미 병합 완료됐고(`tests/integration_scenario_test.py` C-1로 실제 Supabase 연결 재확인, 31/31 PASS),
main·seunguk 브랜치 `pipeline.py` diff 없음 — 병합 회귀 위험은 해소됐다. 다만 이 필드를 검증하는
pytest는 여전히 없다(`test_substitution.py`는 `apply_substitution()` 자체만 봄, 실제 발견은
`tests/integration_test.md` 시나리오 C 수동 테스트에서 나왔다) — 향후 다른 브랜치에서 이 필드가
조용히 빠지는 걸 pytest로는 못 잡으므로 회귀 테스트 추가가 필요하다.

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 7.1~7.6(함수 목록), AC-01~13. 코드 자체 주석이 각 문서 절 번호를 인용하고 있어
함수별 상세 근거는 각 파일 docstring이 더 빠르다(문서 재검색 불필요).
