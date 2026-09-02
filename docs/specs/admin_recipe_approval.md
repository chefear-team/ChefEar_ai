# Spec: 관리자 페이지(레시피 승인 Y/N 워크플로우) — Phase 1은 `.env` 토큰 게이트, 화자검증은 Phase 2

> **2026-09-02 갱신**: `docs/specs/private_recipe_visibility.md`가 신규 `user_custom` 등록의 기본값을
> `approved='N'`(관리자 승인 대기)에서 `approved='Y'`(소유자 전용 즉시 공개)로 바꿨다 — 신규 등록은 더
> 이상 이 스펙의 승인 워크플로우를 거치지 않는다. 이 문서와 관리자 페이지 코드는 레거시 `approved='N'`
> 행 처리용으로 그대로 남아있다(팀 결정, 지우지 않음). 아래 내용은 Phase 1 도입 당시 기준으로 읽을 것.
>
> **전제**: `docs/specs/remove_user_accounts.md`가 먼저 적용되어 로그인/회원가입/마이레시피가 없는 상태를 기준으로 한다. `docs/specs/dish_not_found_voice_notice.md`(no_match 제거)의 조회 실패 처리도 전제로 하며, 이 스펙은 그 처리를 "완전히 없음" / "심사 대기" 두 갈래로 세분화한다.
>
> **2026-08-27 범위 조정**: 화자검증(ECAPA-TDNN) 기반 "관리자 권한으로 로그인 할게요" 게이트는 **Phase 2로 미룬다.** 지금(Phase 1)은 `.env` 시크릿 토큰만으로 관리자 페이지 접근을 가른다 — 승인(Y/N) 워크플로우 자체가 이번 스펙의 핵심이고, 인증 방식은 나중에 화자검증으로 교체/보강할 수 있게 분리해서 설계한다.

## Why

- **상황**: 로그인/마이레시피를 없애면서(`remove_user_accounts.md`) 사용자가 등록한 레시피를 개인별로 가리던 장치(`owner_id` 필터)가 사라졌다. 등록 즉시 아무 필터 없이 전체 공개되면 품질 검수가 전혀 안 된 데이터가 그대로 표준 조회 결과에 섞여 나온다.
- **문제**:
  1. 신규 등록 레시피를 검수 없이 공개하면 안 됨 → 관리자가 승인해야만 조회 가능하게 바꿔야 한다.
  2. 그 관리자 화면 접근을 위한 "로그인"은 다시 화면 전환 잔상 문제를 되풀이할 수 있어(`remove_user_accounts.md`의 Why 참고), 아예 같은 스크립트/세션에서 벗어난 독립 Streamlit 페이지로 분리하기로 함 — 대신 페이지 이동에 따르는 마이크(webrtc) 재연결 비용은 감수하기로 함(2026-08-27 결정).
  3. 화자검증(누가 관리자인지 목소리로 구분)까지 한 번에 하려면 ECAPA-TDNN 모델·임베딩 저장소·enrollment 화면까지 다 갖춰야 해서 착수가 늦어짐 — 승인 워크플로우 자체는 그거 없이도 독립적으로 완성 가능하므로 먼저 분리해서 진행하기로 함.
- **측정 지표**: 정량 지표 없음 — AC 통과로 판단.

## Goal

- **해결 목표 (Phase 1, 이번 스펙 구현 범위)**:
  1. `recipes` 테이블에 승인 여부 컬럼을 추가해, 승인된 것만 조회에 노출한다.
  2. 로그인 버튼 자리를 없애고, `.env` 시크릿 토큰이 URL에 붙어 있을 때만 진입 가능한 독립 관리자 페이지를 만든다.
  3. 관리자 페이지에서 승인 대기 레시피 목록을 보고 "등록"(승인)/"삭제"(제거) 처리를 한다.
  4. 조회 실패를 "아예 없음"과 "등록했지만 심사 대기 중"으로 구분해서 안내한다.
- **해결 목표 (Phase 2, 나중 — 이번 스펙에서 설계만 언급, 구현 안 함)**:
  5. 토큰 게이트를 "관리자 권한으로 로그인 할게요" 발화 + ECAPA-TDNN 화자검증으로 교체하거나 이중화한다. 관리자 여러 명 지원.
- **성공 기준 (Phase 1)**:
  - 승인(`approved == 'Y'`)되지 않은 `user_custom` 레시피는 조회에 전혀 안 걸린다(등록한 사람 포함, 아무도 못 봄).
  - `ADMIN_ACCESS_TOKEN`과 일치하는 `?admin_key=`가 붙은 URL로만 관리자 페이지에 들어갈 수 있다.
  - 관리자 페이지의 "등록" 클릭 시 해당 레시피가 즉시 조회 가능해지고, "삭제" 클릭 시 해당 레시피(및 딸린 조리단계)가 DB에서 사라진다.
  - 조회 실패 시 심사 대기 여부에 따라 서로 다른 안내 음성이 정확히 나온다.
- **Out of Scope**:
  - 화자검증(ECAPA-TDNN), 관리자 목소리 enrollment — Phase 2, 이번 스펙 구현 범위 아님.
  - 구글 OAuth 기반 관리자 인증 — 보류 중, 별도 논의.
  - 관리자별 권한 차등(전원 동일 권한 — 승인/삭제 다 가능).
  - 관리자 페이지에서 레시피 **내용을 수정**하는 기능(승인/삭제만, 편집 없음 — 편집이 필요해지면 별도 스펙).

## What

**Happy Path — 등록자(누구나, 로그인 불필요)**

1. 사용자가 음성으로 레시피를 등록한다(`remove_user_accounts.md`의 등록 플로우).
2. `register_recipe()`가 저장하는 신규 `user_custom` 행의 `approved`가 `'N'`으로 저장된다.
3. (완료 화면 문구는 이 스펙에서 확정하지 않음 — 아래 "미정" 참고)

**Happy Path — 관리자 (Phase 1, `.env` 토큰)**

1. 관리자가 `https://chefear.store/?admin_key=<ADMIN_ACCESS_TOKEN 값>`으로 접속한다(어디에도 링크 안 걸린 URL, 직접 알고 있어야 함).
2. 토큰이 일치하면 독립 Streamlit 페이지(관리자 페이지)로 진입한다(같은 세션의 마이크는 재연결됨 — 감수하기로 한 비용).
3. `approved == 'N'`인 레시피(source 무관) 목록(요리명/재료/조리순서 미리보기)이 뜬다.
4. 각 항목에 "등록"/"삭제" 버튼:
   - "등록" → 해당 행 `approved`를 `'Y'`로 UPDATE
   - "삭제" → 해당 `recipes` 행 DELETE(스키마의 `on delete cascade`로 `recipe_steps`도 자동 삭제)

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 토큰 없이/틀린 토큰으로 `?admin_key=` 접근 | 관리자 페이지 진입 실패, 조용히 무시(기존 `_access_gate_ok()`와 같은 태도 — 실패 사실을 굳이 알려주지 않음) |
| EC-02 | `.env`의 `ADMIN_ACCESS_TOKEN`이 비어있음 | 게이트 자체를 끈다(로컬 개발 fail-open, `_access_gate_ok()`와 동일 패턴) — 프로덕션엔 반드시 값 설정 |
| EC-03 | 조회 실패, 해당 dish_name이 DB에 아예 없음 | 기존 안내를 로그인 언급 없이 다듬은 문구: "등록되지 않은 레시피에요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요."(`remove_user_accounts.md`에서 로그인 개념이 없어짐에 따라 "로그인 후" 삭제) |
| EC-04 | 조회 실패, dish_name은 있지만 전부 `approved == 'N'`(심사 대기) | 새 안내: "등록 심사 중인 레시피예요. 승인되면 바로 조회할 수 있어요." (확정됨) |
| EC-05 | 기존 배포 DB에 `approved` 컬럼이 아직 없음(마이그레이션 시점) | `alter table ... add column if not exists`로 추가 + 기존 행 전부 `'Y'`로 일괄 UPDATE(한 번만 실행) — 안 그러면 이미 있던 표준/커스텀 데이터가 갑자기 전부 조회 안 되는 회귀가 생김 |
| EC-06 | 관리자 페이지가 독립 페이지라 마이크가 재연결됨 | 의도된 트레이드오프(Why 참고) — 정상 동작 |

## 확정됨

- **Phase 1 관리자 게이트 방식**: `.env` 시크릿 토큰(`ADMIN_ACCESS_TOKEN`) 기반, 화자검증은 Phase 2로 연기.
- **(Phase 2 몫, 미리 정해둠) 화자검증 실패 시 반응**: 조용히 무시한다(아무 안내 없음). 공격자에게 "게이트가 있다/없다"는 신호를 주지 않는 쪽을 택함.
- **(Phase 2 몫, 미리 정해둠) 관리자 최초 등록(enrollment) 방식**: `.env` 시크릿 토큰 기반(`ADMIN_ENROLL_TOKEN`, `st.audio_input()`으로 음성 샘플 녹음 → ECAPA-TDNN 임베딩 저장). Phase 2 착수 시 아래 "Phase 2 설계 메모" 참고.

## 미정 → 해결됨 (2026-08-27)

1. **`complete`(등록 완료) 화면 문구**: `ui/screens/register.py::screen_complete()`가 2026-08-27 관리자 승인 워크플로우 도입과 함께 갱신됐다 — owner_id 개인화 전제 문구("다음에 다시 찾으면 회원님 버전으로...", "나만의 레시피로 저장됨")는 지웠고, 지금은 `f"{dish_name}, 관리자 승인 후에 검색할 수 있어요."`로 표시된다(제목은 `_REGISTER_SAVED_MESSAGE = "저장이 완료됐어요!"` 그대로 재사용).

## How (Phase 1)

### 1. DB — `db/schema.sql`

```sql
-- approved: 'Y'면 조회에 노출, 'N'이면 관리자 승인 대기(신규 user_custom 기본값).
-- api_standard는 처음부터 검수된 데이터라 기본 'Y'.
alter table recipes add column if not exists approved text not null default 'Y' check (approved in ('Y', 'N'));

-- 이미 있던 행(api_standard + 기존 user_custom)은 전부 승인된 것으로 간주 — 한 번만 실행.
update recipes set approved = 'Y' where approved is distinct from 'Y';
```

신규 `user_custom` INSERT 시에는 `registration.py::register_recipe()`가 `approved="N"`을 명시적으로 넘긴다(테이블 기본값이 `'Y'`라서 명시 안 하면 갑자기 공개돼버림 — 반드시 코드에서 override).

### 2. 조회 — `orchestration/recipe_search.py::select_standard_recipe()`

`owner_id` 분기(`remove_user_accounts.md`에서 제거됨)를 대체해서, dish_name으로 가져온 전체 행을 승인 여부로 나눈다:

```python
rows = ...  # 기존과 동일한 쿼리 (dish_name 일치, source in [...])
if not rows:
    return None  # 아예 없음 -> DISH_NOT_FOUND_MESSAGE

approved_rows = [r for r in rows if r.get("approved") == "Y"]
if not approved_rows:
    return {"pending": True}  # 있지만 전부 심사 대기 -> 새 PENDING_MESSAGE
# 이후 기존처럼 approved_rows에서 _max_view_count() 등으로 대표 레시피 선정
```

`pipeline.py::handle_utterance()`의 `조회` 분기가 이 `{"pending": True}` 신호를 받아 `PENDING_MESSAGE`("등록 심사 중인 레시피예요. 승인되면 바로 조회할 수 있어요.")로 갈리게 한다 — `dish_not_found_voice_notice.md`의 기존 `DISH_NOT_FOUND_MESSAGE` 분기와 나란히 둔다.

### 3. 관리자 페이지 접근 게이트 — `.env` 토큰

`app.py::_access_gate_ok()`(랜딩페이지 `?key=` 검사)와 완전히 같은 패턴으로 하나 더 만든다.

```python
def _admin_gate_ok() -> bool:
    expected = os.environ.get("ADMIN_ACCESS_TOKEN", "").strip()
    if not expected:
        return False  # 비어있으면 아예 못 들어감(이 게이트는 기본이 닫힘 — 랜딩게이트와 반대)
    return st.query_params.get("admin_key") == expected
```

**주의**: `_access_gate_ok()`는 값이 비어있으면 게이트를 꺼서(fail-open) 전체 앱을 아무나 접근하게 두지만, 관리자 게이트는 반대로 값이 비어있으면 **아무도 못 들어가게(fail-closed)** 한다 — 랜딩 게이트는 "약한 접근 제한"이 목적이지만 관리자 게이트는 승인/삭제 같은 실제 데이터 조작 권한이라 기본값이 안전한 쪽(닫힘)이어야 한다.

`.env`/`.env.example`에 추가:
```
# 관리자 페이지(레시피 승인/삭제) 접근 토큰. URL에 ?admin_key=<이 값>이 붙어야만 통과한다.
# 비워두면 아무도 못 들어간다(기본 닫힘 — ACCESS_GATE_TOKEN과 반대 방향이니 주의).
# ADMIN_ACCESS_TOKEN=
```

### 4. 독립 관리자 페이지 — `st.navigation`/`st.Page`

- 기존 `app.py`를 `st.Page(app_main, ...)`로 감싸고, 관리자 화면을 별도 파일(`ui/screens/admin.py` 가칭)의 `st.Page`로 추가.
- `_admin_gate_ok()`를 통과했을 때만 관리자 Page의 콘텐츠를 렌더링(통과 못 하면 빈 화면 또는 조용히 아무것도 안 보여줌 — EC-01 참고).
- 공통 부트스트랩(`inject_css()`, `_start_model_warmup()` 등)은 두 Page 파일이 같이 부르는 공용 함수로 분리.

### 5. 관리자 페이지 UI

- `approved == 'N'`인 레시피(source 무관) 목록을 조회해 카드/행으로 표시(요리명, 재료, 조리순서 미리보기).
- 행마다 "등록"/"삭제" 버튼 — 기존 `my_recipes.py::screen_my_recipes()`의 목록+버튼 레이아웃 패턴을 참고(그 파일 자체는 삭제되지만 레이아웃 아이디어는 재사용 가능).

## Phase 2 설계 메모

> **2026-08-28 — Phase 2를 별도 스펙으로 확정**: `docs/specs/admin_voice_2fa.md` (토큰 1차 + ECAPA-TDNN 화자검증 2차, 랜덤 챌린지 재생공격 방어). 아래 메모는 그 스펙의 출발점이었고, 세부는 새 스펙을 따른다.

- 새 모듈 `orchestration/speaker_verify.py`(가칭): `speechbrain`(+`torchaudio`) 의존성, `speechbrain/spkrec-ecapa-voxceleb` 체크포인트 로컬 로드(EXAONE과 같은 패턴). GPU 호출은 `voice_io.py::_GPU_LOCK` 공유.
- 관리자 임베딩 저장: `data/admin_voiceprints/`(가칭)에 관리자별 임베딩. `verify_admin(audio_path) -> bool`은 등록된 모든 임베딩과 코사인 유사도 최댓값을 threshold와 비교(`intent_classifier.py`의 `best_per_intent` 패턴과 동일 구조) — 다중 관리자 자연 지원.
- 트리거 문구 "관리자 권한으로 로그인 할게요" 인식은 임베딩 유사도보다 **정확 문자열 매칭**(또는 편집거리 근사) 권장 — 고정 문구라 오탐 방지엔 그쪽이 안전.
- Enrollment: `.env`의 `ADMIN_ENROLL_TOKEN` + `?enroll_key=` 쿼리파라미터로 여는 별도 화면(위 `_admin_gate_ok()`와 같은 fail-closed 패턴) — 이름 입력 + `st.audio_input()`으로 음성 샘플 녹음 → 임베딩 추출/저장.
- 도입 시점에는 `ADMIN_ACCESS_TOKEN` 게이트를 완전히 대체할지, 토큰+화자검증 이중 게이트로 강화할지 결정 필요(둘 다 가능한 구조로 설계해둘 것).

## AC (Given-When-Then, Phase 1)

**AC-01 · 승인 안 된 레시피는 아무도 조회 못 함**
- GIVEN: `user_custom` 레시피가 `approved == 'N'`으로 저장돼 있음
- WHEN: 그 요리명으로 조회함(등록한 사람이든 아니든)
- THEN: 표준 조회 결과에 안 나오고 `PENDING_MESSAGE`가 나온다

**AC-02 · 관리자 승인 후 즉시 조회 가능**
- GIVEN: 관리자가 어떤 레시피의 "등록" 버튼을 누름
- WHEN: DB의 `approved`가 `'Y'`로 바뀜
- THEN: 같은 요리명으로 조회하면 정상적으로 찾아진다

**AC-03 · 삭제 시 완전히 사라짐**
- GIVEN: 관리자가 어떤 레시피의 "삭제" 버튼을 누름
- WHEN: 해당 `recipes` 행이 삭제됨
- THEN: 같은 요리명 조회 시 "아예 없음" 메시지가 나오고, 딸린 `recipe_steps` 행도 함께 삭제돼 있다

**AC-04 · 토큰 없이는 관리자 페이지 진입 불가**
- GIVEN: `ADMIN_ACCESS_TOKEN`이 설정돼 있음
- WHEN: `?admin_key=` 없이 또는 틀린 값으로 접근함
- THEN: 관리자 페이지 콘텐츠가 보이지 않는다

**AC-05 · 올바른 토큰으로 진입 가능**
- GIVEN: 위와 동일
- WHEN: `?admin_key=<올바른 값>`으로 접근함
- THEN: 관리자 페이지(승인 대기 목록)가 보인다

**AC-06 · 토큰 미설정 시 완전 차단**
- GIVEN: `.env`에 `ADMIN_ACCESS_TOKEN`이 비어있음
- WHEN: 아무 `?admin_key=` 값으로 접근하든
- THEN: 관리자 페이지에 절대 진입할 수 없다(fail-closed)

**AC-07 · 조회 실패 메시지 분기**
- GIVEN: 두 가지 경우 — (a) dish_name이 DB에 아예 없음, (b) dish_name은 있지만 전부 `approved == 'N'`
- WHEN: 각각 조회함
- THEN: (a)는 `DISH_NOT_FOUND_MESSAGE`, (b)는 `PENDING_MESSAGE`가 나온다 — 서로 다른 문구임을 확인
