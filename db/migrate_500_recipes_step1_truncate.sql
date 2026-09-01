-- 500개 레시피로 전면 교체 — 1단계: 제약 조건 변경 + 기존 데이터 삭제
-- Supabase 대시보드 SQL Editor에서 직접 실행할 것 (DDL이라 supabase-py로는 못 함,
-- db/schema.sql 자신의 원칙과 동일).
--
-- 실행 전 반드시 확인: 이 스크립트는 recipes/recipe_steps의 기존 데이터를
-- 전부(60,282건 기반 + 사용자 등록분 포함) 영구 삭제합니다. 되돌릴 수 없습니다.

-- recipe_steps.source CHECK 제약에 'rule_generated' 추가(500개 COOKING_STEPS가
-- 이 값을 씀). recipes.source는 그대로 둔다 — 500개 레시피 자체는 source='api_standard'로
-- 들어가고, rule_generated는 조리순서(recipe_steps)에만 해당하는 값이라서다.
alter table recipe_steps drop constraint if exists recipe_steps_source_check;
alter table recipe_steps add constraint recipe_steps_source_check
    check (source in ('api_standard', 'user_custom', 'rule_generated'));

-- 기존 데이터 전부 삭제(스키마/제약/인덱스는 그대로 유지).
-- 2026-09-01 수정 — recipe_steps/recipes를 따로따로 truncate하면 PostgreSQL이
-- "FK로 참조되는 테이블을 truncate하려면 참조하는 테이블도 같은 문장에 포함하거나
-- CASCADE를 써야 한다"고 거부한다(실측: "cannot truncate a table referenced in a
-- foreign key constraint"). 두 테이블을 한 문장에 같이 넣어서 truncate한다 — FK
-- 관계가 있는 두 테이블을 한 번에 지우는 표준적인 방법이라 recipe_steps의
-- on delete cascade 설정과는 무관하게 항상 동작한다.
truncate table recipe_steps, recipes;
