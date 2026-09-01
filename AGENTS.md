# AGENTS.md

AI 코딩 에이전트(Claude Code, Codex, Cursor 등)가 이 저장소에서 작업할 때 따르는 공통 지침입니다. 어떤 도구를 쓰든 이 문서를 기준으로 합니다.

## 프로젝트 개요

셰프이어(ChefEar) — 요리 경험이 거의 없는 사용자가 칼질·반죽 등으로 손을 쓰기 어려운 상황에서도, 화면을 보지 않고 음성만으로 레시피를 한 단계씩 진행하는 음성 레시피 에이전트. STT(Whisper)·TTS(Qwen3-TTS) 도메인 파인튜닝이 핵심 딥러닝 과제이며, 둘 다 파인튜닝을 완료해 팀 GPU 데스크탑에서 상시 배포 중이다. 조리순서는 만개의레시피 실데이터(고유 요리명 60,282건) 조회로만 제공한다. 누구나 새 레시피를 발화로 등록할 수 있고(로그인 여부와 무관), 등록된 레시피는 관리자 승인(Y/N)을 거쳐야 조회에 노출된다. 개인화 저장(쿠키), 재료 대체 기능은 팀 결정으로 제거됐다(`docs/specs/remove_ingredient_substitution.md`). 일반 사용자 로그인/회원가입은 한 번 제거됐다가(`docs/specs/remove_user_accounts.md`) 2026-09-01 구글 OAuth 포함해 재도입됐다(`docs/specs/user_accounts_google_login.md`) — 로그인은 레시피 등록 시 `recipes.owner_id` 표시 용도로만 쓰이고, 마이레시피(내 레시피 목록/수정) 화면은 아직 범위 밖이다.

**절대 원칙 — 서비스 실행 중 외부 LLM API 호출 금지.** 의도분류는 sentence-transformers 임베딩 유사도 매칭으로 처리한다. 자유발화 속 요리명 추정과 "등록하고 싶다"는 의도 판단 보조에는 팀 GPU에 직접 로드해 구동하는 로컬 LLM(`LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`)을 쓰는데, 인터넷 너머 외부 서버로 텍스트를 보내는 API 호출이 아니라 완전한 로컬 추론이라 이 원칙의 배제 대상에 해당하지 않는다. 조리순서 제공은 실데이터 검색으로만 처리한다. OpenAI·Anthropic·Gemini·Groq 등 외부 LLM API를 런타임 코드(배포된 서비스가 실제로 응답하는 경로)에 넣지 않는다 — 지도 강사 가이드 요건이며 위반 시 요건 미충족으로 처리된다(`docs/ChefEar_PRD_SDD_v0.8.md` PART2 1.3, `docs/ChefEar_팀_진행_가이드_v2.md` 원칙 2). 코드 작성·문서화 등 개발 도구로 LLM을 쓰는 건 허용된다. 매칭 실패 시 그럴듯하게 지어내지 않고 "없다"고 정직하게 안내한다.

**관리자 기능(2026-08-28 추가)** — `/admin`은 일반 사용자 흐름과 분리된 별도 페이지다. 접근은 2단계: ①`?admin_key=` 토큰 ②랜덤 한글 단어 3개를 읽는 음성 화자검증(ECAPA-TDNN, `src/orchestration/speaker_verify.py`, CPU 실행). 승인 대기 중인(`approved='N'`) 사용자 등록 레시피를 열람·승인·삭제한다(`docs/specs/admin_recipe_approval.md`, `docs/specs/admin_voice_2fa.md`).

더 볼 곳: `docs/ChefEar_PRD_SDD_v0.8.md`(최신 PRD+SDD, 모르면 여기부터), `docs/ChefEar_설계서.md`(배포용 시스템 설계서 최신본 — 동명 `.pdf`는 2026-08-27 이전 낡은 버전이라 이 `.md`가 우선), `docs/ChefEar_팀_진행_가이드_v2.md`(팀 온보딩·디렉토리 구조), `docs/decisions.md`(아직 미확정인 항목).

## 기술 스택

- **언어**: Python 3.12 (env-main, 오케스트레이션·STT·TTS·서비스 통합환경) — 상시 마이크(streamlit-webrtc) 실행 venv는 3.13
- **UI/배포**: Streamlit 1.61.1, 엔트리포인트 `src/app.py`. 팀 GPU 데스크탑(RTX 5070, 12GB VRAM)에서 상시 구동하며 Cloudflare Tunnel로 공개 도메인(`chefear.store`)을 통해 노출한다
- **의도분류**: sentence-transformers 5.6.1 (`jhgan/ko-sroberta-multitask`) 임베딩 코사인 유사도 — LLM 아님. threshold(0.5)+margin(0.05) 판정
- **요리명 추정·등록의도 보조**: 로컬 LLM `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`(`src/llm/infer.py`) — `transformers.AutoModelForCausalLM`으로 팀 GPU에 직접 로드해 추론. 외부 API 호출 아님(위 절대 원칙 참고)
- **STT**: `openai/whisper-large-v3-turbo`를 QLoRA(4-bit NF4, peft 0.20.0/bitsandbytes 0.50.0)로 파인튜닝 → 배포는 CTranslate2 int8로 변환한 뒤 faster-whisper 1.2.1로 GPU 추론(`src/stt/infer.py`, `src/stt/export_ct2.py`)
- **TTS**: `Qwen3-TTS-12Hz-1.7B`를 KSS 데이터셋으로 QLoRA 파인튜닝 후 merge, `qwen-tts` 0.1.1로 GPU 추론(`src/tts/infer.py`)
- **DB**: Supabase 2.31.0 — `recipes`/`recipe_steps` 테이블(`db/schema.sql`), SQL 함수 대신 Python(supabase-py의 `.eq()`/`.ilike()`/`.range()` 등)에서 조건을 조립. `recipes.approved`('Y'/'N')로 관리자 승인 여부를 가른다. `users` 테이블은 스키마만 남아있고(계정 로그인 코드는 삭제됨) 지금은 아무 코드도 안 씀. 벡터 유사도 계산은 의도분류(임베딩)에만 쓰고 레시피 검색 자체는 문자열 매칭 기반이다
- **관리자 화자검증**: `speechbrain`(ECAPA-TDNN, `spkrec-ecapa-voxceleb`) + `torchaudio` — CPU 실행, `src/orchestration/speaker_verify.py`. GPU 4종(STT/임베딩/로컬LLM/TTS)이 이미 VRAM을 거의 다 써서 관리자 인증은 CPU로 분리
- **상시 마이크**: `streamlit-webrtc` 0.77.0 + `silero-vad` 6.2.1 + `aiortc` 1.15.0 — 세션당 한 번 연결해 화면 전환에도 유지, 발화 구간을 자동 분리
- **평가**: jiwer 4.0.0 (STT/TTS 파인튜닝 전후 WER/CER 비교)
- **의존성 파일**: `requirements.txt`(배포용 최소, HF Spaces가 자동 인식하는 유일한 파일명이라 이 이름을 유지) / `requirements-main.txt`(로컬 개발·학습 전체, `speechbrain` 포함) / `requirements-stt.txt`(STT 학습 확정 버전) — 역할이 다르므로 섞어 쓰지 않는다
- **금지 패키지**: groq, piper-tts (팀 결정으로 배제, `docs/ChefEar_팀_진행_가이드_v2.md` 6.2)

## Spec 먼저, 구현은 그다음

기능을 에이전트에게 시키기 전에 Spec을 먼저 작성하세요 — 형식·섹션 구성은 `writing-specs` 스킬 참고.

## Out of Scope 원칙

에이전트는 Spec에 없는 기능을 임의로 추가하지 않습니다. "이왕이면"으로 범위를 넓히지 않습니다.

## 완료 기준

테스트(AC 기준) 통과 없이 "완료"라고 보고하지 않습니다.
