# db/ — Supabase 스키마

## 이 폴더가 하는 일

Supabase에 수동으로 실행할 DDL(`schema.sql`) 하나만 담는다. `supabase-py`는 SELECT/INSERT/UPDATE/DELETE
같은 데이터 조작만 가능하고 테이블 생성 문법(DDL)은 실행할 수 없어서, 이 파일은 파이썬 코드가 아니라
사람이 Supabase 대시보드 SQL Editor에 직접 붙여넣고 실행하는 용도다. 별도 마이그레이션 도구는 안 쓴다.

## 현재 상태 (확인: 2026-08-28)

`schema.sql` 완성됨 — 테이블 3개(`recipes`/`recipe_steps`/`users`, 아래 참고). Supabase 프로젝트 생성 완료, `schema.sql` 실행 완료(RLS 켠 상태), `.env`에 자격증명 연결 확인 완료.

- `recipes`: 레시피 1건당 1행. `source` 컬럼은 `api_standard`/`user_custom`만 허용(check 제약). `origin_id`는 자기참조(user_custom이 어떤 표준 레시피 기반인지). `external_id`(원본 CSV RCP_SNO), `servings`(인분수) 컬럼 포함.
  - **`owner_id`**: 원래 익명 쿠키 UUID(작업3)/로그인 계정 id를 저장하던 컬럼이었으나, 2026-08-27 계정·쿠키 개인화 기능이 전면 제거되면서 **지금은 신규 행에 항상 null**이 들어간다. 컬럼 자체는 나중에 다른 식별자로 재사용할 수 있게 남겨뒀다.
  - **`approved`('Y'/'N', 2026-08-27 추가)**: 'Y'면 `select_standard_recipe()` 조회에 노출, 'N'이면 관리자가 승인하기 전까지 아무도(등록한 사람 포함) 조회할 수 없다. `api_standard`는 적재 시점에 항상 'Y', 신규 `user_custom`은 저장 시 항상 'N'.
- `recipe_steps`: 레시피 1건당 여러 행(단계별). `(recipe_id, step_number)` 복합 기본키, `on delete cascade`로 레시피 삭제 시 단계도 같이 삭제됨
- `users`(2026-08-22 추가): 로그인 계정용으로 만들었던 테이블. **2026-08-27 계정 로그인 기능 자체가 코드에서 삭제되면서 지금은 스키마만 남아있고 아무 코드도 이 테이블을 안 쓴다.** DROP은 되돌리기 어려운 조작이라 지금 안 쓴다고 굳이 지우지 않았다 — 나중에 다른 인증 방식을 붙이면 재사용할 수도 있다.

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
