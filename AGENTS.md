# AGENTS.md

AI 코딩 에이전트(Claude Code, Codex, Cursor 등)가 이 저장소에서 작업할 때 따르는 공통 지침입니다. 어떤 도구를 쓰든 이 문서를 기준으로 합니다.

## 프로젝트 상태

셰프이어(ChefEar)는 화면을 보지 않고 음성만으로 레시피를 한 단계씩 진행하는 음성 레시피 에이전트입니다. AI Human 7기 1차 팀 프로젝트(2026-08-14 ~ 08-30, 마무리 09-01 ~ 09-08)로 개발이 끝났고, **2026-09-10 기준 최종 정리본**입니다. 새 기능을 추가하는 단계가 아니라 문서·코드를 유지하는 단계입니다.

- 조리순서 데이터: 한국 가정식 **500개 큐레이션 레시피**(`docs/한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv`, 조리 단계 2,950건). 요리명·재료·조회수는 만개의레시피 실데이터, 조리순서 문장은 재료 기반 규칙 생성이며 `[TERM:용어]` 태그가 붙어 있다. 초기의 60,282건 전량 적재는 2026-09-01에 폐기됐다.
- 계정: 로컬 가입(sha256) + 구글 OAuth. 레시피 등록은 로그인 필수이고 등록한 레시피는 **등록자 본인에게만** 조회된다. `api_standard`(500건)는 전체 공개.
- 관리자 페이지(`/admin`): 토큰 + ECAPA-TDNN 화자검증 2단계. 2026-09-02 이전에 등록된 레거시 `approved='N'` 행 처리 전용.
- 배포: RunPod A40 Pod(Docker, `docs/runpod_deploy.md`) + Cloudflare Tunnel(`chefear.store`). 원래는 팀 RTX 5070 데스크탑이었다.

## 절대 원칙

**서비스 실행 중 외부 LLM API 호출 금지.** OpenAI·Anthropic·Gemini·Groq 등 외부 LLM API를 런타임 코드에 넣지 않는다(지도 강사 가이드 요건). 의도분류는 sentence-transformers 임베딩 유사도, 요리명 추정은 팀 GPU에 직접 로드한 로컬 LLM(`LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`)으로 처리한다. 로컬 추론은 이 원칙의 배제 대상이 아니다. 매칭 실패 시 지어내지 않고 "없다"고 안내한다. 개발 도구로 LLM을 쓰는 것은 허용된다.

## 기술 스택

- **언어**: Python 3.13 (상시 마이크가 의존하는 aioice가 3.14 미지원)
- **UI**: Streamlit 1.61.1, 엔트리포인트 `src/app.py`
- **의도분류**: sentence-transformers 5.6.1 (`jhgan/ko-sroberta-multitask`), threshold 0.5 + margin 0.05
- **요리명 추정**: 로컬 LLM EXAONE-3.5-2.4B (`src/llm/infer.py`)
- **STT**: `openai/whisper-large-v3-turbo` QLoRA 파인튜닝 → CTranslate2 int8 → faster-whisper 1.2.1 (`src/stt/infer.py`)
- **TTS**: `Qwen3-TTS-12Hz-1.7B` KSS LoRA 파인튜닝 → qwen-tts 0.1.1 (`src/tts/infer.py`)
- **GPU 실행**: 별도 프로세스 워커 풀(`src/orchestration/gpu_worker_pool.py`, 기본 3워커, spawn)
- **DB**: Supabase 2.31.0 — `recipes`/`recipe_steps`/`users` (`db/schema.sql`), SQL 함수 없이 Python 필터
- **관리자 화자검증**: speechbrain ECAPA-TDNN, CPU (`src/orchestration/speaker_verify.py`)
- **상시 마이크**: streamlit-webrtc 0.77.0 + silero-vad 6.2.1 + aiortc 1.15.0
- **의존성 파일**: `requirements.txt`(서빙 최소) / `requirements-main.txt`(모델 로딩 스택 포함) / `requirements-stt.txt`(STT 학습 고정 버전). 섞어 쓰지 않는다.
- **금지 패키지**: groq, piper-tts

## 작업 규칙

- **Spec 먼저**: 기능을 바꾸기 전에 `docs/specs/{기능명}.md`를 먼저 쓴다(`writing-specs` 스킬).
- **Out of Scope**: Spec에 없는 기능을 임의로 추가하지 않는다.
- **완료 기준**: `pytest tests/` 통과 없이 완료라고 보고하지 않는다.
- **커밋 금지**: 에이전트는 git commit/push/add를 하지 않는다. 커밋은 사용자가 한다.
- **주석**: 코드 설명만 남긴다. 날짜가 박힌 작업 일지형 주석은 쓰지 않는다(이력은 git과 `docs/decisions.md`).

더 볼 곳: `README.md`(전체 개요·평가 결과), `docs/ChefEar_PRD_SDD_v0.9.md`(요구사항·설계), `docs/ChefEar_설계서.md`(배포 관점 요약), `docs/ChefEar_팀_진행_가이드_v3.md`(디렉토리 구조·환경), `docs/decisions.md`(의사결정 기록), `docs/specs/README.md`(스펙 목록과 상태).
