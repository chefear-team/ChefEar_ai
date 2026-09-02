# src/orchestration/ — 담당: 김승욱 (A, 오케스트레이션/통합 주관)

기준일: 2026-08-28

## 이 폴더가 하는 일

의도분류·조리순서 조회·신규등록·관리자 승인·DB 연결을 담당하는 순수 로직 계층. 대부분 LLM 없이 sentence-transformers 임베딩 유사도 + Supabase 실데이터 조회로 동작한다. **AGENTS.md 절대 원칙이 막는 건 "서비스 실행 중 외부 LLM API 호출"이지 로컬 LLM 자체가 아니다** — `entity_extract_llm.py`는 GPU 데스크탑 프로세스 안에 직접 로드한 로컬 LLM(EXAONE)을 쓰는 유일한 예외이고, 네트워크로 남의 서버에 텍스트를 보내지 않으므로 이 원칙에 걸리지 않는다(`docs/specs/llm_dish_name_extract.md` Why 참고). Streamlit 세션(`st.session_state`)을 함수 인자로 받는 형태라 Streamlit 없이도 dict만으로 테스트 가능.

**2026-08-27 팀 결정으로 제거된 것**: 재료 대체(`substitution.py` 삭제), 계정 로그인(`auth.py` 삭제), 익명 쿠키 개인화(`identity.py` 삭제). `docs/specs/remove_ingredient_substitution.md`, `docs/specs/remove_user_accounts.md` 참고.

## 파일별 상태 (확인: 2026-08-28)

| 파일 | 상태 | 역할 |
|---|---|---|
| `db.py` | 완성 | `get_client()` — Supabase 자격증명 없으면 자동으로 `mock_client.py`로 폴백. 프로세스당 client 하나만 재사용(캐싱이 실제로 히트하게) |
| `mock_client.py` | 완성 | 로컬 개발용 가짜 Supabase 클라이언트 |
| `intent_classifier.py` | 완성 | `classify_intent()` — `jhgan/ko-sroberta-multitask` 임베딩 유사도, `THRESHOLD`(0.5)+`MARGIN`(0.05) 판정. 의도 집합: 조회/등록/진행/재청취/이전/감탄사(+미분류) — 재료대체/취소는 2026-08-27 제거 |
| `recipe_search.py` | 완성 | `select_standard_recipe()`(`approved='Y'`이고 `api_standard`이거나 조회자 본인 소유(`owner_id`)인 행만 후보, 2026-09-02) / `extract_dish_name()`(완전일치→부분일치→편집거리 3단계 + 공백무시·반복축약 안전망) |
| `registration.py` | 완성 | `register_recipe()`(다단계 세션) / `save_recipe()`(최종 저장, 2026-09-02부터 `approved='Y'`로 즉시) / `update_recipe()`(마이레시피 수정) / `delete_recipe()`(관리자 삭제용) |
| `speaker_verify.py` | **신규(2026-08-28)** | 관리자 화자검증(ECAPA-TDNN, CPU) — `embed()`/`verify()`/`enroll()`/`remove_admin()`. 성문은 Supabase가 아니라 로컬 파일(`data/admin_voiceprints.json`)에 저장 |
| `load_data.py` | 완성 | CSV → Supabase 적재 CLI. `python src/orchestration/load_data.py --csv <경로> [--dry-run]` |
| `pipeline.py` | 완성 | `get_precomputed_steps`/`get_current_step`/`advance_step`/`manual_fallback` + `handle_utterance()`(STT 텍스트 → `classify_intent()` → 의도별 라우팅 → 응답, `app.py`가 호출할 최종 진입점) |
| `entity_extract.py` | **죽은 코드** | 자유발화에서 요리명을 뽑는 규칙 기반 v1(`extract_dish_name`, 접미사 rstrip 방식). 원래는 `app.py`가 호출했지만, `recipe_search.py::extract_dish_name()`(편집거리 보정 포함)과 `entity_extract_llm.py`(로컬 LLM)로 완전히 대체돼 지금은 어디서도 호출되지 않는다. 재료명 추출 함수(`extract_substitution_ingredients`)는 재료대체 기능과 함께 삭제됨 |
| `entity_extract_llm.py` | 완성 | 요리명 추정 + 등록 의도 판단을 로컬 LLM(EXAONE-3.5-2.4B-Instruct, `../llm/infer.py`)으로 한 번에 처리 — `extract_intent_llm(text) -> {"dish_name": str\|None, "wants_register": bool}`. 실패/형식오류/불확실 응답이면 안전한 기본값으로 폴백(지어내지 않음). 상세: `docs/specs/llm_dish_name_extract.md`, `../llm/README.md` |

## 소유자 전용 조회 (2026-09-02, `docs/specs/private_recipe_visibility.md`) — 관리자 승인 대체

`user_custom`(신규 등록)은 이제 `save_recipe()`가 저장 시점에 바로 `approved='Y'`로 넣는다(관리자 승인 대기 없음). 대신 `select_standard_recipe()`가 `owner_id`(조회자, `ui.session.get_owner_id()`)를 받아서, `api_standard`가 아닌 `user_custom` 행은 "조회자 본인이 등록한 것"일 때만 후보로 본다 — 다른 사용자·비로그인 조회자에게는 안 보인다. 등록 화면(`ui/screens/register.py::screen_register_dish_name()`)도 로그인 필수로 바뀌어서, owner_id 없는(비로그인) `user_custom`이 새로 생기지 않는다.

`recipes.approved`('Y'/'N') 컬럼 자체와 `src/ui/screens/admin.py`의 승인/삭제 워크플로우(`docs/specs/admin_recipe_approval.md`)는 코드 그대로 남아있지만, 이제는 **이 스펙 이전에 등록된 레거시 `approved='N'` 행**을 처리할 때만 쓰인다 — 새 행은 이 상태를 거치지 않는다. `select_standard_recipe()`는 그런 레거시 행만 있으면 여전히 `{"pending": True}`를 돌려줘 "심사 중"이라고 안내한다(`PENDING_MESSAGE`).

## 진행 방법

1. `.env`에 `SUPABASE_URL`/`SUPABASE_KEY`를 채우면 코드 수정 없이 mock → 실제 DB로 자동 전환된다(`db.py` docstring 참고).
2. `data/standard/`의 표준 레시피 CSV를 `load_data.py --csv`로 적재한다(현재 DB엔 60,196건 적재 완료, `../../db/README.md` 참고).
3. `pipeline.py`의 `handle_utterance(session, utterance, ...)`가 `app.py`에서 호출할 최종 진입점이다. `classify_intent()`는 의도만 분류하고 요리명 같은 세부 정보(entity)는 추출하지 않으므로, 조회 의도의 `dish_name`은 호출부가 `extract_intent_llm()`으로 미리 채워 넘긴다.
4. 관리자 페이지를 쓰려면 `.env`에 `ADMIN_ACCESS_TOKEN`(1차 게이트) + `ADMIN_ENROLL_TOKEN`(목소리 등록용)을 채우고, `/enroll?enroll_key=<토큰>`에서 관리자 목소리를 먼저 등록해야 한다.

## 테스트

`tests/test_pipeline.py`, `test_intent_classifier.py`, `test_recipe_search.py`, `test_registration.py`, `test_mock_client.py`, `test_speaker_verify.py` — 전부 `FakeSupabaseClient`(또는 목킹된 화자검증 모델)로 격리해서 검증한다. `test_substitution.py`/`test_identity.py`는 해당 기능 삭제와 함께 제거됐다. 실제 Supabase(PostgREST) 연동 자체는 자격증명 확보 후 별도로 확인해야 한다(mock으로는 잡히지 않음).

```
pytest tests/
```

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 6~7장(데이터모델·인터페이스), `docs/specs/admin_recipe_approval.md`, `docs/specs/admin_voice_2fa.md`. 코드 자체 주석이 각 문서 절 번호를 인용하고 있어 함수별 상세 근거는 각 파일 docstring이 더 빠르다.
