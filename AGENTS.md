# AGENTS.md

AI 코딩 에이전트(Claude Code, Codex, Cursor 등)가 이 저장소에서 작업할 때 따르는 공통 지침입니다. 어떤 도구를 쓰든 이 문서를 기준으로 합니다.

## 프로젝트 상태

셰프이어(ChefEar)는 화면을 보지 않고 음성만으로 레시피를 한 단계씩 진행하는 음성 레시피 에이전트입니다. AI Human 7기 1차 팀 프로젝트(2026-08-14 ~ 08-30, 마무리 09-01 ~ 09-08)로 개발이 끝났고, 2026-10-19~20에 **서버리스 웹앱으로 다시 구성**했습니다(`docs/specs/renewal_serverless.md`).

- 구조: 웹(`web/`, Vercel) → 상태 없는 API(`server/chefear_api`, Modal CPU) → STT·TTS(`inference/modal_app.py`, Modal GPU, 안 쓰면 0대) → Supabase(DB·파일·로그인). 서비스 전체가 로그인 전용입니다.
- 조리순서 데이터: 한국 가정식 **500개 큐레이션 레시피**(`docs/한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv`, 조리 단계 2,950건). 요리명·재료·조회수는 만개의레시피 실데이터, 조리순서 문장은 재료 기반 규칙 생성이며 `[TERM:용어]` 태그가 붙어 있다.
- 계정: Supabase Auth(구글·이메일). 레시피 등록은 로그인 필수이고 등록한 레시피는 **등록자 본인에게만** 조회된다. `api_standard`(500건)는 로그인한 모든 사용자에게 공개.
- 음성: 응답 문장은 미리 만든 mp3(`data/tts_manifest.csv`, 2,724개)를 먼저 재생하고, 없을 때만 실시간 TTS를 쓴다. 등록 레시피 음성은 저장 직후 별도 GPU 함수가 만든다.
- 제거된 것(리뉴얼): Streamlit 앱, RunPod·Docker 배포, 관리자 페이지·화자검증, 로컬 계정 모듈, GPU 워커 풀, 소개 페이지(`landing/`). 이력은 git과 `docs/decisions.md`.

## 절대 원칙

**서비스 실행 중 외부 LLM API 호출 금지.** OpenAI·Anthropic·Gemini·Groq 등 외부 LLM API를 런타임 코드에 넣지 않는다(지도 강사 가이드 요건). 의도분류는 sentence-transformers 임베딩 유사도, 요리명은 DB 요리명 매칭으로 처리한다. 로컬 추론은 이 원칙의 배제 대상이 아니다(EXAONE 코드는 `src/llm`에 남아 있으나 서비스 경로에서는 호출하지 않는다). 매칭 실패 시 지어내지 않고 "없다"고 안내한다. 개발 도구로 LLM을 쓰는 것은 허용된다.

## 기술 스택

- **웹**: Vite + React 18 + TypeScript, `@ricky0123/vad-web`(silero VAD), supabase-js
- **API**: FastAPI, Python 3.12(Modal 이미지). 입력은 `server/chefear_api/guard.py`를 거친다
- **의도분류**: sentence-transformers 5.6.1 (`jhgan/ko-sroberta-multitask`), threshold 0.5 + margin 0.05
- **STT**: `openai/whisper-large-v3-turbo` QLoRA 파인튜닝 → CTranslate2 int8 → faster-whisper 1.2.1, Modal L4 (`src/stt/`, `inference/stt_runtime.py`)
- **TTS**: `Qwen3-TTS-12Hz-1.7B` KSS LoRA 파인튜닝 → qwen-tts 0.1.1, Modal L4 (`src/tts/infer.py`)
- **DB**: Supabase 2.31.0 — `recipes`/`recipe_steps`/`users`(레거시) + `sessions`/`tts_assets`/`tts_jobs` (`db/schema.sql`, `db/migrate_renewal.sql`)
- **의존성 파일**: `requirements-server.txt`(API·테스트) / `requirements.txt`(스크립트·평가 최소) / `requirements-main.txt`(모델 로딩 스택) / `requirements-stt.txt`(STT 학습 고정 버전). 섞어 쓰지 않는다.
- **금지 패키지**: groq, piper-tts

## 작업 규칙

- **Spec 먼저**: 기능을 바꾸기 전에 `docs/specs/{기능명}.md`를 먼저 쓴다(`writing-specs` 스킬).
- **Out of Scope**: Spec에 없는 기능을 임의로 추가하지 않는다.
- **완료 기준**: `pytest tests/`(GPU·DB 불필요)와 `cd web && npm run build`가 통과해야 한다. 통과 없이 완료라고 보고하지 않는다. CI(`.github/workflows/ci.yml`)가 같은 검사를 한다.
- **사용자 입력**: 사용자가 입력한 글자는 반드시 `guard`를 거친다. 새 입력 지점을 만들면 `tests/renewal/test_guard.py`에 케이스를 더한다.
- **비밀값**: 키·토큰은 코드·문서·채팅에 쓰지 않는다. 서버 전용 키(`SUPABASE_KEY`)는 웹 번들에 들어가면 안 된다.
- **커밋 금지**: 에이전트는 git commit/push/add를 하지 않는다. 커밋은 사용자가 한다(사용자가 직접 요청한 경우는 예외).
- **주석**: 코드 설명만 남긴다. 날짜가 박힌 작업 일지형 주석은 쓰지 않는다(이력은 git과 `docs/decisions.md`).

더 볼 곳: `README.md`(전체 개요·평가 결과), `renewal/DEPLOY.md`(배포 절차), `renewal/API_CONTRACT.md`(API 계약), `docs/specs/renewal_serverless.md`(리뉴얼 스펙), `docs/ChefEar_PRD_SDD_v0.9.md`(요구사항·설계, 리뉴얼 전 기준), `docs/decisions.md`(의사결정 기록), `docs/specs/README.md`(스펙 목록과 상태).
