# src/ — 전체 소스 맵

## 하위 폴더

| 폴더 | 담당 | 상태 요약 | 상세 |
|---|---|---|---|
| `orchestration/` | 김승욱 | 완성 — `pipeline.py`에 `handle_utterance()`(STT→의도분류→라우팅) 포함 | [orchestration/README.md](orchestration/README.md) |
| `llm/` | 김승욱 | **신규(2026-08-20)** — 로컬 LLM(EXAONE-3.5-2.4B-Instruct)을 GPU 데스크탑 프로세스 안에 직접 로드해서 요리명 추출을 보조. 외부 API 아님(AGENTS.md 1.5 원칙과 무관) | [llm/README.md](llm/README.md) |
| `stt/` | 하주성 | 모델 확정(whisper-large-v3-turbo) + 평가 완료. **배포용 `stt_transcribe()`(faster-whisper/CTranslate2 int8) 작성 완료(2026-08-19, `docs/specs/stt_deploy.md`)** — 오프라인 변환 스크립트 `export_ct2.py`도 신규 추가 | [stt/README.md](stt/README.md) |
| `tts/` | 홍민하 | 파인튜닝 완료(HF Hub 업로드, 13에포크 체크포인트, 2026-08-19 전체 리포 재업로드). `infer.py`에 `tts_synthesize()` 작성됨. ✅ roundtrip CER 0.0000(5문장 전부) — 품질 문제 해소. HF Spaces CPU Basic은 목표 응답시간(5초) 미달로 배포 방향에서 제외되고 GPU 기반(팀 데스크탑+Tailscale)으로 전환 결정됨(2026-08-19, `docs/decisions.md` #2) — 실서비스는 이 GPU 경로로 동작 중. `max_new_tokens`는 고정 상수를 여러 번 올리다 2026-08-26부로 문장 길이 비례 동적 계산으로 전환. "닭을" 등 발음 오류 패치(`pronunciation.py`)도 추가 | [tts/README.md](tts/README.md) |
| `ui/`(`src/ui/`) | 홍민하 | **2026-08-22 채워짐, 2026-08-25 재구조화** — `src/app.py`가 쓰는 세션/STT-TTS/디스패처/화면 모듈 7개(화면 컴포넌트화, 아래 참고). `listen()` 호출은 이제 화면 함수가 아니라 `app.py::main()`이 직접 부름. 최상위 `ui/`(별도 폴더, `theme.py`+mock 프로토타입)와는 다른 폴더 | [ui/README.md](ui/README.md) |

## app.py (확인: 2026-08-26)

`src/app.py` **작성 완료(`docs/specs/app_e2e.md` Spec 기준)** — 마이크 입력 → STT
(`stt.infer.stt_transcribe`) → `orchestration.pipeline.handle_utterance()` → TTS
(`tts.infer.tts_synthesize`) 재생까지 한 화면 루프로 엮었다. 화면 컴포넌트는 최상위
`ui/theme.py`를 그대로 재사용(최상위 `ui/streamlit_screens/*.py` mock 프로토타입은 시나리오
하드코딩이라 자유발화엔 못 씀, `docs/specs/app_e2e.md` 참고).

**2026-08-22 화면 컴포넌트화**: 원래 `src/app.py` 한 파일(1100줄+)에 다 있던 화면 13개·
세션 상태·STT/TTS 연결·발화 디스패처를 `src/ui/`(session.py/voice_io.py/recipe_view.py/
dispatch.py/screens/*.py)로 옮겼다.

**2026-08-25 재구조화**: 화면 전환 잔상(Streamlit 미해결 버그) 대응으로 화면마다
`st.container(key=...)`로 감쌌더니 그 안의 마이크(webrtc) 컴포넌트가 화면 전환마다
재마운트되는 문제가 드러나, `listen()`/`listen_background_only()` 호출 자체를 각
`screen_*()` 밖으로 빼서 `app.py::main()`이 컨테이너 밖에서 직접 호출하도록 변경했다 —
그 결과 `app.py`가 다시 커져서 지금은 ~270줄(단순 조립 엔트리포인트가 아니라 화면별 발화
라우팅까지 담당). 상세는 [ui/README.md](ui/README.md) 참고.

**2026-08-25/26 추가**: 위 컨테이너 픽스로도 못 잡는 잔상에 대한 최후 수단으로
`ui/theme.py::render_screen_cleanup()`(브라우저 JS로 이전 화면 DOM 직접 청소)을 매 rerun
호출. 등록 기능(버튼+음성)을 로그인 여부로 게이팅하고 로그인 성공 시 이전 화면으로 복귀
(`_login_return_screen`). 모델 워밍업(`_start_model_warmup()`, 옛 `_warm_up_models()`)을
메인 스레드 블로킹에서 백그라운드 스레드로 전환해 마이크 연결과 병렬로 진행되게 함.

- 루트 `README.md`엔 YAML frontmatter(`sdk: streamlit`, `app_file: src/app.py`)가 이미 추가돼
  있음 — HF Spaces 배포 메타데이터 쪽은 준비 완료
- **요리명 추출은 2026-08-20부로 `orchestration/entity_extract_llm.py`(로컬 LLM 기반,
  `llm/infer.py`)로 전환됨** — 기존 `orchestration/entity_extract.py`의 `extract_dish_name()`(규칙
  기반)은 파일 자체는 그대로 남아있지만 `app.py`는 더 이상 호출하지 않음. 재료명 추출
  (`extract_substitution_ingredients()`)은 여전히 `entity_extract.py`(규칙 기반) 담당(`docs/specs/llm_dish_name_extract.md` 참고)
- 실행: `streamlit run src/app.py` 또는 로컬 GPU 데스크탑에서 `./run_local.sh src/app.py`
  (venv/CUDA 라이브러리 경로를 자동으로 잡아줌, 기본값은 `tests/test_ui.py`)
