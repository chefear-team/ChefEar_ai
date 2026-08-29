-- ChefEar Supabase 스키마 (PRD/SDD v0.8, 6.7 Supabase 테이블)
-- Supabase 대시보드 SQL Editor에서 직접 실행할 것 (supabase-py는 SELECT/INSERT/UPDATE/DELETE
-- 같은 데이터 조작만 할 수 있고, 테이블을 만드는 DDL 문법은 실행할 수 없다. 그래서 이
-- schema.sql은 파이썬 코드가 아니라 사람이 Supabase 웹 화면에서 직접 붙여넣고 실행한다.)

-- gen_random_uuid() 함수(레시피 id를 자동으로 만들어줄 때 씀)를 쓰려면 이 확장이 필요하다.
-- Supabase는 보통 기본으로 켜져 있지만, 혹시 몰라 안전하게 한 번 더 켠다(이미 켜져 있으면 무시됨).
create extension if not exists pgcrypto;

-- recipes: 레시피 "한 건"의 기본 정보. 요리 하나당 딱 한 행이다.
create table if not exists recipes (
    -- uuid: 숫자를 1,2,3... 순서로 매기는 대신 무작위에 가까운 긴 문자열로 id를 만드는 방식.
    -- gen_random_uuid()가 자동으로 값을 채워주므로, insert할 때 id는 안 넣어도 된다.
    id uuid primary key default gen_random_uuid(),
    dish_name text not null,       -- 요리명(예: "된장찌개")
    ingredients text,               -- 재료 목록. 가공하지 않고 원문 텍스트 그대로 저장(6.1/6.2)
    -- source: 이 레시피가 어디서 왔는지 구분하는 값. api_standard = 표준 데이터(작업1로
    -- 대량 적재), user_custom = 사용자가 직접 등록/수정한 버전. check 제약으로 이 두 값
    -- 이외의 오타(예: "API_STANDARD")가 실수로 들어가는 걸 DB 차원에서 막는다.
    source text not null check (source in ('api_standard', 'user_custom')),
    -- origin_id: user_custom 레시피가 "어떤 표준 레시피를 기반으로 수정한 것인지" 가리키는
    -- 자기 자신 테이블 참조(self-reference). references recipes(id)라서 recipes 테이블이
    -- 자기 자신을 가리킬 수 있다.
    origin_id uuid references recipes(id),
    -- 6.7 표에는 없지만 7.6 select_standard_recipe() 응답(view_count)과
    -- EC-19(조회수 0일 때 등록일 최신순 대체 정렬)를 충족하려면 필요해서 추가함
    view_count integer not null default 0,
    created_at timestamptz not null default now(),  -- default now(): insert할 때 안 넣으면 현재 시각이 자동으로 들어감
    -- 원래는 작업3(쿠키 UUID 개인화, ~~FR-08~~)이 익명 사용자를 식별하려고 쓰던 컬럼이었으나,
    -- 2026-08-27 계정/쿠키 개인화 기능이 전면 제거되면서 지금은 신규 행에 항상 null이 들어간다
    -- (registration.py::save_recipe() 참고). 컬럼 자체는 나중에 다른 식별자로 재사용할 수
    -- 있게 스키마엔 남겨뒀다.
    owner_id text
);

-- recipe_steps: 레시피 하나의 "조리순서 한 단계"씩. 레시피 하나당 여러 행(1단계, 2단계, ...)이 붙는다.
create table if not exists recipe_steps (
    -- recipe_id는 recipes.id를 가리키는 외래키(foreign key)다. "이 단계가 어느 레시피
    -- 소속인지"를 나타낸다. on delete cascade: 만약 recipes에서 레시피 하나가 삭제되면,
    -- 그 레시피에 딸린 recipe_steps 행들도 자동으로 같이 삭제된다(고아 데이터 방지).
    recipe_id uuid not null references recipes(id) on delete cascade,
    step_number integer not null,   -- 몇 번째 단계인지 (1, 2, 3, ...)
    step_text text not null,        -- 그 단계의 안내 문장
    source text not null check (source in ('api_standard', 'user_custom')),
    -- primary key를 (recipe_id, step_number) 두 컬럼을 합쳐서 만든 이유: 같은 레시피 안에서
    -- "1단계"는 하나뿐이어야 하지만(중복 방지), 다른 레시피끼리는 둘 다 "1단계"를 가질 수
    -- 있어야 한다. 두 컬럼을 묶은 이 조합을 복합 기본키(composite primary key)라고 부른다.
    primary key (recipe_id, step_number)
);

-- 인덱스: 자주 검색하는 컬럼에 인덱스를 만들어두면, 그 컬럼으로 WHERE 조건을 걸 때
-- 테이블 전체를 다 훑지 않고 훨씬 빠르게 찾을 수 있다(책 뒤의 "찾아보기"와 비슷한 개념).
create index if not exists idx_recipes_dish_name on recipes(dish_name);  -- 요리명으로 조회할 때(select_standard_recipe 등)
create index if not exists idx_recipes_source on recipes(source);        -- api_standard/user_custom 구분 조회할 때
create index if not exists idx_recipes_owner_id on recipes(owner_id);    -- 특정 사용자의 user_custom만 찾을 때

-- ── 작업1(요리명별_조리과정_60282건.csv 적재, load_data.py) 준비 ──────────
-- 위의 create table은 테이블이 이미 Supabase에 만들어져 있으면 아무것도 안 바꾸므로,
-- 이미 만든 사람도 다시 붙여넣어 실행하면 안전하게 아래 변경분만 추가로 반영되도록
-- alter table(컬럼 추가)과 if not exists(재실행 안전)를 쓴다.

-- external_id: 원본 CSV의 RCP_SNO(레시피 번호). load_data.py를 재실행해도 같은
-- 레시피가 중복으로 쌓이지 않게 막아주는 키로 쓴다(같은 external_id면 건너뜀).
-- user_custom 레시피는 원본 CSV 번호가 없으므로 null로 둔다(unique 제약은 null끼리는
-- 서로 다른 값으로 취급하므로 null이 여러 개 있어도 문제없음).
alter table recipes add column if not exists external_id integer unique;

-- servings: 원본 CSV의 CKG_INBUN_NM(인분수, 예: "3인분"). 가공 없이 원문 그대로 저장.
alter table recipes add column if not exists servings text;

-- dish_name에 앞뒤 공백이 섞여 들어오면(예: "닭볶음탕 ") 같은 요리가 서로 다른 행으로
-- 취급돼 표준 레시피 선정(6.1 규칙)이 깨진다. 실제로 원본 CSV에서 이 문제로 86쌍이
-- 발견됐다(예: "닭볶음탕"과 "닭볶음탕 "). DB 차원에서 공백 섞인 값 저장을 원천 차단한다.
-- (postgres는 constraint에 if not exists 문법이 없어서 존재 여부를 직접 확인하는
-- do 블록으로 감싼다 — 재실행해도 중복 추가 에러가 안 나게 하기 위함)
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'dish_name_trimmed'
    ) then
        alter table recipes add constraint dish_name_trimmed check (dish_name = btrim(dish_name));
    end if;
end $$;

-- api_standard(표준 데이터)는 요리명 하나당 딱 한 행만 있어야 한다(6.1 표준선정규칙,
-- load_data.py가 적재 전에 조회수 1위만 남기고 나머지는 버림). user_custom은 EC-17에
-- 따라 같은 요리명으로 여러 버전을 가질 수 있으므로 이 제약에서 제외한다(where 조건).
create unique index if not exists uq_recipes_dish_name_standard
    on recipes (dish_name) where source = 'api_standard';

-- ── users(2026-08-22 추가): 마이 레시피 로그인용 실제 계정 ──────────────────
-- 원래는 작업3(위 recipes.owner_id, ~~FR-08~~)의 쿠키 익명 UUID 위에 "로그인해서
-- 기기와 무관하게 내 레시피를 관리"하는 진짜 계정을 얹으려고 만든 테이블이었다.
-- 2026-08-27 계정/쿠키 개인화 기능이 코드에서 전부 삭제되면서(auth.py 삭제,
-- recipes.owner_id는 항상 null) 이 테이블도 지금은 스키마만 남아있고 아무 코드도
-- 안 쓴다 — DROP은 되돌리기 어려운 조작이라 지금 안 쓴다고 굳이 지우지 않았다.
create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    username text not null unique,
    -- 원문 비밀번호는 저장하지 않는다. "salt(hex):hash(hex)" 형태의 PBKDF2-HMAC-SHA256
    -- 해시 문자열이었다(orchestration/auth.py, 2026-08-27 계정 시스템 제거로 코드는
    -- 삭제됨). 테이블은 남겨둔다 — 나중에 구글 OAuth 등을 붙이면 이 자리를 다시 쓸 수도
    -- 있고, DROP은 되돌리기 어려운 조작이라 지금 코드에서 안 쓴다고 굳이 지우지 않는다.
    password_hash text not null,
    created_at timestamptz not null default now()
);

-- ── approved(2026-08-27 추가, docs/specs/admin_recipe_approval.md): 관리자 승인 워크플로우 ──
-- 'Y'면 조회(select_standard_recipe)에 노출되고, 'N'이면 관리자가 승인하기 전까지
-- 아무도(등록한 사람 포함) 조회할 수 없다. api_standard는 처음부터 검수된 데이터라
-- 기본값을 'Y'로 두고, 신규 user_custom은 registration.py::save_recipe()가 매번
-- 명시적으로 'N'을 넣는다(테이블 기본값만 믿으면 그 코드를 깜빡했을 때 바로 공개돼버림).
alter table recipes add column if not exists approved text not null default 'Y' check (approved in ('Y', 'N'));

-- 이미 있던 행(이 컬럼이 생기기 전에 적재된 api_standard/user_custom)은 전부 승인된
-- 것으로 간주한다 — 안 그러면 기존 데이터가 이 마이그레이션 직후 전부 조회 안 되는
-- 회귀가 생긴다. 한 번만 실행하면 되고, 재실행해도 이미 'Y'인 행은 그대로라 안전하다.
update recipes set approved = 'Y' where approved is distinct from 'Y';
