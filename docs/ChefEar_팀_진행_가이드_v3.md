# 셰프이어(ChefEar) — 팀 진행 가이드 (v3, 최종본)

작성자: 김승욱(팀장) · 기준일: 2026-09-10 — 마무리 작업까지 반영. v2(08-28)는 이 문서로 대체됨.

저장소를 처음 보는 사람이 구조와 원칙, 환경을 파악하기 위한 문서다.

## 0. 한 줄 정의

요리 초보가 손을 못 쓰는 상황에서 음성으로 레시피를 한 단계씩 안내받는 에이전트. 로그인 사용자는 새 레시피를 등록해 본인 전용으로 쓸 수 있다.

## 1. 핵심 원칙

**원칙 1. 딥러닝 과제는 STT/TTS 둘 다.** `openai/whisper-large-v3-turbo`(QLoRA)와 `Qwen3-TTS-12Hz-1.7B`(LoRA)를 파인튜닝했고 전/후 수치를 README에 둔다.

**원칙 2. 서비스 응답 경로에 외부 LLM API를 넣지 않는다.** 의도분류는 임베딩 유사도, 요리명 추정은 팀 GPU에 직접 올린 로컬 LLM(EXAONE)이 한다. 개발 도구로 LLM을 쓰는 것은 자유다.

**원칙 3. 데이터 구성은 있는 그대로 설명한다.** 요리명·재료·조회수는 만개의레시피 실데이터, 조리순서 문장은 재료 기반 규칙 생성이다. 초기 60,282건 전량 적재를 09-01에 500건 큐레이션으로 교체했다는 사실도 숨기지 않는다.

**원칙 4. 지어내지 않는다.** 데이터에 없으면 "없다"고 안내하고 등록으로 유도한다. 로컬 LLM이 요리명 추정에 실패해도 안전한 기본값으로 처리한다.

## 2. 디렉토리 구조

```
proj1-a/
├── README.md                     프로젝트 개요·평가 결과·실행 방법
├── AGENTS.md / CLAUDE.md         AI 에이전트 작업 지침
├── requirements*.txt             서빙 최소 / 모델 로딩 스택 / STT 학습 고정
├── Dockerfile, docker/           RunPod 배포 이미지·엔트리포인트
├── run_local.sh                  로컬 GPU 실행 스크립트
├── .env.example                  환경변수 목록
├── .github/workflows/            GHCR 이미지 빌드, secret-scan
│
├── docs/
│   ├── ChefEar_PRD_SDD_v0.9.md   요구사항·설계 (1차 문서)
│   ├── ChefEar_설계서.md          배포 관점 요약
│   ├── ChefEar_팀_진행_가이드_v3.md  이 문서
│   ├── ChefEar_경쟁사분석.md
│   ├── decisions.md              의사결정 기록
│   ├── runpod_deploy.md          배포 절차
│   ├── stt.md                    STT 학습 환경 스냅샷
│   ├── specs/                    기능 스펙 (README.md에 상태표)
│   ├── presentation/             발표 자료 PDF(파이프라인 구조도·모델 비교·고객여정)
│   └── 한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv   서비스 데이터 원본
│
├── src/
│   ├── app.py                    서비스 엔트리포인트
│   ├── orchestration/            의도분류·검색·등록·계정·워커 풀·DB·용어 사전·적재 스크립트
│   ├── llm/infer.py              로컬 LLM(EXAONE)
│   ├── stt/                      infer.py(배포 추론) · export_ct2.py(CT2 변환) · evaluate_fixed100.py(재평가)
│   ├── tts/                      infer.py(배포 추론) · pronunciation.py(발음 보정) · assets/(참조 음성)
│   └── ui/                       session · voice_io · dispatch · recipe_view · screens/
├── ui/                           theme.py(공용 스타일) · mic_vad.py(VAD) · images/
├── db/                           schema.sql · 500건 교체 마이그레이션 SQL
├── data/                         기준예문 · Fixed100 검증셋 · MOS 원자료 (대용량 음성·모델은 git 제외)
├── results/                      STT·TTS 평가 CSV·대시보드
├── tests/                        pytest 125개 + GPU 벤치마크 스크립트
└── landing/                      소개 페이지
```

모델 가중치는 git에 두지 않고 HF Hub(`leeony/chefear-stt-large-v3-turbo`, `kimseunguk/chefear-stt-ct2-int8`, `kimseunguk/qwen3-tts-kss-finetuned`)에서 내려받는다. 세 저장소 모두 private라 `HF_TOKEN`이 필요하다.

## 3. 팀 역할

| 파트 | 담당 | 업무 |
| --- | --- | --- |
| 오케스트레이션·통합·배포(조장) | 김승욱 | 의도분류, 검색·등록 로직, 상시 마이크, GPU 워커 풀, Whisper 파인튜닝·평가, Docker·RunPod, 데이터 큐레이션, 문서 |
| TTS·UI·계정 | 홍민하 | Qwen3-TTS 파인튜닝, Streamlit 화면·테마, 로그인·마이레시피, 보안 수정 |
| STT 평가·데이터 | 하주성 | Fixed100 검증셋, 학습 환경 고정, 단위 정규화·문맥 보정(08-24까지 참여) |

08-31 발표로 과제 마감은 끝났지만, 로컬 GPU 한계·데이터 품질·계정 구조가 스스로 납득되지 않아 김승욱·홍민하가 09-01 ~ 09-08 강의 후 저녁마다 집에서 이어서 작업했다. GPU 서버 이관, 프로세스 워커 풀, 계정·마이레시피 재도입, 500건 데이터 교체, TTS 잘림 수정이 이 기간의 산출물이고, 지금 배포된 버전이 그 결과다(`README.md` 6장 ⑥).

## 4. 조회·등록이 처리되는 방식

```
사용자: "OO 어떻게 만들어?"
   ├─ 500건 표준 데이터에 있음        → 재료 + 조리순서 안내 (용어는 설명과 함께)
   ├─ 본인이 등록한 레시피            → 동일하게 안내 (다른 사용자에겐 안 보임)
   └─ 없음                            → "등록되지 않은 레시피예요. '레시피 등록'이라고 말씀해 주세요."

사용자: "등록"  (비로그인이면 로그인 화면으로)
   ① 요리명 → ② 재료(여러 턴) → ③ 순서(여러 턴) → ④ 저장 (owner_id 필수, 즉시 본인 조회 가능)
```

조리가 진행 중일 때는 조회·등록 의도를 무시한다. 다른 요리는 처음 화면으로 돌아가서 조회한다.

## 5. 개발 환경

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt -r requirements-main.txt
cp .env.example .env     # 값 채우기
./run_local.sh           # src/app.py 실행 (CUDA 라이브러리 경로 자동 설정)
pytest tests/            # GPU·DB 없이 실행 가능
```

Python은 3.13이어야 한다(aioice가 3.14 미지원). Docker로 띄우려면 `docker build -t chefear . && docker run --gpus all --env-file .env -p 8501:8501 chefear`.

| 구분 | 패키지 | 버전 |
| --- | --- | --- |
| UI | streamlit | 1.61.1 |
| 의도분류 | sentence-transformers | 5.6.1 |
| STT 추론 | faster-whisper | 1.2.1 |
| 학습·로컬 LLM | transformers / peft / bitsandbytes | 4.57.3 / 0.20.0 / 0.50.0 |
| TTS 추론 | qwen-tts | 0.1.1 |
| 평가 | jiwer | 4.0.0 |
| DB | supabase | 2.31.0 |
| 상시 마이크 | streamlit-webrtc / silero-vad / aiortc | 0.77.0 / 6.2.1 / 1.15.0 |
| 화자검증 | speechbrain / torchaudio | requirements-main.txt |

`groq`, `piper-tts`는 쓰지 않는다. Supabase 스키마는 `db/schema.sql`을 SQL Editor에 직접 실행한다(자격증명이 없으면 mock 클라이언트로 동작).

## 6. 음성 학습 데이터

TTS·STT 모두 KSS(CC BY-NC-SA 4.0, 비상업)를 쓴다. STT는 조리문 텍스트를 TTS로 읽은 합성 음성으로 학습했고, 평가는 Fixed100(저장소 포함)과 신규500으로 했다. 팀원 목소리는 녹음하지 않아 동의서가 필요 없다. MOS는 지인 13명 블라인드 청취(집계: `results/tts/mos/MOS_청취평가.html`, 참여자별 원자료는 저장소 제외).

## 7. 배포

RunPod A40 Pod에서 Docker 이미지로 Streamlit과 GPU 워커 풀을 띄우고, Cloudflare Tunnel로 `chefear.store`에 연결한다. 랜딩페이지(Vercel)를 거쳐 접속 게이트 토큰이 붙은 URL로 들어온다. 평소엔 Pod를 Stop해 과금을 멈추고 시연 전 Start한다. 상세 절차는 `docs/runpod_deploy.md`.

## 8. 발표·면접에서 챙길 것

1. STT/TTS 전/후 수치(README 5장)와 재현 방법(`src/stt/evaluate_fixed100.py`).
2. 로컬 LLM이 외부 API 배제 원칙에 안 걸리는 이유.
3. 데이터 구성(실데이터 + 규칙 생성 조리순서, 60,282 → 500 결정)을 있는 그대로.
4. 문제 해결 이야기: TTS epoch-24 회귀, GIL과 Queue overflow → 프로세스 풀, 화면 잔상 → `st.empty()` 슬롯, TTS 끝음절 잘림 → 캐시 파일 레이스.
5. 기능을 뺀 이유(재료 대체, 승인 모델)와 다시 넣은 이유(계정)가 실사용 판단이었다는 점.
