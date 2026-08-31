# src/ — 전체 소스 맵

기준일: 2026-08-28 (계정/재료대체 제거, 관리자 승인·화자검증 2FA 반영 이후)

## 하위 폴더

| 폴더 | 담당 | 상태 요약 | 상세 |
|---|---|---|---|
| `orchestration/` | 김승욱 | 완성 — `pipeline.py`에 `handle_utterance()`(STT→의도분류→라우팅) 포함. 재료대체(`substitution.py`)·계정(`auth.py`/`identity.py`)은 2026-08-27 삭제, 관리자 화자검증(`speaker_verify.py`)은 2026-08-28 신규 | [orchestration/README.md](orchestration/README.md) |
| `llm/` | 김승욱 | 로컬 LLM(EXAONE-3.5-2.4B-Instruct)을 GPU 데스크탑 프로세스 안에 직접 로드해서 요리명 추출·등록의도 판단을 보조. 외부 API 아님(AGENTS.md 절대 원칙 참고) | [llm/README.md](llm/README.md) |
| `stt/` | 김승욱 | 모델 확정(whisper-large-v3-turbo) + 파인튜닝·평가 완료. 배포용 `stt_transcribe()`(faster-whisper/CTranslate2 int8)가 실사용 중이며, 환각(hallucination) 방어(상투구 블록리스트 + no_speech_prob 임계값)가 2026-08-28 추가됨 | [stt/README.md](stt/README.md) |
| `tts/` | 홍민하 | 파인튜닝 완료(HF Hub 업로드, 13에포크 체크포인트). `infer.py`의 `tts_synthesize()`가 실사용 중, `max_new_tokens`는 문장 길이 비례 동적 계산 | [tts/README.md](tts/README.md) |
| `ui/`(`src/ui/`) | 홍민하 | 실서비스 화면 컴포넌트 9개 모듈(session/voice_io/dispatch/recipe_view + screens 5개: cooking/register/admin/admin_auth/admin_enroll). 관리자 화면(`screens/admin*.py`)은 일반 흐름과 완전히 분리된 별도 Streamlit 페이지 | [ui/README.md](ui/README.md) |

## app.py

`src/app.py`가 실제 서비스 엔트리포인트다 — 마이크 입력 → STT(`stt.infer.stt_transcribe`) → `orchestration.pipeline.handle_utterance()` → TTS(`tts.infer.tts_synthesize`) 재생까지 한 화면 루프로 엮는다. 화면 컴포넌트는 최상위 `ui/theme.py`를 그대로 재사용한다(최상위 `ui/streamlit_screens/*.py`는 별도 프로토타입, 실서비스 경로 아님 — [ui/README.md](../ui/README.md) 참고).

`src/ui/`(session.py/voice_io.py/recipe_view.py/dispatch.py/screens/*.py)로 화면·세션 상태·STT/TTS 연결·발화 디스패처가 분리돼 있고, `listen()` 호출 자체는 화면 함수가 아니라 `app.py::main()`이 화면별 key 컨테이너 *밖에서* 직접 부른다 — Streamlit 화면 전환 잔상 버그(streamlit/streamlit#8360) 대응으로, 컨테이너 안에 마이크(webrtc) 컴포넌트가 있으면 화면 전환마다 재마운트되던 문제 때문이다. 잔상 자체는 `SCREENS[screen]()`을 재사용 `st.empty()` 슬롯에 담아 자식 엘리먼트 수를 고정하는 방식으로 대응하고, 보조로 `ui/theme.py::render_screen_cleanup()`(브라우저 JS로 다른 화면 소속 `<audio>` 정지 등)을 매 rerun 호출한다.

**요리명 추출**은 `orchestration/entity_extract_llm.py`(로컬 LLM 기반)과 `orchestration/recipe_search.py`(3단계 편집거리 보정)가 함께 담당한다 — 옛 규칙 기반 `orchestration/entity_extract.py::extract_dish_name()`은 파일만 남아있고 어디서도 호출되지 않는다.

**관리자 페이지**는 `src/ui/screens/admin.py`(승인 대기 목록/승인/삭제)·`admin_auth.py`(토큰+화자검증 챌린지)·`admin_enroll.py`(목소리 등록)로 구성되며, `app.py`의 `st.navigation`에서 일반 사용자 페이지와 별도 페이지로 등록된다(토큰 없으면 페이지 목록에도 안 나타남).

- 루트 `README.md`엔 YAML frontmatter(`sdk: streamlit`, `app_file: src/app.py`)가 있음 — HF Spaces 배포 메타데이터 쪽은 준비 완료
- 실행: `streamlit run src/app.py` 또는 로컬 GPU 데스크탑에서 `./run_local.sh`(venv/CUDA 라이브러리 경로를 자동으로 잡아줌, 기본값은 `src/app.py`)
