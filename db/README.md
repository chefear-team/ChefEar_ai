# db/ — Supabase 스키마

## 이 폴더가 하는 일

Supabase에 수동으로 실행할 DDL(`schema.sql`) 하나만 담는다. `supabase-py`는 SELECT/INSERT/UPDATE/DELETE
같은 데이터 조작만 가능하고 테이블 생성 문법(DDL)은 실행할 수 없어서, 이 파일은 파이썬 코드가 아니라
사람이 Supabase 대시보드 SQL Editor에 직접 붙여넣고 실행하는 용도다. 별도 마이그레이션 도구는 안 쓴다.

## 현재 상태 (확인: 2026-08-28)

`schema.sql` 완성됨 — 테이블 3개(`recipes`/`recipe_steps`/`users`, 아래 참고). Supabase 프로젝트 생성 완료, `schema.sql` 실행 완료(RLS 켠 상태), `.env`에 자격증명 연결 확인 완료.

- `recipes`: 레시피 1건당 1행. `source` 컬럼은 `api_standard`/`user_custom`만 허용(check 제약). `origin_id`는 자기참조(user_custom이 어떤 표준 레시피 기반인지). `external_id`(원본 CSV RCP_SNO), `servings`(인분수) 컬럼 포함.
  - **`owner_id`**: 2026-09-01 로그인 재도입으로 다시 사용 중 — 신규 `user_custom`은 등록자 id 필수(`save_recipe()`가 `None`이면 저장 거부). 비로그인 신규 행은 생기지 않는다. 이 스펙 이전 레거시 `NULL` 행은 누구에게도 조회 노출하지 않고 관리자 페이지에서만 처리한다.
  - **`approved`('Y'/'N')**: 2026-09-02부터 신규 `user_custom`은 즉시 'Y'로 저장되고, 공개 범위는 `owner_id`(본인만 조회)로 가른다. 'N'은 이 스펙 이전 레거시 승인 대기 행을 걸러내는 역할로만 남는다. `api_standard`는 적재 시점에 항상 'Y'.
- `recipe_steps`: 레시피 1건당 여러 행(단계별). `(recipe_id, step_number)` 복합 기본키, `on delete cascade`로 레시피 삭제 시 단계도 같이 삭제됨
- `users`(2026-08-22 추가, 2026-09-01 재도입): 로컬/구글 로그인 계정. `user_id_hash`(PK, sha256) / `user_id`(표시 id) / `auth_provider` / `google_sub` / `session_token_hash` 등. RLS는 켜져 있으나(`schema.sql` 하단), 소유자 격리는 앱 코드 필터로 하며 service_role 키는 RLS를 우회하므로 키 관리 주의.

인덱스 3개(`dish_name`, `source`, `owner_id`) + `uq_recipes_dish_name_standard`(표준 레시피 요리명 유니크) 포함. `owner_id` 인덱스는 지금은 항상 null인 컬럼을 대상으로 하므로 사실상 안 쓰인다.

**관리자 성문(voiceprint)은 이 DB가 아니라 로컬 파일에 저장된다** — `data/admin_voiceprints.json`(ECAPA-TDNN 임베딩, `src/orchestration/speaker_verify.py`). 관리자가 소수라 별도 테이블을 만들지 않았다.

### 데이터 적재 완료 (2026-08-16)

`src/orchestration/load_data.py`로 `recipes`(`api_standard`) 60,196건 + `recipe_steps` 357,938건 적재 완료.

요리명·재료·조회수 등 메타데이터는 만개의레시피 원본 CSV(60,282건, 실물 확보 완료) 기준.
**조리과정(`COOKING_STEPS`) 텍스트는 LLM(ChatGPT)이 작성**해서 채워 넣었다 — 원본 CSV 나머지
필드는 실데이터고, 조리 단계 서술만 LLM 생성이라는 뜻. 내용 검토 결과 조리법 자체는 사람마다
표현이 달라도 무방한 수준이라 실사용에 문제없는 걸로 확인됨.

## 진행 방법

1. Supabase 프로젝트 생성 → SQL Editor에 `schema.sql` 내용 그대로 붙여넣고 실행
2. `.env`에 `SUPABASE_URL`/`SUPABASE_KEY` 채우기 → `src/orchestration/db.py`의 `get_client()`가
   자동으로 mock 대신 이 진짜 DB를 씀(코드 수정 불필요)
3. 스키마를 바꿔야 하면 이 파일을 직접 수정한 뒤 다시 SQL Editor에서 수동 실행(마이그레이션 이력
   관리 없음 — 실행 순서를 팀이 직접 챙겨야 함)
4. `python src/orchestration/load_data.py --csv <경로>`로 표준 레시피 CSV 적재(`--dry-run`으로 먼저
   파싱만 검증 가능)

## 필요한 것 / 막힌 것

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 6.7(Supabase 테이블), `docs/decisions.md` OI-08(SQL 함수 대신 Python 필터).
