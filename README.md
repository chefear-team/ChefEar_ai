# 👨‍🍳 ChefEar (셰프이어)

> 손에 물기와 재료가 묻어 화면을 볼 수 없는 순간에도, 음성만으로 레시피를 한 단계씩 안내받는 음성 레시피 에이전트.
> STT(Whisper)와 TTS(Qwen3-TTS)를 요리 도메인으로 직접 파인튜닝했고, 안 쓸 때는 서버가 0대로 줄어드는 서버리스 웹앱으로 배포했습니다.

| | |
|---|---|
| 과정 | AI Human 7기 · 1차 팀 프로젝트(딥러닝 기반 TTS·STT 서비스) · A조 |
| 기간 | 2026-08-14 ~ 08-30 (발표 08-31) · 09-01 ~ 09-08 마무리 작업 · 2026-10-19 ~ 10-20 서버리스 리뉴얼 |
| 서비스 | [chefear.vercel.app](https://chefear.vercel.app) — 구글 또는 이메일로 로그인해야 쓸 수 있습니다. 안 쓰다가 처음 접속하면 서버가 깨어나는 데 수십 초 걸릴 수 있습니다. |
| 저장소 상태 | 2026-10-20 리뉴얼 반영. 구조·결정은 [`docs/specs/renewal_serverless.md`](docs/specs/renewal_serverless.md), 미측정 항목은 11장 |

---

## 1. 한눈에 보기

```
사용자: "된장찌개 만드는 법 알려줘"
ChefEar: "된장찌개, 표준 레시피예요. 이걸로 시작할까요?"
사용자: "응"
ChefEar: "일단계, 두부와 감자를 깍둑썰기 해주세요."   ← 조리 용어는 짧은 설명을 함께 읽어줌
사용자: "다음" / "다시" / "이전"                        ← 정해진 명령어가 아니라 자유발화
```

- **음성만으로 진행** — 브라우저가 말소리를 감지(VAD)해 한 문장씩 잘라 STT로 보내고, 응답은 TTS(또는 미리 만든 음성)로 바로 재생됩니다. 버튼을 누를 필요가 없습니다.
- **자유발화 이해** — "다음꺼", "한 번 더", "아까 거"처럼 표현이 달라도 임베딩 유사도로 의도를 판단합니다.
- **도메인 파인튜닝** — 요리명·재료명·계량단위·조리동작을 일반 모델보다 정확히 듣고(STT), 자연스럽게 읽습니다(TTS).
- **정직한 데이터** — 조리순서는 저장된 500개 큐레이션 레시피에서 조회만 합니다. 없으면 "없다"고 답하고, 런타임에 문장을 생성하지 않습니다.
- **외부 LLM API 없음** — 서비스 실행 중 OpenAI·Gemini 등 외부 API를 호출하지 않습니다. 리뉴얼에서 요리명 추정용 로컬 LLM(EXAONE)도 서비스 경로에서 뺐습니다(영향은 11장).
- **로그인 전용, 입력 방어** — GPU 비용을 남이 만들지 못하게 서비스 전체가 로그인한 사용자 전용이고, 모든 사용자 입력은 서버에서 정리·제한·차단을 거칩니다.

### 화면 (2026-10-20)

| 로그인 | 이메일 로그인·가입 | 시작 | 레시피 확인 |
|---|---|---|---|
| ![로그인](docs/images/renewal/01_login.jpg) | ![이메일 시트](docs/images/renewal/02_email_sheet.jpg) | ![시작](docs/images/renewal/03_start.jpg) | ![레시피 확인](docs/images/renewal/04_recipe_confirm.jpg) |

| 조리 1단계 | 조리 마지막 단계 | 요리 완성 | 등록 · 재료 |
|---|---|---|---|
| ![조리 1단계](docs/images/renewal/05_cooking_step1.jpg) | ![조리 마지막 단계](docs/images/renewal/06_cooking_last_step.jpg) | ![요리 완성](docs/images/renewal/07_cooking_complete.jpg) | ![등록 재료](docs/images/renewal/08_register_ingredients.jpg) |

| 등록 · 조리 순서 | 등록 완료 · 음성 준비 안내 | 마이레시피 | 레시피 수정 |
|---|---|---|---|
| ![등록 순서](docs/images/renewal/09_register_steps.jpg) | ![등록 완료](docs/images/renewal/10_register_complete.jpg) | ![마이레시피](docs/images/renewal/11_my_recipes.jpg) | ![레시피 수정](docs/images/renewal/12_edit_recipe.jpg) |

모두 서버 없이 눌러 보는 **데모 모드**(`VITE_MOCK=1`, 가짜 API·가짜 마이크)에서 2026-10-20에 찍었습니다. 그래서 화면 위에 "데모 모드" 표시가 있고, 대화 카드 내용은 가짜 서버가 만든 것이라 실제 서버와 조금 다를 수 있습니다. 말 처리 중 오버레이는 실제 말소리가 있어야 떠서 캡처하지 않았습니다. 리뉴얼 전(Streamlit) 화면은 `docs/images/flow/`에 남아 있습니다.

## 2. 팀과 역할

| 이름 | 역할 | 실제 기여(커밋 이력 기준) |
|---|---|---|
| **김승욱** (조장) | 오케스트레이션·통합 / STT 파인튜닝 / 배포 | 의도분류·레시피 검색·등록 로직, 상시 마이크 파이프라인, GPU 워커 풀, Whisper QLoRA 파인튜닝과 평가, Docker·RunPod·Cloudflare 배포, 500건 데이터 큐레이션, 문서 전반 (266 커밋) |
| **홍민하** | TTS 파인튜닝 / UI / 계정 | Qwen3-TTS LoRA 파인튜닝과 체크포인트 검증, Streamlit 화면·테마, 로그인·구글 OAuth·마이레시피, 소유자 격리 보안 수정 (58 커밋) |
| **하주성** | STT 평가·데이터 | Fixed100 검증셋(문장 100개 + 음성) 구축, STT 학습 환경 고정, 단위 정규화·문맥 기반 숫자 보정 후처리, 랜딩페이지 (19 커밋, 08-24까지 참여) |

과제 마감은 08-31 발표였고, 09-01 ~ 09-08의 작업은 김승욱·홍민하 두 사람이 강의 종료 후 이어서 진행한 것입니다. 발표 시점의 배포 상태(로컬 12GB GPU, 락 기반 동시성, 6만 건 미검수 데이터, 계정 없는 등록)를 그대로 두지 않기 위한 마무리였고, 당시 배포된 버전은 이 기간의 결과입니다(작업 내역은 6장 ⑥). 그 뒤 2026-10-19~20에 서버리스 웹앱으로 다시 구성했습니다(6장 ⑦).

## 3. 문제 정의

요리 경험이 거의 없는 초보자는 칼질·반죽처럼 손을 쓰기 어려운 순간마다 화면을 확인하러 조리를 멈춥니다. 손을 씻고 화면을 보는 사이 반죽 농도나 양념 타이밍처럼 되돌릴 수 없는 손실이 생깁니다. ChefEar의 목표는 시간 절약이 아니라 **첫 시도부터 완성도를 잃지 않게 하는 것**입니다.

| 경쟁 서비스 | 한계 | ChefEar |
|---|---|---|
| 레시피오 | 텍스트 채팅형, 화면을 봐야 함 | 음성 출력 중심 |
| 레시핏 | 음성 핸즈프리지만 정해진 명령어, 유튜브 변환이라 품질 미검증 | 자유발화 + 큐레이션 데이터 |
| 만개의레시피 | 음성은 레시피 작성용, 안내용 아님 | 조리 진행 전체가 음성 |

## 4. 아키텍처

```mermaid
flowchart TD
    U["브라우저 (Vercel, React)<br/>로그인 · 마이크 VAD(silero) · 소리 재생"] -->|"토큰 + 발화 WAV 또는 글자"| API["API (Modal CPU, FastAPI)<br/>로그인 확인 · 입력 검증 · 대화 상태 기계"]
    API --> STT["STT (Modal GPU L4)<br/>faster-whisper int8, whisper-large-v3-turbo QLoRA"]
    STT --> API
    API --> M["요리명 매칭 + 임베딩 의도분류 (CPU)<br/>ko-sroberta, threshold 0.5 / margin 0.05"]
    M --> DB[("Supabase Postgres<br/>recipes · recipe_steps · sessions")]
    API --> Q{"미리 만든 음성이 있나?"}
    Q -- 예 --> S[("Supabase Storage<br/>공용 mp3 · 본인 전용 mp3")]
    Q -- 아니오 --> TTS["TTS (Modal GPU L4)<br/>Qwen3-TTS-1.7B KSS LoRA, voice-clone"]
    API -->|"레시피 저장 후"| RA["등록 음성 생성 (Modal GPU, 동시 1대)"] --> S
```

| 층 | 위치 | 안 쓸 때 |
|---|---|---|
| 웹 | `web/` (Vite + React + TypeScript) → Vercel | 정적 파일, 항상 켜짐(무료) |
| API | `server/chefear_api` (FastAPI) → Modal CPU | 마지막 요청 5분 뒤 0대 |
| STT·TTS·등록 음성 | `inference/modal_app.py` → Modal GPU(L4) | 마지막 요청 5분 뒤 0대 |
| DB·파일·로그인 | Supabase (Postgres·Storage·Auth) | 켜짐. 무료는 1주 미사용 시 정지되므로 `keepalive.yml`로 3일마다 접속 |

**흐름의 원칙.** 파인튜닝한 모델, 500개 데이터, 대화 흐름(상태 기계)은 기존 그대로이고 서빙·연결 방식만 바꿨습니다. API는 기억을 갖지 않고 대화 상태를 Supabase `sessions`에 저장하므로 꺼졌다 켜져도 이어집니다. 웹은 STT·TTS를 직접 부르지 않고 API가 Modal SDK로 부릅니다(STT·TTS에는 공개 주소가 없습니다).

**소리.** 응답 문장의 지문(`sha256(VOICE_VERSION + 문장)`)으로 미리 만든 mp3를 먼저 찾고(`scripts/upload_tts_audio.py`), 없을 때만 실시간 TTS를 씁니다. 사용자가 등록한 레시피의 음성은 저장 직후 별도 GPU 함수가 만들어 본인만 들을 수 있는 비공개 저장소에 둡니다.

**데이터 흐름.** 조리 단계 텍스트에는 `[TERM:깍둑썰기]` 같은 태그가 붙어 있고, TTS로 읽을 때는 짧은 설명("사방 1~2cm 정육면체로 써는 방법")을 붙여 읽고 화면에는 용어만 표시합니다.

**마이크.** 로그인 후 "시작하기"를 누르면 연결합니다. 재생·처리 중에는 듣기만 멈추고, "마이크 끄기"·로그아웃·레시피 등록 화면에서는 연결 자체를 닫아 브라우저 표시등도 꺼집니다.

## 5. 딥러닝 파인튜닝과 평가

### 5.1 STT — `openai/whisper-large-v3-turbo` QLoRA

| 항목 | 내용 |
|---|---|
| 방식 | QLoRA(4-bit NF4), r=16 / alpha=64 / dropout=0.05, target=q_proj·k_proj·v_proj·out_proj |
| 학습 데이터 | 요리 조리문 텍스트(재료·계량·조리동작 위주)를 TTS로 읽어 만든 합성 음성. train300 → train1000 → 숫자·단위 보강 250 → 최종 MIX750(리플레이 500 + 숫자보강 250, LR 1e-5) |
| 검증셋 | Fixed100(저장소에 커밋됨: `data/evaluation_scripts/stt/`) · 신규500 |
| 배포 | LoRA 병합 → CTranslate2 int8 변환(`src/stt/export_ct2.py`) → faster-whisper GPU 추론 |

| 체크포인트 | Fixed100 WER | Fixed100 CER | 신규500 WER | 신규500 CER | 숫자·단위 정확도 |
|---|---|---|---|---|---|
| 기준(2 epoch) | 33.20% | 5.81% | — | — | — |
| train300 | 10.68% | 2.21% | 13.97% | 3.05% | 70.75% |
| train1000 | 7.26% | 1.49% | 10.98% | 2.33% | 86.79% |
| reinforce250 | 8.20% | 1.54% | 11.07% | 2.32% | 90.57% |
| **MIX750 (최종)** | **7.68%** | **1.44%** | **10.72%** | **2.26%** | **90.57%** |

핵심정보 인식률(MIX750, 신규500): 재료명 98.31% · 조리동작 99.54% · 숫자·단위 90.57% · 종합 96.23%.

비교 실험: Whisper Small(경량 비교군), wav2vec2(구조 비교군, 숫자·단위·일부 한국어 음절 처리 한계로 중단). V1 어댑터 위에 신규 300문장으로 V2 추가 학습도 했으나 개선이 없어 V1(MIX750)을 최종 채택했습니다.

**재현 가능한 수치.** 배포 중인 int8 모델을 저장소의 Fixed100으로 다시 돌린 결과입니다(`python src/stt/evaluate_fixed100.py`, 결과 `results/stt/`). 위 표는 학습 환경의 4-bit 어댑터 기준이고 아래는 int8 변환본이라 수치가 다릅니다.

| 배포 모델(CTranslate2 int8) | Fixed100 WER | Fixed100 CER | 완전 일치 | 문장당 추론 |
|---|---|---|---|---|
| MIX750 int8 (2026-09-10 재측정) | 11.83% | 1.81% | 55/100 | 0.34초 (RTX 5070) |

### 5.2 TTS — `Qwen3-TTS-12Hz-1.7B-Base` LoRA

| 항목 | 내용 |
|---|---|
| 방식 | LoRA 파인튜닝 후 merge_and_unload, KSS 데이터셋(12,854문장, 24kHz 리샘플링), Colab A100 |
| 체크포인트 | epoch-8 → epoch-24(과적합, 반복 발화) → **epoch-13 채택** |
| 추론 | qwen-tts 0.1.1, bfloat16, KSS 화자 참조 음성으로 voice-clone, `max_new_tokens`를 문장 길이 비례로 동적 계산 |

TTS → STT 재인식 CER(5문장): epoch-8 평균 1.37 → epoch-24 평균 14.26 → **epoch-13 전부 0.00**.

파인튜닝 방식 비교(N=30~100, 별도 실험 공간):

| 모델 | WER | CER | MOS |
|---|---|---|---|
| Qwen3-TTS Base | 0.27 | 0.08 | 4.33 |
| Full FT | 0.48 | 0.22 | 2.10 (회귀) |
| **LoRA FT (채택)** | 0.26 | 0.10 | **4.67** |
| QLoRA FT | 0.27 | 0.12 | 4.17 |

블라인드 MOS(13명, 모델당 10문항, 총 909건): Qwen3 LoRA 4.67 > Base 4.33 > QLoRA 4.17 > Full FT 2.10 > vits-kss 1.45 > Chatterbox 1.05. 지인 편의표본이라 통계적 대표성은 없습니다. 집계 대시보드는 `results/tts/mos/`.

응답 속도(RTX 5070, 4문장 평균): eager 6.34초 → SDPA 5.48초 → `torch.compile(dynamic=True)` 5.21초. 목표 5초에 근접했으나 긴 문장은 여전히 초과합니다. CPU는 26초로 배포 불가 판정을 내려 GPU 상시 배포로 방향을 잡았습니다.

### 5.3 학습 코드의 위치

STT·TTS 학습은 Colab과 개인 작업 공간의 노트북·스크립트로 진행했고, 이 저장소에는 학습 설정(`docs/stt.md`, `src/stt/README.md`, `src/tts/README.md`)과 평가 자산(Fixed100 검증셋, 평가 스크립트, 결과 CSV·대시보드)만 포함되어 있습니다. 학습 스크립트 파일은 저장소에 없습니다.

### 5.4 리뉴얼 서버의 STT 속도 (Modal)

`modal run inference/bench_stt.py`로 Fixed100 앞 10문장을 같은 모델·같은 코드로 돌린 결과입니다(`results/stt/bench_modal.json`).

| 환경 | 발화당 평균 | 모델 로드 | WER |
|---|---|---|---|
| CPU 2 vCPU | 11.27초 | 9.2초 | 11.1% |
| CPU 4 vCPU | 8.12초 | 7.9초 | 11.1% |
| **GPU L4** | **0.20초** | 7.1초 | 15.6% |

속도 차이는 분명해서 STT는 GPU로 두었습니다. WER은 표본이 10문장뿐이라 서로 비교하지 않습니다(100문장 전체 재측정 필요).

## 6. 기술적 의사결정

**① 외부 LLM API 금지를 어떻게 풀었나.** 과제 요건상 서비스 응답 경로에 외부 LLM API를 넣을 수 없었습니다. 의도분류는 `jhgan/ko-sroberta-multitask` 임베딩과 110개 기준 예문의 코사인 유사도로 처리하고, 1위 점수가 0.5 미만이거나 2위와 차이가 0.05 미만이면 임의로 고르지 않고 되묻습니다. 자유발화 속 요리명 추정만 로컬 LLM(EXAONE-3.5-2.4B, `transformers`로 GPU에 직접 로드)에 맡겼습니다.

**② TTS epoch-24 회귀.** 더 오래 학습한 epoch-24 체크포인트에서 재인식 CER이 1.37에서 14.26으로 튀고 같은 말을 반복하는 발화가 늘었습니다. 화자 임베딩 테이블이 바뀐 것과 과적합을 원인으로 잡고 epoch-13으로 되돌렸으며, 추론 방식도 화자명 지정에서 참조 음성 voice-clone으로 바꿨습니다. 결과는 5문장 CER 0.

**③ Queue overflow와 GIL.** 사용자가 늘면 STT·TTS·LLM 추론이 겹쳐 마이크 프레임 큐가 넘쳤습니다. 모델별로 락을 4개로 나눠 병렬화했더니 오히려 GIL 경합으로 마이크 드레인 스레드가 굶어 재발했습니다. 원인이 락이 아니라 GIL이라는 걸 확인하고 추론을 별도 프로세스 풀로 옮겨 해결했습니다(리뉴얼에서 서비스 구조 자체를 바꿔 이 워커 풀은 제거했습니다, ⑦).

**④ 60,282건에서 500건으로.** 처음에는 만개의레시피 고유 요리명 60,282건 전량을 적재했습니다. 원본에는 조리순서 텍스트가 없어 ChatGPT로 오프라인 생성해 채웠는데, 6만 건의 품질을 사람이 검수할 수 없다는 판단이 섰습니다. 9월 1일 한국 가정식 500개로 범위를 줄이고, 재료 목록 기반 규칙으로 조리순서 2,950단계를 생성한 뒤 조리 용어 926개에 설명 태그를 붙여 전면 교체했습니다. 적은 데이터를 확실하게 만드는 쪽을 택한 결정입니다.

**⑤ 계정 기능을 뺐다가 다시 넣은 이유.** 08-27에 화면 전환 잔상 버그와 "누가 등록했는지 쓰지 않는다"는 결정으로 로그인을 제거하고 관리자 승인 모델로 갔습니다. 잔상 버그를 `st.empty()` 슬롯 방식으로 근본 해결한 뒤 09-01에 로컬 가입 + 구글 OAuth 로그인과 마이레시피를 재도입했고, 09-02부터 등록은 로그인 필수, 등록한 레시피는 본인에게만 보이는 구조로 바꿨습니다. 관리자 승인 페이지는 그 이전 레거시 데이터 처리용으로만 남아 있습니다.

**⑥ 마감 이후의 마무리(09-01 ~ 09-08).** 발표 시점의 로컬 데스크탑(RTX 5070, 12GB)은 워커 하나가 VRAM 10GB를 써서 동시 사용자를 받을 수 없었고, 락 방식은 Queue overflow를 반복했습니다. 두 사람이 8일간 이어서 한 일은 다음과 같습니다.

| 날짜 | 작업 | 담당 |
|---|---|---|
| 08-31 | 멀티스테이지 Docker 이미지(Python 3.13 소스 빌드, CUDA 12.4), GitHub Actions → GHCR, RunPod A40(48GB) 이관, 저장소를 Organization으로 이전 | 김승욱 |
| 09-01 | 스레드 락 → GPU 프로세스 워커 풀, PeerConnection 누적 크래시 근본 수정, 60,282건 → 500건 큐레이션 데이터 교체와 조리 용어 태깅 | 김승욱 |
| 09-01 | 로컬 가입 + 구글 OAuth 로그인, 마이레시피(목록/수정/삭제) 재도입 | 홍민하 |
| 09-02 | 등록 로그인 필수·본인 전용 노출로 전환, 관리자 승인은 레거시 전용으로 | 홍민하 |
| 09-02 ~ 09-04 | TTS 끝음절 잘림 원인 추적(무음 패딩·더미 기호 등 우회 시도 후 캐시 파일 동시 쓰기 레이스로 확정), 조리 단계 번호 한글 낭독, 프리페치 병렬화 | 김승욱 |
| 09-07 ~ 09-08 | flash-attn 사전빌드 휠 적용, 워커 풀 자동 복구, 소유자 격리 보안 결함(IDOR·비로그인 노출) 수정 | 김승욱·홍민하 |

이 기간의 결과가 리뉴얼 이전 최종 버전(`chefear.store`, RunPod)입니다.

**⑦ 서버리스 웹앱으로 다시 구성(2026-10-19 ~ 10-20).** 쓰는 사람이 거의 없는 기간에도 RunPod A40이 상시 과금되고, Streamlit 재실행 + WebRTC 구조는 화면 잔상과 동시 1~2명 한계를 반복했습니다. 파인튜닝한 모델·500개 데이터·대화 흐름은 그대로 두고 서빙만 바꿨습니다.

- **웹 + 상태 없는 API + 안 쓰면 0대인 GPU.** 대화 상태를 DB에 두어 서버를 마음대로 끄고 켤 수 있게 했고, 화면은 요소를 통째로 교체해 잔상이 남을 자리를 없앴습니다. 콜드 스타트는 숨기지 않고 화면에 안내합니다.
- **STT는 GPU.** CPU로 두면 비용이 더 줄 거라 기대했지만 Modal 실측에서 발화당 8~11초라 L4로 갔습니다(5.4). 모델 파일은 이미지에 미리 넣어 켜질 때마다 내려받지 않습니다.
- **등록 음성은 별도 GPU 함수(동시 1대).** 4명이 동시에 등록해도 조리 중인 사용자의 STT·TTS를 막지 않습니다.
- **로그인 전용 + 입력 방어.** 공개 서비스에서 로그인 없이 GPU를 호출하면 남이 비용을 만듭니다. 서버가 비로그인 요청을 전부 401로 거절하고, 모든 사용자 글자는 `guard.py`가 정리·제한·차단합니다. 무료 크레딧이 떨어지면 카드 청구 대신 멈추도록 Modal 지출 한도를 $0으로 걸었습니다.
- **대가.** 요리명 추정 LLM(EXAONE)을 뺐고 정확도 A/B는 아직 재지 않았습니다. 관리자 페이지·로컬 계정·구글 `st.login`은 없어졌고 기존 `users` 10명은 새 로그인과 연결되지 않습니다(데이터는 유지). 첫 접속은 서버가 깨어나는 동안 느립니다.

## 7. 기능 범위

**포함**: 자유발화 조회 · 단계 진행(다음/다시/이전, 1단계에서 이전은 유지) · 조리 중 다른 요리로 전환 금지 · 조리 용어 설명 · 음성 실패 시 글자 입력·수동 버튼 · 구글/이메일 로그인(서비스 전체 로그인 전용) · 레시피 등록(요리명→재료→순서, 글자 입력) · 등록 음성 자동 생성과 진행 안내 · 마이레시피(목록/수정/삭제, 본인 전용).

**제외(팀 결정)**: 재료 대체(08-27 제거) · 사진 등록 · 타이머 · 바지인(TTS 중 끼어들기) · 판매/결제 · 데이터 밖 요리의 조리순서 실시간 생성 · 관리자 페이지와 화자검증(리뉴얼 제거).

## 8. 기술 스택

| 구분 | 선택 | 비고 |
|---|---|---|
| STT | whisper-large-v3-turbo + QLoRA → CTranslate2 int8 / faster-whisper 1.2.1 | Modal L4 |
| TTS | Qwen3-TTS-12Hz-1.7B + LoRA / qwen-tts 0.1.1 | bfloat16, voice-clone, Modal L4 |
| 의도분류 | sentence-transformers 5.6.1, `jhgan/ko-sroberta-multitask` | LLM 아님, API 컨테이너(CPU) |
| 웹 | Vite + React 18 + TypeScript, `@ricky0123/vad-web`(silero VAD), supabase-js | Vercel |
| API | FastAPI, Python 3.12 | Modal CPU, 입력 검증 `guard.py` |
| DB·파일·로그인 | Supabase (Postgres, Storage, Auth) | `db/schema.sql` + `db/migrate_renewal.sql`, RLS 켬 |
| 추론 서버 | Modal | 안 쓰면 0대, 모델은 이미지에 포함 |
| 테스트·CI | pytest 167개(GPU·DB·모델 불필요) + GitHub Actions | `.github/workflows/ci.yml` |

## 9. 실행 방법

### 9.1 서버 없이 화면만 눌러 보기

```bash
cd web
npm install
cp .env.example .env.local     # VITE_MOCK=1 로 두면 브라우저 안의 가짜 API로 동작
npm run dev
```

### 9.2 API 서버를 PC에서 돌리기 (GPU 불필요)

```bash
pip install -r requirements-server.txt
PYTHONPATH=server:src ALLOW_DEV_USER=1 INFERENCE_BACKEND=none \
  uvicorn chefear_api.main:app_factory --factory --port 8000
```

`SUPABASE_URL`/`SUPABASE_KEY`가 없으면 인메모리 mock DB로 동작합니다. `ALLOW_DEV_USER=1`은 `x-dev-user` 헤더를 로그인으로 취급하는 **로컬 테스트 전용** 값이며 운영에서는 절대 켜지 않습니다. 음성 인식·합성은 `INFERENCE_BACKEND=modal` + Modal 배포가 필요합니다.

### 9.3 배포

`renewal/DEPLOY.md`(Supabase → 공용 음성 업로드 → Modal → Vercel 순서, 구글 로그인·지출 한도 설정 포함)와 `renewal/API_CONTRACT.md`(엔드포인트·오류 코드)를 봅니다.

| 환경변수 | 어디에 | 설명 |
|---|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_ANON_KEY` | Modal 비밀값 | `SUPABASE_KEY`는 서버 전용 키(웹 번들에 절대 넣지 않음) |
| `HF_TOKEN`, `HF_STT_CT2_REPO` | Modal 비밀값 | 모델 저장소가 private |
| `INFERENCE_BACKEND=modal`, `ALLOWED_ORIGINS` | Modal 비밀값 | CORS 허용 웹 주소 |
| `VITE_API_BASE`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Vercel | 공개돼도 되는 값만 |

전체 목록은 `.env.example`과 `web/.env.example`.

### 9.4 테스트와 평가

```bash
pytest tests/ --ignore=tests/tts_cpu_inference_test.py --ignore=tests/tts_stt_roundtrip_test.py   # GPU·DB·모델 불필요
cd web && npm run build                                      # 타입 검사 + 빌드
python src/stt/evaluate_fixed100.py                          # 배포 STT를 Fixed100으로 재평가 (GPU, .env 필요)
python tests/tts_stt_roundtrip_test.py                       # TTS→STT 재인식 CER (GPU)
modal run inference/bench_stt.py                             # Modal에서 STT 속도 비교(CPU·GPU)
```

## 10. 저장소 구조

```
web/                        웹(Vite + React). 로그인·마이크 VAD·소리 재생·등록 화면
server/chefear_api/         API(FastAPI): 대화 상태 기계, 로그인 확인, 입력 검증(guard), 음성 주소
inference/                  Modal 앱(STT·TTS·등록 음성), STT 세그먼트 처리, 속도 벤치
src/orchestration/          의도분류·레시피 검색·등록·DB (API가 가져다 씀)
src/stt/, src/tts/          STT 추론·후처리·평가, TTS 추론·발음 보정
src/llm/                    로컬 LLM(EXAONE). 서비스 경로에서는 호출하지 않음
db/                         schema.sql, migrate_renewal.sql(세션·음성 표, 버킷, RLS)
scripts/                    공용 음성 목록 추출·업로드
data/                       기준예문, Fixed100 검증셋, MOS 원자료, 음성 목록(tts_manifest.csv)
results/                    STT·TTS 평가 결과 CSV와 대시보드, Modal 속도 측정
renewal/                    API 계약, 배포 절차
docs/                       PRD/SDD, 설계서, 팀 가이드, 스펙, 의사결정, 발표 자료
tests/                      pytest 스위트(+ tests/renewal) + 수동 GPU 스크립트
.github/workflows/          ci.yml, keepalive.yml(Supabase 정지 방지), secret-scan.yml
```

## 11. 한계와 정직한 기록

- 학습 스크립트는 저장소 밖(Colab·개인 작업 공간)에 있어 가중치 재학습은 이 저장소만으로 재현되지 않습니다. 평가는 재현됩니다(5.1).
- STT 기준선은 파인튜닝 2 epoch 시점이며, 원본 모델 zero-shot 수치는 측정하지 않았습니다.
- 조리순서 텍스트는 실데이터가 아니라 재료 목록 기반 규칙 생성이며, 요리명·재료·조회수만 만개의레시피 실데이터입니다.
- **리뉴얼 후 실제 사람이 마이크로 끝까지 돌려 본 기록이 없습니다.** 글자 입력 흐름은 배포본에서, 마이크 연결·해제와 화면 상태는 가짜 마이크로 확인했습니다.
- **종단 응답 시간(p95)과 동시 사용자 부하는 측정하지 않았습니다.** 확인한 것은 API 콜드 스타트 약 20초(헬스체크)뿐이고, STT 속도는 10문장 표본입니다(5.4).
- **요리명 추정 LLM(EXAONE)을 뺀 영향은 재지 않았습니다.** 같은 발화 세트로 A/B가 필요합니다.
- 등록 음성 생성 시간(화면 안내 "보통 1~3분")은 추정이며 실제 Modal에서 재 보지 않았습니다. 공용 음성 2,724개는 직접 생성해 올리는 중이라 올리기 전에는 실시간 TTS(GPU)를 씁니다.
- 기존 `users` 테이블 10명은 새 로그인(Supabase Auth)과 연결되지 않습니다. 데이터는 지우지 않았습니다.
- TTS 응답은 문장 길이에 따라 5초를 넘길 수 있습니다(로컬 RTX 5070 측정).
- 모델 저장소가 private라 실행에는 팀 토큰이 필요합니다.
- MOS는 지인 13명 편의표본입니다.

## 12. 라이선스·윤리

| 대상 | 라이선스 | 비고 |
|---|---|---|
| Whisper | MIT | 상업적 이용 가능 |
| Qwen3-TTS | Apache 2.0 | 상업적 이용 가능 |
| EXAONE-3.5-2.4B-Instruct | EXAONE AI Model License 1.1-NC | 비상업 전용, 수업 과제로 충족. 리뉴얼 서비스 경로에서는 쓰지 않음 |
| KSS | CC BY-NC-SA 4.0 | 비상업, 팀원 목소리 미사용 |
| 만개의레시피(KADX) | 정식 유통 경로 | 요리명·재료·조회수만 사용 |

서비스 실행 중 외부 LLM API 호출 없음. 사용자 음성은 말이 끝난 한 문장 분량만 서버로 보내고 저장하지 않습니다(등록 레시피의 합성 음성만 본인 전용 저장소에 보관).

---

문서 안내: [`renewal/DEPLOY.md`](renewal/DEPLOY.md)(배포 절차) · [`renewal/API_CONTRACT.md`](renewal/API_CONTRACT.md)(API 계약·오류 코드) · [`docs/specs/renewal_serverless.md`](docs/specs/renewal_serverless.md)(리뉴얼 스펙) · [`docs/decisions.md`](docs/decisions.md)(의사결정 기록) · [`docs/ChefEar_PRD_SDD_v0.9.md`](docs/ChefEar_PRD_SDD_v0.9.md)(요구사항·설계, 리뉴얼 전 기준) · [`docs/ChefEar_설계서.md`](docs/ChefEar_설계서.md) · [`docs/ChefEar_팀_진행_가이드_v3.md`](docs/ChefEar_팀_진행_가이드_v3.md) · [`docs/specs/`](docs/specs/README.md)(기능 스펙) · [`docs/presentation/`](docs/presentation/)(발표 자료)
