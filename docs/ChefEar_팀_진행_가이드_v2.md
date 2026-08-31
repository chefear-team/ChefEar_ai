# 셰프이어(ChefEar) — 팀 진행 가이드 (v2)

작성자: 김승욱(팀장) · 기준일: 2026-08-28 — 현재 배포·실사용 중인 소스 기준으로 전면 재작성(계정/재료대체 제거, 관리자 승인·화자검증 2FA 반영)

이 문서는 팀원 전원이 읽고 시작하는 문서입니다. 지금 서비스가 실제로 어떤 구조로 동작하고 있는지, 새로 합류하는 사람이 무엇부터 봐야 하는지를 담았습니다.

---

## 0. 한 줄 정의

부모님과 따로 살기 시작한 직후, 요리를 거의 해본 적 없는 완전 초보가, 칼질·반죽 등으로 손을 못 쓰는 상황에서 음성으로 레시피를 한 단계씩 안내받고 진행하는 에이전트. 로그인 없이 누구나 새 레시피를 발화로 등록할 수 있고, 등록된 레시피는 관리자 승인을 거쳐야 다른 사람에게도 공개된다.

**2026-08-27 팀 결정**: 계정 로그인/회원가입/개인화 저장, 재료 대체(진행 중 재료 치환·취소) — 두 기능은 v0.8 최초 작성 시점엔 Must였으나 실사용 리포트 기반으로 팀이 걷어냈습니다(`docs/specs/remove_user_accounts.md`, `docs/specs/remove_ingredient_substitution.md`). 이 문서 어디에도 "구현 예정"으로 남겨두지 않습니다.

---

## 1. 반드시 먼저 이해해야 할 핵심 원칙

### 원칙 1. 딥러닝 과제 범위는 STT/TTS 둘 다입니다

파인튜닝하는 건 STT(`openai/whisper-large-v3-turbo`)와 TTS(`Qwen3-TTS-12Hz-1.7B`) 두 개입니다. 둘 다 QLoRA로 파인튜닝했고, 파인튜닝 전/후 WER·CER·청취 비교를 발표 자료에 넣습니다.

### 원칙 2. 서비스 응답 경로에 외부 LLM API를 넣지 않습니다

지도 강사 가이드("1차 팀 프로젝트 가이드")에 따라, 완성된 서비스가 사용자 요청에 응답하는 동안 OpenAI·Anthropic·Gemini·Groq 같은 외부 LLM API를 호출하는 코드가 있으면 요건 미충족입니다.

| 상황 | 처리 방식 |
| --- | --- |
| 의도 판단(다음/재료대체/등록 등) | 임베딩 유사도 매칭(sentence-transformers) — 발화를 벡터로 바꿔서 미리 준비한 예문 중 제일 비슷한 걸 고름 |
| 자유발화 속 요리명 추정, "등록하고 싶다" 의도 보조 판단 | **로컬 LLM**(`LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`)을 팀 GPU 데스크탑에 직접 로드해서 그 자리에서 추론. 인터넷 너머 외부 서버로 텍스트를 보내는 게 아니라서 강사 가이드가 금지하는 "외부 LLM API 호출"에 해당하지 않음 |
| 재료대체 요청이 DB에 없음 | 그 자리에서 답을 지어내지 않고 "그런 레시피는 없어요"라고 정직하게 말함 |
| 조리순서 문의 | 60,282건 표준 데이터(사전 적재된 실데이터)에서 조회만 함 |

개발 도구로서 LLM(Claude 등)을 코드 작성·자료조사·문서화에 쓰는 건 자유롭게 허용됩니다. 경계선은 "언제, 어디서 추론이 일어나느냐"입니다 — 개발 중이거나 팀 GPU에서 직접 도는 로컬 모델이면 OK, 서비스가 응답하는 순간 남의 서버(외부 API)로 텍스트가 나가면 안 됩니다.

### 원칙 3. 조리순서 데이터 구성은 있는 그대로 설명합니다

요리명·재료·인분수·조회수 등 메타데이터(60,282건)는 만개의레시피 실데이터입니다. 동일 요리명이 여러 건 있을 때는 조회수(INQ_CNT) 1위를 표준 레시피로 채택합니다. 조리순서(`COOKING_STEPS`) 본문 텍스트는 원본 데이터에 해당 항목 자체가 없어서, 배포 전 단계에서 재료 목록을 근거로 LLM(ChatGPT)이 작성해 채워 넣은 것이고 `source=api_standard`로 함께 태깅됩니다. 이 작업은 서비스가 켜지기 전에 끝난 1회성 오프라인 데이터 준비이며, 서비스는 이렇게 준비된 문장을 조회만 할 뿐 실행 중에 새로 생성하지 않습니다. 이 구성을 숨기지 않고 발표에서도 그대로 설명합니다(아래 원칙 4와 같은 태도).

표준 데이터 밖의 요리명을 요청받으면 정직하게 "없다"고 안내하고, 로그인 여부와 무관하게(계정 시스템 자체가 없음) 누구나 신규 등록으로 유도합니다.

### 원칙 4. 절대 임의로 지어내지 않습니다

애매한 상황이 생기면 데이터를 직접 확인하고, 없으면 "없다"고 인정합니다. 그럴듯하게 짐작해서 채우지 않습니다. 로컬 LLM(EXAONE)이 요리명을 잘못 짐작하거나 실패해도, 그럴듯한 다른 답으로 둔갑시키지 않고 "요리명 없음"과 동일하게 안전한 기본값으로 처리합니다.

---

## 2. 디렉토리 구조

```
proj1-a/
├── README.md                         # 프로젝트 소개·팀 정보·HF Spaces frontmatter
├── AGENTS.md                         # AI 에이전트 공통 지침(원본). CLAUDE.md는 이 문서를 그대로 참조
├── requirements.txt                  # 배포용 최소 의존성 — HF Spaces가 자동 인식하는 유일한 파일명
├── requirements-main.txt             # env-main(로컬 개발·학습 전체) 의존성
├── requirements-stt.txt              # STT 학습 확정 버전
├── run_local.sh                      # 로컬 GPU 데스크탑에서 streamlit 앱을 실행하는 스크립트
├── .env / .env.example / .env.example.local   # 환경변수(.env는 git 미추적, 값은 로컬에만 존재)
├── .streamlit/config.toml
├── .github/                          # PR 템플릿, secret-scan 워크플로
│
├── docs/
│   ├── ChefEar_PRD_SDD_v0.8.md           # 최신 PRD+SDD, 모르면 여기부터
│   ├── ChefEar_설계서.md                 # 배포용 시스템 설계서 최신본
│   ├── ChefEar_설계서.pdf                 # 위 .md의 낡은 PDF 버전(2026-08-27 이전, 재변환 필요)
│   ├── ChefEar_팀_진행_가이드_v2.md       # 이 문서
│   ├── ChefEar_경쟁사분석.md
│   ├── decisions.md                      # 아직 확정되지 않은 항목 추적
│   ├── stt.md                            # STT 학습 환경 스냅샷
│   ├── specs/                            # 기능별 Spec(Why·Goal·What·How·AC)
│   ├── meetings/                         # 회의록
│   └── audits/                           # 조사·디버깅 기록
│
├── src/
│   ├── app.py                        # 실제 서비스 엔트리포인트 — streamlit run src/app.py
│   ├── orchestration/                # 김승욱 담당
│   │   ├── intent_classifier.py          # 임베딩 유사도 의도분류 — classify_intent()
│   │   ├── entity_extract.py             # 정규식 기반 요리명 추출 v1 — 지금은 어디서도 안 부르는 죽은 코드(recipe_search.py로 대체됨)
│   │   ├── entity_extract_llm.py         # 로컬 LLM 기반 요리명 추정·등록의도 판단
│   │   ├── recipe_search.py              # 표준레시피 선정(approved='Y'만) · 요리명 3단계 보정
│   │   ├── registration.py               # 신규 등록 세션, 저장(approved='N')/삭제
│   │   ├── speaker_verify.py             # 관리자 화자검증(ECAPA-TDNN, CPU) — 2026-08-28 신규
│   │   ├── pipeline.py                   # 발화 하나를 의도별로 라우팅하는 조립 함수
│   │   ├── db.py                         # Supabase 클라이언트(자격증명 없으면 mock 전환)
│   │   ├── mock_client.py                # 로컬 개발용 가짜 클라이언트
│   │   └── load_data.py                  # 표준 레시피 CSV → Supabase 적재 스크립트
│   ├── llm/infer.py                  # 로컬 LLM(EXAONE) 로드·추론
│   ├── stt/                          # 김승욱 담당
│   │   ├── infer.py                      # 배포용 STT 추론(faster-whisper, CTranslate2 int8) — 환각 방어 포함
│   │   ├── export_ct2.py                 # 파인튜닝 체크포인트 → CTranslate2 변환(오프라인 1회)
│   │   ├── prepare_data.py / finetune_whisper.py  # 학습 데이터 준비·QLoRA 파인튜닝
│   │   └── compare_realtime_models.py    # 파인튜닝 전/후 비교
│   ├── tts/                          # 홍민하 담당
│   │   ├── infer.py                      # 배포용 TTS 추론(Qwen3-TTS)
│   │   ├── pronunciation.py              # TTS 직전 발음 보정 테이블
│   │   └── prepare_data.py / finetune_qwen3tts.py  # 학습 데이터 준비·QLoRA 파인튜닝
│   └── ui/                           # 실제 서비스 화면 컴포넌트 — src/app.py가 조립
│       ├── session.py                    # 세션 상태 초기화, 화면 전환
│       ├── voice_io.py                   # 상시 마이크(WebRTC) 연결, STT/TTS 호출·캐싱
│       ├── dispatch.py                   # 발화 → 의도 처리 → 화면 전환 디스패처
│       ├── recipe_view.py                # 화면에 보여줄 레시피 뷰 갱신
│       └── screens/                      # cooking.py · register.py · admin.py · admin_auth.py · admin_enroll.py
│
├── ui/                                # 화면 시각 자산 + 초기 목업
│   ├── theme.py                          # CSS/아이콘/카드 등 공용 컴포넌트(실서비스가 그대로 재사용)
│   ├── mic_vad.py                        # silero-vad 기반 발화 구간 분리기(실서비스가 재사용)
│   └── streamlit_screens/                # 초기 버튼 기반 목업 — 화면 흐름 검증용, 실서비스 경로 아님
│
├── db/
│   ├── schema.sql                    # recipes / recipe_steps / users 테이블 DDL(Supabase SQL Editor에 수동 실행)
│   └── README.md
│
├── data/
│   ├── standard/                     # 요리명별 조리과정 CSV
│   ├── kadx_raw/                     # KADX 원본 시드 CSV
│   ├── intent_examples/기준예문.csv   # 의도분류 기준 예문
│   ├── kss/                          # TTS·STT 학습 원본 음성(KSS, CC BY-NC-SA 4.0)
│   ├── synthesized/                  # STT 학습용 합성음(파인튜닝된 TTS가 생성)
│   └── evaluation_scripts/           # WER/CER 평가용 텍스트
│
├── models/                            # 학습 산출물 로컬 스테이징(git 미추적)
│   ├── stt_finetuned/ct2_int8/            # 배포가 실제로 읽는 CTranslate2 변환본
│   └── tts_finetuned/
│
├── results/
│   ├── stt/
│   └── tts/                           # WER/CER/응답속도 측정 결과 CSV
│
├── landing/                           # 메인 서비스와 분리된 소개 페이지(로컬 전용 Streamlit)
│
└── tests/                             # pytest 스위트(단위 테스트 + 통합 시나리오)
```

배포된 모델(어댑터·병합본)은 Hugging Face Hub의 팀 저장소(`leeony/chefear-stt-large-v3-turbo`, `kimseunguk/qwen3-tts-kss-finetuned`, CTranslate2 변환본은 `kimseunguk/chefear-stt-ct2-int8`)에서 앱 시작 시 내려받습니다 — 가중치를 git 저장소에 직접 커밋하지 않습니다.

---

## 3. 팀 역할 분담

| 파트 | 담당 | 업무 |
| --- | --- | --- |
| 오케스트레이션/통합(조장) | 김승욱 | 의도분류, 기준 예문 세트 관리, 등록·관리자 승인 로직, 로컬 LLM 연동, Supabase 연동·적재, 배포, 통합테스트 |
| TTS 파인튜닝/UI | 홍민하 | Qwen3-TTS-12Hz-1.7B + KSS 학습·파인튜닝, Streamlit UI 구현 |
| STT 파인튜닝 | 김승욱 | Whisper Small·wav2vec2 비교 실험, whisper-large-v3-turbo QLoRA 파인튜닝, WER/CER 평가 및 최종 모델 선정 |

---

## 4. 재료 대체 — 2026-08-27 전면 제거됨

이 절은 원래 "바지락 넣어도 돼?"류 재료 대체 요청을 요리명 정확매칭 → 재료내용 검색 → 롤백("취소해줘") 순으로 처리하던 로직을 설명했습니다. 실사용 리포트 기반으로 팀이 명시적으로 걷어냈습니다(`docs/specs/remove_ingredient_substitution.md`) — 관련 코드(`orchestration/substitution.py`)와 의도 분류 카테고리도 함께 삭제됐습니다. 지금은 재료를 바꾸고 싶으면 새로 등록하거나 처음부터 다시 조회해야 합니다.

## 4-1. 신규 등록 + 관리자 승인이 실제로 어떻게 처리되는지 (LLM 생성 없이)

```
사용자: "등록" (또는 로컬 LLM이 자유발화에서 등록 의도를 감지)
   │
   ① 요리명을 물어봄 (register_dish_name)
   ② 재료를 물어봄, 여러 턴 누적 가능 (register_ingredients)
   ③ 조리 순서를 물어봄, 여러 턴 누적 가능 (register_steps)
   ④ "네, 저장할게요" → Supabase에 저장, source='user_custom', approved='N'

이후 다른 사용자/등록한 사람 본인도 이 레시피를 조회 불가 (승인 대기 중이라고 정직하게 안내)

관리자: /admin (토큰 + 랜덤 단어 3개 음성 화자검증 통과)
   │
   └─ 승인 대기 목록에서 재료·순서 확인 → "등록"(approved='Y') 또는 "삭제"

승인되면: 이제 누구나 정상 조회 가능. 표준 데이터(api_standard)와 동일하게 조회수 기준으로 경쟁.
```

조리가 이미 진행 중일 때는 새 요리로 전환되지 않습니다 — 다른 요리를 조회하거나 새로 등록하려면 항상 처음 화면으로 돌아가야 합니다(오인식으로 진행 중이던 레시피가 갑자기 다른 요리로 바뀌는 것을 막기 위함).

## 5. 조리순서 문의 처리 (LLM 실시간 생성 없이)

```
사용자: "OO 어떻게 만들어?"
   │
   ├─ 60,282건 표준 데이터 안에 있고 승인됨 → 재료+조리순서 다 안내 (대부분 이 경우)
   │
   ├─ 표준 데이터 밖 → "등록되지 않은 레시피예요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요."
   │   → 로그인 없이 누구나 바로 신규 등록 흐름으로 진입 가능(위 4-1)
   │
   └─ 표준 데이터엔 있지만 아직 관리자 승인 전 → "등록 심사 중인 레시피예요. 승인되면 바로 조회할 수 있어요."
```

---

## 6. 개발 환경 세팅

### 6.1 환경 하나로 통합

오케스트레이션·STT 파인튜닝·TTS 파인튜닝·서비스 전부 하나의 환경(env-main)에서 돌립니다. STT(Whisper)·TTS(Qwen3-TTS)·로컬 LLM(EXAONE) 모두 HuggingFace `transformers` 계열이라 별도 학습 환경 분리가 필요 없습니다.

```bash
python3.12 -m venv env-main
source env-main/bin/activate
pip install -r requirements-main.txt
```

상시 마이크(`streamlit-webrtc`) 기능은 그 ICE 구현 의존성(`aioice`)이 아직 Python 3.14를 공식 지원하지 않으므로, 서비스를 실제로 띄울 venv는 Python 3.13으로 만들어야 합니다. `run_local.sh`가 알려진 venv 후보 경로들을 순서대로 찾아 실행하므로, 새 계정에서는 이 스크립트의 후보 목록에 자신의 venv 경로를 추가하면 됩니다.

```bash
./run_local.sh                     # 기본값: src/app.py(실제 서비스) 실행
./run_local.sh tests/test_ui.py    # STT→LLM→DB→TTS 수동 확인용 테스트 화면
```

### 6.2 기술 스택 버전 (고정)

| 구분 | 패키지 | 버전 |
| --- | --- | --- |
| 언어 | Python | 3.12 (env-main), 서비스 실행 venv는 3.13 |
| 실행/배포 | streamlit | 1.61.1 |
| 임베딩(의도분류) | sentence-transformers | 5.6.1 (모델: jhgan/ko-sroberta-multitask) |
| STT 학습·로컬 LLM 공유 스택 | transformers / peft / bitsandbytes / accelerate | 4.57.3 / 0.20.0 / 0.50.0 / 1.12.0 |
| STT 추론(배포) | faster-whisper | 1.2.1 (CTranslate2 int8, GPU) |
| TTS 추론(배포) | qwen-tts | 0.1.1 |
| STT·TTS 평가 | jiwer | 4.0.0 |
| DB | supabase | 2.31.0 (SQL RPC 미사용, Python 필터만) |
| 상시 마이크 | streamlit-webrtc / silero-vad / aiortc | 0.77.0 / 6.2.1 / 1.15.0 |
| 관리자 화자검증 | speechbrain / torchaudio | `requirements-main.txt`에만 포함(배포 최소 의존성엔 미포함), CPU 전용 |

`groq`, `piper-tts` 패키지는 requirements에서 완전히 제외합니다. `streamlit-cookies-manager`는 2026-08-27 계정/쿠키 개인화 제거와 함께 완전히 뺐습니다. Qwen3-TTS 학습 시 24kHz 리샘플링은 필수입니다.

### 6.3 Supabase

`db/schema.sql`을 Supabase 대시보드 SQL Editor에 직접 붙여넣어 실행합니다(별도 마이그레이션 도구 없음). `.env`에 `SUPABASE_URL`/`SUPABASE_KEY`를 채우면 `src/orchestration/db.py`의 `get_client()`가 자동으로 실제 DB를 씁니다 — 자격증명이 없으면 코드 수정 없이 인메모리 mock 클라이언트로 동작해 로컬 개발을 막지 않습니다.

---

## 7. 음성 학습 데이터

TTS·STT 파인튜닝 모두 **KSS(공개 한국어 음성 데이터셋, CC BY-NC-SA 4.0)** 를 사용합니다. TTS는 KSS 원문 음성으로 직접 학습하고, STT는 KSS 원문 음성과 파인튜닝된 Qwen3-TTS가 생성한 합성 음성을 함께 학습 데이터로 씁니다. 본 프로젝트는 수업 과제(비상업)라 KSS 라이선스 조건을 충족합니다. 팀원·지인의 실제 목소리를 녹음해 쓰지 않으므로 별도 동의서는 필요 없습니다.

MOS(청취 평가)나 TTS→STT 재인식 검증처럼 "완성된 음성을 듣고 확인"하는 작업에는 팀원이 직접 참여합니다 — 학습용 녹음과는 다른, 부담이 적은 확인 절차입니다.

---

## 8. 배포

팀 GPU 데스크탑(RTX 5070, 12GB VRAM) 한 대에서 Streamlit 서비스와 STT·TTS·임베딩·로컬 LLM 모델을 모두 상시 구동합니다. GPU는 학습(파인튜닝)뿐 아니라 배포된 서비스의 추론에도 그대로 쓰입니다 — Qwen3-TTS(1.7B)를 목표 응답시간(5초 이내) 안에 CPU만으로 구동하기 어려워, 이미 확보된 GPU 자원을 상시 노출하는 방식을 택했습니다.

외부 접속은 Cloudflare Tunnel로 공개 도메인(`chefear.store`)을 통해 이 GPU 데스크탑에 연결됩니다. 랜딩페이지(`chefear-landingpage.vercel.app`)를 거쳐 접속 링크로 안내하며, `.env`의 `ACCESS_GATE_TOKEN`을 설정하면 그 토큰이 붙은 URL로만 접근을 허용하는 약한 접근 제어를 둘 수 있습니다(비워두면 게이트가 꺼집니다). WebRTC 마이크 연결은 Cloudflare Realtime TURN을 우선 쓰고, 없으면 자체 TURN 또는 구글 공개 STUN으로 대체됩니다.

STT(faster-whisper)·임베딩(sentence-transformers)·로컬 LLM(EXAONE)·TTS(Qwen3-TTS) 넷 다 같은 GPU를 공유하므로, 단일 락으로 넷의 동시 추론을 직렬화해 자원 경합을 막습니다(한때 모델별로 락을 4개로 쪼갰다가 마이크 프레임 드레인이 밀려 "Queue overflow"가 재현돼 바로 되돌렸습니다). 관리자 화자검증(ECAPA-TDNN)만 CPU에서 별도로 돕니다.

관리자 페이지(`/admin`)는 일반 사용자 화면과 완전히 분리된 별도 Streamlit 페이지입니다 — 토큰(`ADMIN_ACCESS_TOKEN`) + 랜덤 한글 단어 3개를 읽는 음성 화자검증(2차) 통과해야만 승인 대기 레시피를 보고 승인/삭제할 수 있습니다.

---

## 9. 발표 시 챙길 것

1. **STT/TTS 둘 다 Before/After 비교**(WER·CER, 청취 비교)
2. **"왜 로컬 LLM은 외부 API 배제 원칙에 안 걸리는지"를 먼저 설명** — 팀 GPU에서 직접 도는 완전 로컬 추론이라는 점
3. **조리순서 데이터 구성을 있는 그대로 설명** — 메타데이터는 실데이터, 조리순서 본문은 배포 전 LLM으로 사전 작성했다는 점(원칙 3, 숨기지 않음)
4. **경쟁앱(레시피오·레시핏·만개의레시피) 비교 결과** — 우리 차별점(자유발화 이해·검증된 표준 데이터·관리자 승인 워크플로우로 등록 콘텐츠 품질 관리)이 근거와 어떻게 맞아떨어지는지
5. **KSS 라이선스 확인했다는 것** 한 줄 명시(동의서는 불필요 — 팀원 녹음 안 함)
6. **계정/재료대체를 왜 뺐는지** — 실사용 리포트 기반 의사결정이었다는 것(구현 못 해서가 아니라 팀이 판단해서 뺐다는 점을 분명히)

---

## 10. 질문 있으면

`docs/ChefEar_PRD_SDD_v0.8.md`와 `docs/ChefEar_설계서.md`에 지금까지 정리된 기술 결정과 근거가 다 있습니다. 여기 없는 애매한 상황이 생기면, 임의로 판단하지 말고 팀 채팅방에 먼저 물어봐 주세요.
