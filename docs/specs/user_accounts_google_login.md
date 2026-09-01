# Spec: 일반 사용자 회원가입/로그인 재도입 + 구글 OAuth 연동

## Why

- **배경**: `docs/specs/remove_user_accounts.md`(2026-08-27)에서 일반 사용자 로그인/회원가입/마이레시피를 전부 제거했다. 이유는 두 가지: ①Streamlit 화면 전환 잔상 버그(streamlit/streamlit#8360)가 로그인 관련 화면에서 반복적으로 재현됐고, ②관리자 승인(Y/N) 모델로 전환하면서 "누가 등록했는지" 자체를 안 쓰기로 했기 때문. 다만 그 문서는 "구글 OAuth 로그인 도입 여부는 아직 결정 안 됨, 보류 중"이라고 명시해뒀다 — 이번 요청은 그 보류를 다시 꺼내는 것이다.
- **바뀐 조건**: ①번 이유였던 잔상 버그는 그 이후(2026-08-28, `src/app.py` `_screen_slot = st.empty()` 패턴)에 **모든 화면 공통으로 근본 대응**됐다 — 화면이 바뀔 때마다 `st.empty()` 슬롯 하나를 통째로 교체하는 방식이라, 로그인/회원가입 화면을 새로 추가해도 같은 버그가 재현될 조건 자체가 이제 없다.
- **결정**: 팀 요청으로 로그인/회원가입을 다시 만들고, 구글 로그인도 같이 붙인다. `recipes.owner_id`는 `remove_user_accounts.md`가 스키마를 남겨둔 이유 그대로(나중에 구글 `sub`/`email` 재사용) 이번에 다시 채우기 시작한다.

## Goal

- **해결 목표**: 아이디(`username`, 이메일 형식이든 일반 문자열이든 상관없이 자유 입력)+비밀번호 일반 가입/로그인과 구글 원클릭 로그인을 둘 다 지원한다. 두 경로 모두 계정 고유 식별자(`users.id`)는 SHA256 해시값이다 — 로컬 가입은 `sha256(username)`, 구글 로그인은 `sha256(google_sub)`. `username` 컬럼은 기존 스키마에 이미 있고(`unique` 제약 포함) 그대로 재사용한다.
- **성공 기준**: 회원가입 → 로그아웃 → 같은 계정으로 재로그인 성공 / 구글 로그인 시 최초 1회만 INSERT, 이후엔 기존 행 재사용(중복 insert 없음) / 로그인 상태가 `recipes.owner_id`에 반영됨 / `pytest` 전체 그린.
- **Out of Scope**:
  - 계정 연동(같은 이메일로 로컬 가입 후 구글 로그인 시 자동 병합) — 이번엔 안 함, `id`가 다르므로 별개 계정으로 취급됨(Edge Case 표 EC-05 참고)
  - 비밀번호 재설정("비밀번호 찾기") 플로우 — 별도 Spec
  - 이메일 인증(가입 시 확인 메일 발송) — 별도 Spec
  - 로그인 시도 rate limiting/브루트포스 방어 — 별도 Spec(보안 후속 과제로 남김)
  - 마이레시피(내가 등록한 레시피 목록/수정/삭제) 화면 부활 — 이번 Spec은 로그인 자체만, 마이레시피는 별도 Spec

## What

**Happy Path A — 회원가입 후 로그인**

1. `start` 화면 또는 브랜드 영역에 "로그인" 버튼 추가 → `login` 화면 진입
2. `login` 화면에 "회원가입" 링크 → `signup` 화면 진입
3. 아이디(`username`, 이메일이든 일반 문자열이든 자유) + 비밀번호 + 비밀번호 확인 입력 → 제출
4. 서버가 `sha256(username.strip())`로 `id` 계산, `users` 테이블에 같은 `id` 있는지 확인
5. 없으면 INSERT(`id`, `username`, `auth_provider='local'`, `password_hash=salt+PBKDF2-HMAC-SHA256`)
6. 가입 완료 → 자동 로그인 처리 → `start` 화면으로 이동, 세션에 `current_user` 저장

**Happy Path B — 구글 로그인(신규)**

1. `login` 화면에서 "구글로 로그인" 버튼 클릭 → `st.login()` 호출 → 구글 OIDC 동의 화면으로 리다이렉트
2. 사용자 인증 완료 → 앱으로 리다이렉트(`redirect_uri=.../oauth2callback`) → `st.user.is_logged_in == True`
3. 서버가 `sha256(st.user.sub)`로 `id` 계산, `users` 테이블 조회
4. 없으면 INSERT(`id`, `username=st.user.email`, `email=st.user.email`, `auth_provider='google'`, `google_sub=st.user.sub`, `password_hash=NULL`)
5. 있으면 그대로 통과(insert 안 함) — 두 경우 다 세션에 `current_user` 저장

**Happy Path C — 재로그인**

1. `login` 화면에서 아이디+비밀번호 입력
2. `sha256(username)`로 조회 → 행 존재 확인 → `password_hash` 검증(PBKDF2 재계산 비교)
3. 성공 시 세션에 `current_user` 저장, 실패 시 "아이디 또는 비밀번호가 올바르지 않습니다" (계정 존재 여부는 노출 안 함)

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 이미 가입된 아이디로 재가입 시도 | `sha256(username)` 행이 이미 있으면 "이미 가입된 아이디입니다" 오류, insert 안 함 |
| EC-02 | 구글 로그인은 최초, 로컬 계정도 같은 이메일로 이미 있음 | `id`가 다르므로(sha256(username) vs sha256(sub)) 별개 계정으로 새로 insert됨 — 계정 연동 안 함(Out of Scope 참고) |
| EC-03 | 비밀번호 확인란 불일치 | 제출 막고 "비밀번호가 일치하지 않습니다" 표시, insert 안 함 |
| EC-04 | 짧은/빈 비밀번호(8자 미만) | 제출 막고 최소 길이 안내, insert 안 함 |
| EC-05 | 구글 로그인 사용자가 재방문(쿠키 만료 후) | `st.login()` 재시도 → 구글이 이미 로그인돼 있으면 즉시 재인증 → `sha256(sub)` 동일값이므로 기존 행 재사용, 중복 insert 없음(AC-03) |
| EC-06 | Supabase 연결 실패/미설정(mock 클라이언트 폴백 상태) | 회원가입/로그인 모두 실패 처리, "일시적 오류" 안내(기존 mock 폴백 정책과 동일하게 조용히 죽지 않고 에러 안내) |
| EC-07 | 로그인 화면에서 "처음으로" 등 화면 전환 | 기존 `st.empty()` 슬롯 교체 패턴을 그대로 따르므로 잔상 재현 안 됨(2026-08-28 대응 재사용) |
| EC-08 | 신규 가입/구글 로그인이 기존 테스트 계정 6행(2026-08-22~27 생성, `id`가 구 UUID라 새 sha256 스킴과 안 맞음)과 `username` 충돌 | 팀 결정으로 이 6행은 삭제하지 않고 고아 행으로 남김(마이그레이션에서 손 안 댐) — `test`/`test12`/`test1234`/`claude_debug_99821`/`leeony`/`김승욱`을 아이디로 쓰려는 신규 가입자는 `unique` 위반으로 막힘(드물 것으로 판단, 발생 시 다른 아이디 안내) |

## How

### DB 스키마 변경 (`db/schema.sql`에 추가, Supabase SQL Editor에서 수동 실행)

```sql
-- id를 uuid에서 text로 변경 — SHA256 hex digest(64자)를 그대로 저장하기 위함.
-- 기존 uuid 값이 들어있던 행이 있다면(과거 로그인 흔적) 이 마이그레이션 전에 팀 논의 필요.
alter table users alter column id type text;
alter table users alter column id drop default;

alter table users add column if not exists email text;  -- 구글 계정만 채움, 로컬 가입은 null
alter table users add column if not exists auth_provider text not null default 'local'
    check (auth_provider in ('local', 'google'));
alter table users add column if not exists google_sub text;
alter table users alter column password_hash drop not null;  -- 구글 계정은 로컬 비밀번호 없음
```

### 신규 모듈: `src/orchestration/auth.py` (제거됐던 파일을 새 스펙으로 재작성)

```
hash_password(password: str) -> str
    # "salt(hex):hash(hex)" 형식, PBKDF2-HMAC-SHA256 (기존 삭제된 auth.py와 동일 포맷 재사용)
verify_password(password: str, stored_hash: str) -> bool

account_id_from_username(username: str) -> str
    # hashlib.sha256(username.strip().encode()).hexdigest()
account_id_from_google_sub(sub: str) -> str
    # hashlib.sha256(sub.encode()).hexdigest()

signup_local(username: str, password: str) -> User | SignupError
login_local(username: str, password: str) -> User | None
login_or_create_google(sub: str, email: str) -> User
    # SELECT by id=account_id_from_google_sub(sub); 없으면 INSERT(username=email로 채움)
```

### Google OAuth 설정 (Streamlit 1.61.1 내장 `st.login()` 사용 — 직접 OAuth 플로우 구현 불필요)

- 의존성: `Authlib>=1.3.2` 추가 필요 (`pip install streamlit[auth]`) → `requirements-main.txt`, `requirements.txt` 둘 다에 추가(배포 환경도 이 기능을 쓰므로)
- `.streamlit/secrets.toml` (신규 파일, **커밋 금지** — `.gitignore`에 추가 필수):
  ```toml
  [auth]
  redirect_uri = "https://chefear.store/oauth2callback"
  cookie_secret = "<secrets.token_urlsafe(32)로 생성>"
  client_id = "<Google Cloud Console에서 발급>"
  client_secret = "<Google Cloud Console에서 발급>"
  server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
  ```
- 로컬 개발용 `redirect_uri`는 `http://localhost:8501/oauth2callback` — Google Cloud Console의 "승인된 리디렉션 URI"에 배포용/로컬용 둘 다 등록 필요
- 코드 패턴:
  ```python
  if not st.user.is_logged_in:
      if st.button("구글로 로그인"):
          st.login()  # 기본 provider(위 [auth] 설정) 사용
  else:
      user = login_or_create_google(st.user.sub, st.user.email)
      session["current_user"] = user
  ```

### `src/app.py` / `src/ui/session.py` / `src/ui/dispatch.py`

- `SCREENS`에 `"login"`, `"signup"` 추가 (`"my_recipes"`, `"edit_recipe"`는 이번 Spec 범위 아님 — 추가 안 함)
- `ui/session.py`: `login()`, `logout()`, `get_owner_id()` 재작성(제거됐던 것과 유사하되 쿠키 기반 익명 식별과는 무관 — `st.user` 또는 로컬 세션 상태 기반)
- `ui/dispatch.py`의 `_block_register_if_not_logged_in()`은 **부활 안 함** — `remove_user_accounts.md`의 관리자 승인 모델 결정은 그대로 유지, 등록은 여전히 로그인 여부와 무관하게 가능. 로그인은 "마이레시피용 소유권 표시" 목적으로만 다시 씀
- `orchestration/registration.py::register_recipe()`가 `owner_id=session.get("owner_id")`를 다시 넘기도록 복원(로그인 상태면 `current_user.id`, 아니면 `None`)
- 화면 추가 시 반드시 기존 `_screen_slot = st.empty()` / `st.container(key=f"screen_{screen}")` 패턴을 그대로 따를 것(EC-07)

## AC (Given-When-Then)

**AC-01 · 회원가입**
- GIVEN: `users` 테이블에 없는 아이디(이메일 형식이든 아니든)
- WHEN: signup 폼에 아이디+비밀번호(8자 이상, 확인란 일치) 제출
- THEN: `id=sha256(username)`인 행이 `auth_provider='local'`로 insert되고, 비밀번호는 `salt:hash` 형식으로 저장되며 평문은 어디에도 안 남는다

**AC-02 · 재로그인**
- GIVEN: AC-01로 가입된 계정
- WHEN: 같은 아이디+비밀번호로 로그인 시도
- THEN: 인증 성공, 세션에 `current_user` 설정. 틀린 비밀번호는 실패하고 계정 존재 여부를 노출하지 않는다

**AC-03 · 구글 로그인 최초 1회만 insert**
- GIVEN: `users`에 없는 구글 계정
- WHEN: `st.login()`으로 최초 로그인 → 로그아웃 → 같은 계정으로 재로그인
- THEN: 최초 1회만 INSERT 발생, 두 번째 로그인 시 기존 행을 그대로 사용(추가 insert 없음)

**AC-04 · owner_id 반영**
- GIVEN: 로그인 상태(로컬 또는 구글)
- WHEN: 레시피를 새로 등록함
- THEN: `recipes.owner_id`에 `current_user.id`(sha256 값)가 저장된다. 비로그인 상태면 기존과 동일하게 `null`

**AC-05 · 등록 게이트 미부활**
- GIVEN: 비로그인 상태
- WHEN: "레시피 등록해줘" 발화
- THEN: 로그인 여부와 무관하게 `register_intro`로 바로 진입(remove_user_accounts.md AC-02 유지, 회귀 없음)

**AC-06 · 화면 전환 잔상 없음**
- GIVEN: `login`/`signup` 화면 추가됨
- WHEN: `start` → `login` → `signup` → `start` 등 화면을 연속 전환
- THEN: #8360류 잔상(이전 화면 위젯이 겹쳐 보임)이 재현되지 않는다

**AC-07 · 테스트 스위트 그린**
- GIVEN: 위 변경 전부 적용됨
- WHEN: `pytest` 전체 실행
- THEN: 실패 0건
