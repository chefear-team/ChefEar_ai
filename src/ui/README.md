# src/ui/ — 담당: 홍민하 (Streamlit 화면 컴포넌트)

기준일: 2026-08-28

## 이 폴더가 하는 일

`src/app.py`(엔트리포인트)가 조립해서 쓰는 화면·상태·발화 처리 모듈들. 원래 `src/app.py` 한 파일에 다 있던 걸 화면 컴포넌트화하면서 여기로 옮겼다.

**`listen()` 호출 위치**: 각 `screen_*()` 함수가 아니라 `app.py::main()`이 화면별 `st.container(key=f"screen_{screen}")` *밖에서* 직접 부른다 — Streamlit 미해결 버그(streamlit/streamlit#8360)로 화면마다 컨테이너를 감쌌더니, 컨테이너 key가 바뀔 때마다 그 안의 webrtc 마이크 컴포넌트까지 재마운트되던 문제 대응. 그래서 문자열 직접 비교로 처리하는 화면(recipe_confirm/register_dish_name)은 `screen_*()`(렌더링)와 `handle_*()`(app.py가 잡아온 발화 처리, 예: `handle_recipe_confirm()`)로 분리돼 있다 — `app.py`가 화면 상태에 따라 `process_utterance()`/`handle_*()`/`listen()` 반환값 무시 중 무엇을 부를지 분기한다.

**화면 전환 잔상 대응(2026-08-28 재구성)**: `app.py::main()`이 `SCREENS[screen]()`을 재사용 `st.empty()` 슬롯에 담아 렌더링한다 — 슬롯 자식은 항상 1개로 고정되므로 "이 위치의 엘리먼트 수가 줄면 이전 실행분이 안 지워지는" #8360 트리거 조건 자체를 회피한다. 화면 본문 뒤에 빈 `st.empty()` 패딩(`_SCREEN_TRAILING_PAD`)도 붙여, 화면 간 본문 길이 차이가 이 패딩 구간 안에서 흡수되게 한다. 보조로 `ui/theme.py::render_screen_cleanup()`(브라우저 JS, 다른 화면 소속 `<audio>` 정지·특정 텍스트 마커 잔상 정리)을 매 rerun 호출한다. 마이크(webrtc) 컴포넌트는 이 청소 대상에서 완전히 제외된다(상시 연결 유지가 우선).

**등록은 로그인 불필요(2026-08-27)**: 계정 시스템 전체가 삭제되면서 등록 게이트도 같이 없어졌다 — `dispatch.py::process_utterance()`의 "등록" 음성 단축도 로그인 여부와 무관하게 항상 `register_dish_name`으로 보낸다. 저장 시 `approved='N'`으로 관리자 승인 대기 상태가 된다(승인/거부는 `screens/admin.py`, 일반 사용자 화면과 완전히 분리된 별도 페이지).

**이름 주의**: 이 폴더(`src/ui/`)는 `src`가 `sys.path`에 있어서 `ui.session`처럼 패키지로 import된다. 저장소 루트의 최상위 `ui/`(`theme.py` 등, `src/app.py`가 별도로 `sys.path.insert(0, PROJECT_ROOT/"ui")` 해줘서 `from theme import ...`로 씀)와는 이름만 같고 서로 다른 경로다 — 헷갈리지 않게 각 파일 상단에도 같은 안내를 남겨뒀다.

## 파일 구성

- `session.py` — 세션 상태 초기화(`init_state`), 화면 전환(`goto`)
- `voice_io.py` — STT/TTS 연결(`speak`/`listen`), 다음 단계 음성 백그라운드 프리페치, 상시 마이크(webrtc) 연결·재연결·VAD 세그먼테이션
- `recipe_view.py` — `recipes`/`recipe_steps` 조회·세션 캐시(`refresh_recipe_view`), 재료 칩 변환
- `dispatch.py` — 발화 처리 핵심 디스패처(`process_utterance`), 수동 이전/다시/다음 버튼(`fallback_buttons`), 관리자 페이지 진입 발화 트리거(`_is_admin_trigger`)
- `screens/cooking.py` — start/recipe_confirm/cooking_step/cooking_complete (조리 진행 핵심 흐름). `handle_recipe_confirm()`도 여기서 export
- `screens/register.py` — unclassified/register_*/complete (신규 등록 흐름, 로그인 불필요). `handle_register_intro()`/`handle_register_dish_name()`도 여기서 export
- `screens/admin.py` — 관리자 페이지 본체(승인 대기 목록·승인·삭제)
- `screens/admin_auth.py` — 관리자 2차 인증(랜덤 단어 챌린지 + STT + 화자검증)
- `screens/admin_enroll.py` — 관리자 목소리 최초 등록 화면(`/enroll`)

2026-08-27 삭제됨: `screens/my_recipes.py`(로그인/마이레시피/레시피수정 — 계정 시스템 제거), `no_match` 화면(조회 실패를 화면 전환 없이 현재 화면 음성 안내로 대체).

의존 방향은 `screens/* → dispatch → voice_io/recipe_view → session`이고 순환 없음(`app.py`는 이 위에서 `screens/*`·`dispatch`·`voice_io.listen`을 모두 직접 조립하는 엔트리포인트라 이 방향에 포함되지 않음). `orchestration/`(DB·의도분류·등록·관리자 화자검증 등 백엔드 로직)은 이미 준비돼 있어서 그대로 가져다 쓴다 — 이 폴더는 그 위에 Streamlit 화면만 얹는 계층이다.

최상위 `ui/streamlit_screens/*.py`(초기 화면 프로토타입, 목업 데이터)는 실제 서비스에서 안 쓴다 — `src/app.py` 최상단 docstring 참고. 다만 최상위 `ui/theme.py`(CSS·아이콘·카드 등 공용 컴포넌트)와 `ui/mic_vad.py`(VAD 세그먼터)는 실서비스가 그대로 import해서 쓴다 — 프로토타입 폴더 전체가 죽은 코드는 아니다.

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 3.3~3.4(화면 구성), `docs/ChefEar_팀_진행_가이드_v2.md` 디렉토리 구조, `docs/specs/app_e2e.md`, `docs/specs/admin_recipe_approval.md`, `docs/specs/admin_voice_2fa.md`.
