-- ChefEar 리뉴얼용 Supabase 변경분. SQL Editor에 붙여 넣어 실행한다(재실행 안전).
-- 먼저 db/schema.sql이 적용돼 있어야 한다(recipes, recipe_steps 테이블).

-- ── 1. 세션: 서버가 상태를 들고 있지 않으므로 대화 상태 전체를 여기에 둔다 ─────────────
create table if not exists sessions (
    id text primary key,
    data jsonb not null,
    updated_at timestamptz not null default now()
);
create index if not exists idx_sessions_updated_at on sessions(updated_at);

-- ── 2. 음성 파일 목록: 어떤 문장의 음성이 올라가 있는지 ────────────────────────────
-- path 예: standard/{키}.mp3 (공용, 공개 버킷 tts) / users/{owner_id}/{키}.mp3 (본인 전용, 비공개 버킷 tts-private)
create table if not exists tts_assets (
    path text primary key,
    scope text not null check (scope in ('standard', 'user')),
    owner_id text,
    recipe_id uuid,
    created_at timestamptz not null default now()
);
create index if not exists idx_tts_assets_scope on tts_assets(scope);
create index if not exists idx_tts_assets_owner_recipe on tts_assets(owner_id, recipe_id);

-- ── 3. 등록·수정한 레시피의 음성 생성 상태(마이레시피의 "음성 준비 중" 표시) ─────────────
create table if not exists tts_jobs (
    recipe_id uuid primary key references recipes(id) on delete cascade,
    owner_id text not null,
    status text not null check (status in ('queued', 'running', 'done', 'failed')),
    error text,
    updated_at timestamptz not null default now()
);

-- ── 4. 저장소 버킷 ────────────────────────────────────────────────────────────
insert into storage.buckets (id, name, public) values ('tts', 'tts', true) on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('tts-private', 'tts-private', false) on conflict (id) do nothing;

-- ── 5. 보안: 웹 번들에 들어가는 anon 키로는 DB에 접근할 수 없게 한다 ──────────────────
-- 기존 schema.sql은 anon 키로 직접 접속해도 앱이 동작하도록 모든 행을 열어 두는 정책을 만들었다.
-- 리뉴얼에서는 anon 키가 웹(공개)에 실리므로 그 정책을 지운다. 서버는 service_role 키(RLS 우회)로만 DB를 쓴다.
drop policy if exists chefear_recipes_all on recipes;
drop policy if exists chefear_recipe_steps_all on recipe_steps;
drop policy if exists chefear_users_all on users;

alter table recipes enable row level security;
alter table recipe_steps enable row level security;
alter table users enable row level security;
alter table sessions enable row level security;
alter table tts_assets enable row level security;
alter table tts_jobs enable row level security;
-- 정책을 하나도 만들지 않는다 = anon/로그인 사용자는 이 테이블들을 직접 읽거나 쓸 수 없고, 서버(service_role)만 쓴다.

-- ── 6. 오래된 세션 정리(선택): Supabase에서 주기 실행하거나 가끔 손으로 실행 ──────────────
-- delete from sessions where updated_at < now() - interval '2 days';
