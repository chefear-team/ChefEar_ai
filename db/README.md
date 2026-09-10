# db/ — Supabase 스키마

`supabase-py`는 DDL을 실행할 수 없으므로 SQL 파일은 Supabase 대시보드 SQL Editor에 직접 붙여넣어 실행한다. 마이그레이션 도구는 쓰지 않는다.

| 파일 | 용도 |
|---|---|
| `schema.sql` | `recipes` / `recipe_steps` / `users` 테이블, 인덱스, RLS |
| `migrate_500_recipes_step1_truncate.sql` | 2026-09-01 500건 교체 1단계: `recipe_steps.source`에 `rule_generated` 허용 + 기존 데이터 truncate. 2단계는 `python src/orchestration/load_500_recipes.py` |

## 테이블

- **`recipes`** — 레시피 1건당 1행. `source`는 `api_standard`(500건 표준) / `user_custom`(사용자 등록). `owner_id`는 등록자 id(09-01부터 신규 등록에 필수). `approved`는 신규 등록 시 'Y'로 즉시 저장되며 'N'은 09-02 이전 레거시 승인 대기 행에만 남아 있다. 공개 범위는 `approved`가 아니라 `owner_id`로 가른다(`api_standard`는 전체 공개, `user_custom`은 본인만).
- **`recipe_steps`** — 레시피 1건당 단계별 여러 행, `(recipe_id, step_number)` 복합 PK, `on delete cascade`. `step_text`는 `[TERM:용어]` 태그를 포함한 원문. `source`는 `api_standard` / `user_custom` / `rule_generated`.
- **`users`** — `user_id_hash`(PK, sha256) / `user_id`(표시 id) / `auth_provider`(local|google) / `google_sub` / `password_hash` / `session_token_hash` / `last_login_at`.

RLS는 켜져 있지만 소유자 격리는 앱 코드 필터로 하며, `service_role` 키는 RLS를 우회하므로 서버 `.env`에만 둔다. 관리자 성문은 DB가 아니라 로컬 `data/admin_voiceprints.json`.

## 현재 데이터

한국 가정식 500개(`docs/한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv`): `recipes` 500행, `recipe_steps` 2,950행, 용어 태그 926개. 요리명·재료·조회수는 만개의레시피 실데이터, 조리순서는 재료 기반 규칙 생성. 초기의 60,196건/357,938단계(조리순서 ChatGPT 생성)는 09-01에 전량 삭제했다.

## 설정

1. SQL Editor에 `schema.sql` 실행
2. `.env`에 `SUPABASE_URL` / `SUPABASE_KEY` → `src/orchestration/db.py::get_client()`가 자동으로 실제 DB 사용(없으면 mock)
3. `migrate_500_recipes_step1_truncate.sql` 실행 후 `python src/orchestration/load_500_recipes.py`
