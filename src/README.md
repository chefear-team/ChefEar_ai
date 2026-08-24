# src/ — 전체 소스 맵

## 하위 폴더

| 폴더 | 담당 | 상태 요약 | 상세 |
|---|---|---|---|
| `orchestration/` | 김승욱 | 완성 — `pipeline.py`에 `handle_utterance()`(STT→의도분류→라우팅) 포함 | [orchestration/README.md](orchestration/README.md) |
| `llm/` | 김승욱 | **신규(2026-08-20)** — 로컬 LLM(EXAONE-3.5-2.4B-Instruct)을 GPU 데스크탑 프로세스 안에 직접 로드해서 요리명 추출을 보조. 외부 API 아님(AGENTS.md 1.5 원칙과 무관) | [llm/README.md](llm/README.md) |
| `stt/` | 하주성 | 모델 확정(whisper-large-v3-turbo) + 평가 완료. **배포용 `stt_transcribe()`(faster-whisper/CTranslate2 int8) 작성 완료(2026-08-19, `docs/specs/stt_deploy.md`)** — 오프라인 변환 스크립트 `export_ct2.py`도 신규 추가 | [stt/README.md](stt/README.md) |
| `tts/` | 홍민하 | 파인튜닝 완료(HF Hub 업로드, 13에포크 체크포인트, 2026-08-19 전체 리포 재업로드). `infer.py`에 `tts_synthesize()` 작성됨. ✅ roundtrip CER 0.0000(5문장 전부) — 품질 문제 해소. ⚠️ CPU 배포 속도 **재측정 완료, 여전히 FAIL**(26.11초/목표 5초) — GPU는 SDPA+`torch.compile`로 5.21초까지 근접. "닭을" 등 발음 오류 패치(`pronunciation.py`)도 추가 | [tts/README.md](tts/README.md) |
| `ui/`(`src/ui/`) | 홍민하 | **2026-08-22 채워짐** — `src/app.py`가 쓰는 세션/STT-TTS/디스패처/화면 모듈 7개(화면 컴포넌트화, 아래 참고). 최상위 `ui/`(별도 폴더, `theme.py`+mock 프로토타입)와는 다른 폴더 | [ui/README.md](ui/README.md) |

## app.py (확인: 2026-08-22)

`src/app.py` **작성 완료(`docs/specs/app_e2e.md` Spec 기준)** — 마이크 입력 → STT
(`stt.infer.stt_transcribe`) → `orchestration.pipeline.handle_utterance()` → TTS
(`tts.infer.tts_synthesize`) 재생까지 한 화면 루프로 엮었다. 화면 컴포넌트는 최상위
`ui/theme.py`를 그대로 재사용(최상위 `ui/streamlit_screens/*.py` mock 프로토타입은 시나리오
하드코딩이라 자유발화엔 못 씀, `docs/specs/app_e2e.md` 참고).

**2026-08-22 화면 컴포넌트화**: 원래 `src/app.py` 한 파일(1100줄+)에 다 있던 화면 13개·
세션 상태·STT/TTS 연결·발화 디스패처를 `src/ui/`(session.py/voice_io.py/recipe_view.py/
dispatch.py/screens/*.py)로 옮기고, `src/app.py`는 그것들을 조립하는 엔트리포인트(~130줄)만
남겼다 — 상세는 [ui/README.md](ui/README.md) 참고.

- 루트 `README.md`엔 YAML frontmatter(`sdk: streamlit`, `app_file: src/app.py`)가 이미 추가돼
  있음 — HF Spaces 배포 메타데이터 쪽은 준비 완료
- **요리명 추출은 2026-08-20부로 `orchestration/entity_extract_llm.py`(로컬 LLM 기반,
  `llm/infer.py`)로 전환됨** — 기존 `orchestration/entity_extract.py`의 `extract_dish_name()`(규칙
  기반)은 파일 자체는 그대로 남아있지만 `app.py`는 더 이상 호출하지 않음. 재료명 추출
  (`extract_substitution_ingredients()`)은 여전히 `entity_extract.py`(규칙 기반) 담당(`docs/specs/llm_dish_name_extract.md` 참고)
- 실행: `streamlit run src/app.py` 또는 로컬 GPU 데스크탑에서 `./run_local.sh src/app.py`
  (venv/CUDA 라이브러리 경로를 자동으로 잡아줌, 기본값은 `tests/test_ui.py`)
