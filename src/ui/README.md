# src/ui/ — Streamlit 화면 컴포넌트

`src/app.py`가 조립해서 쓰는 화면·세션·음성 입출력·디스패처 모듈. 의존 방향은 `screens/* → dispatch → voice_io/recipe_view → session`이고 순환이 없다.

| 파일 | 역할 |
|---|---|
| `session.py` | `init_state()` 세션 상태 초기화, `goto()` 화면 전환, `reset_to_start()` |
| `voice_io.py` | `listen()` 상시 마이크(streamlit-webrtc) 연결·재연결, VAD 세그먼트 수집, STT 제출. `speak()` TTS 제출·파일 캐시·자동 재생·다음 단계 프리페치. Cloudflare Realtime TURN 발급 |
| `dispatch.py` | `process_utterance()` 발화 처리 핵심. 홈/관리자/등록 단축어, 조리 중 전환 금지, LLM 요리명 추정, 의도분류 라우팅. `fallback_buttons()` 수동 이전/다시/다음 |
| `recipe_view.py` | `refresh_recipe_view()` recipes/recipe_steps 조회·세션 캐시, 재료 칩 변환 |
| `screens/cooking.py` | `start` / `recipe_confirm` / `cooking_step` / `cooking_complete` |
| `screens/register.py` | `unclassified` / `register_dish_name` → `register_ingredients` → `register_steps` → `complete` |
| `screens/login.py` | 로컬 로그인·회원가입, 구글 OAuth 복귀 처리 |
| `screens/my_recipes.py` | 마이레시피 목록, `edit_recipe` 수정, 삭제 |
| `screens/admin.py` | 관리자 페이지(레거시 승인 대기 목록·승인·삭제) |
| `screens/admin_auth.py` | 관리자 2차 인증: 랜덤 한글 단어 3개 낭독 → STT 일치 + 화자검증, IP당 5회 실패 시 60초 잠금 |
| `screens/admin_enroll.py` | 관리자 목소리 등록(`/enroll`) |

## 설계 포인트

- **마이크는 화면 밖에서 한 번만 마운트**한다. `app.py::main()`이 화면 컨테이너 밖에서 `listen()`을 부르므로 화면이 바뀌어도 WebRTC 연결이 유지된다.
- **화면 전환 잔상**(streamlit/streamlit#8360)은 화면 본문을 재사용 `st.empty()` 슬롯 하나에 그려 자식 수를 고정하는 방식으로 막는다. 보조로 `ui/theme.py::render_screen_cleanup()`이 다른 화면의 `<audio>`를 정지한다.
- **GPU 호출은 전부 `orchestration.gpu_worker_pool`의 `Future`**로 기다린다. 메인 스레드는 그동안 마이크 큐를 계속 비운다.
- **TTS 재생 중에는 재생 길이만큼 마이크 입력을 무시**해 자기 목소리를 다시 인식하지 않는다.
- `register_ingredients`/`register_steps`/`my_recipes`/`edit_recipe`는 텍스트 폼이 주 입력이라 자유발화를 받지 않고 "처음으로"/"취소"만 처리한다.
- 등록 진입은 로그인 필수이며, 조회는 `owner_id`를 함께 넘겨 본인 등록분만 보이게 한다.

관련 스펙: `docs/specs/app_e2e.md`, `tts_loading_overlay.md`, `dish_not_found_voice_notice.md`, `user_accounts_google_login.md`, `my_recipes.md`, `private_recipe_visibility.md`, `admin_voice_2fa.md`.
