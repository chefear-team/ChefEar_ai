# src/ui/ — 담당: 홍민하 (Streamlit 화면 컴포넌트)

## 이 폴더가 하는 일

`src/app.py`(엔트리포인트, ~130줄)가 조립해서 쓰는 화면·상태·발화 처리 모듈들.
2026-08-22부터 실제로 쓰인다 — 원래 `src/app.py` 한 파일(1100줄+)에 다 있던 걸 화면
컴포넌트화하면서 여기로 옮겼다.

**이름 주의**: 이 폴더(`src/ui/`)는 `src`가 `sys.path`에 있어서 `ui.session`처럼 패키지로
import된다. 저장소 루트의 최상위 `ui/`(`theme.py` 등, `src/app.py`가 별도로
`sys.path.insert(0, PROJECT_ROOT/"ui")` 해줘서 `from theme import ...`로 씀)와는 이름만
같고 서로 다른 경로다 — 헷갈리지 않게 각 파일 상단에도 같은 안내를 남겨뒀다.

## 파일 구성 (확인: 2026-08-22)

- `session.py` — 세션 상태 초기화(`init_state`), 화면 전환(`goto`), 쿠키 owner_id(`get_owner_id`)
- `voice_io.py` — STT/TTS 연결(`speak`/`listen`), 다음 단계 음성 백그라운드 프리페치
  (`prefetch_next_step_audio`)
- `recipe_view.py` — `recipes` 테이블 조회/캐싱(`refresh_recipe_view`), 재료 칩 변환
- `dispatch.py` — 발화 처리 핵심 디스패처(`process_utterance`), 수동 이전/다시/다음
  버튼(`fallback_buttons`)
- `screens/cooking.py` — start/recipe_confirm/cooking_step (조리 진행 핵심 흐름)
- `screens/register.py` — no_match/unclassified/register_*/complete (신규 레시피 등록 흐름)
- `screens/my_recipes.py` — login/my_recipes/edit_recipe (마이 레시피)

의존 방향은 `screens/* → dispatch → voice_io/recipe_view → session`이고 순환 없음.
`orchestration/`(DB·의도분류·재료대체 등 백엔드 로직)은 이미 준비돼 있어서 그대로 가져다
쓴다 — 이 폴더는 그 위에 Streamlit 화면만 얹는 계층이다.

최상위 `ui/streamlit_screens/*.py`(mock 프로토타입)는 여전히 실제 서비스에서 안 쓴다 —
`src/app.py` 최상단 docstring 참고(자유발화를 못 받는 하드코딩 시나리오 방식이라서).

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 3.4(UI, 최소구현 우선), `docs/ChefEar_팀_진행_가이드_v2.md` 디렉토리 구조,
`docs/specs/app_e2e.md`.
