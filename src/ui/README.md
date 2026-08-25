# src/ui/ — 담당: 홍민하 (Streamlit 화면 컴포넌트)

## 이 폴더가 하는 일

`src/app.py`(엔트리포인트, ~270줄)가 조립해서 쓰는 화면·상태·발화 처리 모듈들.
2026-08-22부터 실제로 쓰인다 — 원래 `src/app.py` 한 파일(1100줄+)에 다 있던 걸 화면
컴포넌트화하면서 여기로 옮겼다.

**2026-08-25부터**: `listen()`/`listen_background_only()` 호출 자체는 각 `screen_*()`
함수가 아니라 `app.py::main()`이 화면별 `st.container(key=f"screen_{screen}")` *밖에서*
직접 부른다 — Streamlit 미해결 버그(streamlit/streamlit#8360)로 화면마다 컨테이너를
감쌌더니, 컨테이너 key가 바뀔 때마다 그 안의 webrtc 마이크 컴포넌트까지 재마운트되던
문제 대응. 그래서 `screens/cooking.py`/`screens/register.py`의 문자열 직접 비교 화면
(recipe_confirm/register_intro/register_dish_name)은 `screen_*()`(렌더링)와
`handle_*()`(app.py가 잡아온 발화 처리, 예: `handle_recipe_confirm()`)로 분리돼 있다 —
`app.py`가 화면 상태에 따라 `process_utterance()`/`handle_*()`/`listen_background_only()`
중 무엇을 부를지 분기한다.

**이름 주의**: 이 폴더(`src/ui/`)는 `src`가 `sys.path`에 있어서 `ui.session`처럼 패키지로
import된다. 저장소 루트의 최상위 `ui/`(`theme.py` 등, `src/app.py`가 별도로
`sys.path.insert(0, PROJECT_ROOT/"ui")` 해줘서 `from theme import ...`로 씀)와는 이름만
같고 서로 다른 경로다 — 헷갈리지 않게 각 파일 상단에도 같은 안내를 남겨뒀다.

## 파일 구성 (확인: 2026-08-25)

- `session.py` — 세션 상태 초기화(`init_state`), 화면 전환(`goto`), 쿠키 owner_id(`get_owner_id`)
- `voice_io.py` — STT/TTS 연결(`speak`/`listen`), 다음 단계 음성 백그라운드 프리페치
  (`prefetch_next_step_audio`)
- `recipe_view.py` — `recipes` 테이블 조회/캐싱(`refresh_recipe_view`), 재료 칩 변환
- `dispatch.py` — 발화 처리 핵심 디스패처(`process_utterance`), 수동 이전/다시/다음
  버튼(`fallback_buttons`)
- `screens/cooking.py` — start/recipe_confirm/cooking_step (조리 진행 핵심 흐름).
  `handle_recipe_confirm()`도 여기서 export(위 2026-08-25 항목 참고)
- `screens/register.py` — no_match/unclassified/register_*/complete (신규 레시피 등록 흐름).
  `handle_register_intro()`/`handle_register_dish_name()`도 여기서 export
- `screens/my_recipes.py` — login/my_recipes/edit_recipe (마이 레시피)

의존 방향은 `screens/* → dispatch → voice_io/recipe_view → session`이고 순환 없음
(`app.py`는 이 위에서 `screens/*`·`dispatch`·`voice_io.listen`을 모두 직접 조립하는
엔트리포인트라 이 방향에 포함되지 않음).
`orchestration/`(DB·의도분류·재료대체 등 백엔드 로직)은 이미 준비돼 있어서 그대로 가져다
쓴다 — 이 폴더는 그 위에 Streamlit 화면만 얹는 계층이다.

최상위 `ui/streamlit_screens/*.py`(mock 프로토타입)는 여전히 실제 서비스에서 안 쓴다 —
`src/app.py` 최상단 docstring 참고(자유발화를 못 받는 하드코딩 시나리오 방식이라서).

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 3.4(UI, 최소구현 우선), `docs/ChefEar_팀_진행_가이드_v2.md` 디렉토리 구조,
`docs/specs/app_e2e.md`.
