## 셰프이어(ChefEar) — PRD(SDD) v0.9 최종본

STT/TTS 도메인 파인튜닝 기반 음성 레시피 진행·등록 에이전트

| 항목 | 내용 |
| --- | --- |
| 프로젝트 | AI Human 7기 1차 팀 프로젝트 — 딥러닝 기반 TTS·STT 서비스 |
| 팀 | 김승욱(조장), 홍민하, 하주성 |
| 작성자 | 김승욱 |
| 착수일 | 2026-08-14 |
| 기준일 | 2026-09-10 — 마무리 작업(09-01 ~ 09-08)까지 반영한 최종본. v0.8(08-28)은 이 문서로 대체됨 |
| 배포 범위 | 팀 내부 / 지도 강사 검토 / 포트폴리오 |

PART 1(PRD)은 무엇을 왜 만드는지, PART 2(SDD)는 어떻게 만들었는지를 담는다. 장 번호는 파트 안에서만 유효하다.

---

# PART 1 — PRD

## 0. Executive Summary

요리를 거의 해본 적 없는 초보가 칼질·반죽처럼 손을 못 쓰는 순간에도 화면을 보지 않고 음성으로 레시피를 한 단계씩 안내받는 에이전트다. 핵심 가치는 시간 절약이 아니라 **완성도 손실 방지**다. STT(Whisper)와 TTS(Qwen3-TTS)를 요리 도메인 데이터로 파인튜닝했고, 상시 마이크 기반 파이프라인(STT → 의도분류 → 레시피 처리 → TTS)이 GPU 서버에서 실제로 구동 중이다.

프로젝트 기간 중 세 가지 큰 방향 전환이 있었다. ① 재료 대체 기능 제거(08-27) ② 계정 제거(08-27) 후 재도입(09-01)과 소유자 기준 공개 범위(09-02) ③ 조리순서 데이터를 60,282건 전량에서 500건 큐레이션으로 교체(09-01). ②와 ③은 08-31 발표로 과제 마감이 끝난 뒤, 김승욱·홍민하 두 사람이 강의 후 저녁 시간에 09-08까지 이어서 완성한 것이다. 이 기간에 GPU 서버 이관과 프로세스 워커 풀 전환도 함께 끝내 지금의 배포 상태가 됐다. 각 결정의 근거는 `docs/decisions.md`에 있다.

## 1. 배경 및 문제 정의

### 1.1 대상 사용자 페르소나

| 항목 | 내용 |
| --- | --- |
| 이름(가상) | 김민지 (24세, 사회초년생) |
| 상황 | 3개월 전 취업과 함께 처음 자취 시작. 요리 경험 거의 없음 |
| 요리 경험 | 라면, 계란후라이 정도. '큰술'이 얼마인지 감이 없음 |
| 기술 친숙도 | 스마트폰 앱에는 익숙, 레시피 서비스는 처음 |
| 동기 | 배달만 시키는 게 부담스러워 직접 요리하고 싶지만 자신이 없음 |

### 1.2 하루 시나리오

퇴근 후 저녁, 민지는 처음으로 된장찌개를 만든다. 감자를 써는 도중 손에 물기와 전분이 묻어 다음 순서를 확인하러 폰을 만지지 못한다. 손을 씻고 화면을 다시 보는 사이 끓던 육수 농도가 변했고, 결과물이 기대와 다르게 짜졌다.

### 1.3 Job To Be Done

요리 경험이 전무한 사람이, 처음 도전하는 요리에서 손이 바쁜 순간에도 화면을 다시 보지 않고 다음에 뭘 해야 할지 정확히 안내받아, 첫 시도부터 완성도를 잃지 않도록 돕는 것.

### 1.4 페인 포인트

| # | 문제 | 메커니즘 | 현재 우회 행동 |
| --- | --- | --- | --- |
| 1 | 완성도 손실(핵심) | 손을 씻고 화면을 보고 복귀하는 사이 반죽 농도·양념 타이밍 손실 | 감으로 이어가거나 처음부터 다시 |
| 2 | 안전 | 칼질 중 집중이 안전으로 쏠려 이전 단계를 잊음 | 천천히 진행, 시간 증가 |
| 3 | 시간 손실(부수) | 매번 손 씻고 확인 | 요리 포기, 배달 |

## 2. 경쟁/유사 서비스 분석

| 구분 | 레시피오 | 레시핏 | 만개의레시피 | ChefEar |
| --- | --- | --- | --- | --- |
| 인터랙션 | 텍스트 채팅 | 음성 핸즈프리, 정해진 명령어 | 음성은 레시피 작성(입력)용 | 자유발화 음성 안내(출력) 중심 |
| 데이터 | 확인 안 됨 | 유튜브 영상을 그때그때 AI 변환 | 사용자 등록 20만여 개, 검증 절차 불명 | 한국 가정식 500개 큐레이션 + 본인 등록분 |
| 신규 등록 | 불가 | 확인 안 됨 | iOS 앱 불가 | 로그인 후 발화/텍스트로 등록, 본인에게만 노출 |
| 비즈니스 | 커머스+광고 | 확인 안 됨 | 커머스 | 판매·결제 Out-of-Scope |

차별점은 음성 지원 여부가 아니라 **①임베딩 기반 자유발화 이해 ②작지만 검수 가능한 큐레이션 데이터 ③조리 용어를 설명과 함께 읽어주는 초보자 배려**의 조합이다. 직접 사용 기록은 `docs/ChefEar_경쟁사분석.md`.

## 3. 제품 목표 및 성공 기준

핵심 가치 우선순위: ① 완성도 손실 방지 ② 안전 ③ 시간 절감.

| 지표 | 목표 | 결과 |
| --- | --- | --- |
| 1단계 안내 응답 시간 | 5초 이내 | TTS 단독 5.21초(RTX 5070, SDPA+compile). 종단 시간은 미측정 |
| TTS→STT 재인식 CER | 파인튜닝 후 개선 | epoch-13 기준 5문장 전부 0.00 (epoch-8 평균 1.37) |
| STT WER 개선 | 파인튜닝 전/후 개선 | 신규500 WER 33.20% → 10.72% |
| 타인 등록 레시피 노출 | 0건 | 소유자 필터 + 테스트로 보장 |
| 동일 시나리오 반복 성공 | 정성 평가 | 통합 시나리오 31/31 PASS(08-16), 이후 수동 확인 |

## 4. 기능 요구사항 (제품 관점)

### 4.1 Must (구현 완료)

- 시작 인사말: 자유발화 유도, 상시 마이크로 버튼 없이 계속 듣기
- 조회: 요리명 발화 시 표준 레시피 안내, 1단계씩 짧게 진행, 조리 용어는 설명을 함께 읽음
- 진행 제어: "다음/다시/이전" 자유발화, 1단계에서 "이전"은 유지
- 계정: 로컬 가입 + 구글 OAuth 로그인
- 신규 등록: 로그인 사용자가 요리명→재료→순서를 입력하고 저장, 본인에게 즉시 조회
- 마이레시피: 목록/수정/삭제
- 관리자 페이지: 토큰 + 화자검증 2단계, 레거시 승인 대기 행 처리
- TTS·STT 파인튜닝 및 전/후 정량 비교

### 4.2 Should (구현 완료)

- 화면에 현재 단계·재료·최근 대화 병행 표시
- 숫자+단위 정확 인식, 조리 문맥 기반 고위험 숫자 보정
- 음성 실패 시 [이전][다시][다음] 수동 버튼
- 조회·합성 결과 세션 캐시, 다음 단계 음성 프리페치

### 4.3 Won't (Out of Scope)

| 항목 | 사유 |
| --- | --- |
| 사진으로 레시피 등록 | 과제 범위 밖 |
| 서비스 응답 경로의 외부 LLM API | 강사 가이드 요건. 로컬 LLM은 해당 없음 |
| 데이터 밖 요리의 조리순서 실시간 생성 | 정직 안내 후 등록 유도 |
| 재료 궁합 AI 조언 | 신뢰성 검증 불가 |
| 바지인(TTS 중 끼어들기) | 짧은 응답으로 해결, 난이도 대비 효과 낮음 |
| 판매·결제, 타이머, 손 씻기 감지 | 범위 밖 |
| 조리 중 다른 요리로 전환 | 오인식으로 레시피가 바뀌는 것을 막기 위해 처음 화면에서만 조회 |
| 재료 대체 | 08-27 제거(`docs/specs/remove_ingredient_substitution.md`) |
| 등록 레시피 공개/공유 | 본인 전용으로 고정 |

## 5. 사용자 시나리오

**A — 조회·진행**: "된장찌개 어떻게 만들어?" → "된장찌개, 표준 레시피예요. 이걸로 시작할까요?" → "응" → "일단계, 두부와 감자를 깍둑썰기 해주세요. 깍둑썰기는 사방 1~2cm 정육면체로 써는 방법이에요." → "다음" …

**B — 데이터 밖 요리**: "문어초무침 어떻게 만들어?" → "등록되지 않은 레시피예요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요." → (로그인) → "등록" → 요리명·재료·순서 입력 → 저장 → 본인에게 즉시 조회.

**C — 다른 사용자**: B가 등록한 문어초무침을 A가 물으면 "등록되지 않은 레시피" 안내.

**D — 관리자(레거시)**: `/admin` 토큰 접근 → 랜덤 한글 단어 3개 읽어 화자검증 → 09-02 이전 승인 대기 행 열람·승인·삭제.

## 6. 완료 정의 및 검증

- **AC-14 핵심 시나리오 완주**: 화면 터치 없이 음성만으로 마지막 단계까지 진행 — 시연 영상으로 확인.
- **AC-15 반복 질의 일관성**: 동일 레시피 반복 조회 시 동일 결과 — 통합 시나리오 스크립트 PASS.
- **AC-16 딥러닝 검증**: 파인튜닝 전/후 WER·CER·MOS 수치 제시 — README 5장, `results/`.
- 단위테스트: `pytest tests/` 119개 통과(2026-09-10).

## 7. 딥러닝 과제 정의 및 강사 가이드 준수

파인튜닝 대상은 TTS(Qwen3-TTS)와 STT(Whisper) 둘 다다. 서비스 실행 중 외부 LLM API를 호출하는 코드는 없다. 의도분류는 임베딩 유사도, 요리명 추정은 팀 GPU에 직접 로드한 로컬 LLM(EXAONE-3.5-2.4B)이 담당하며 인터넷 너머로 텍스트를 보내지 않는다.

## 8. 라이선스

Whisper(MIT) · Qwen3-TTS(Apache 2.0) · KSS(CC BY-NC-SA 4.0, 비상업) · EXAONE(1.1-NC, 비상업) · 만개의레시피 KADX(정식 유통, 요리명·재료·조회수만 사용).

---

# PART 2 — SDD

## 1. 개요 및 딥러닝 과제 범위

| 구분 | 범위 | 비고 |
| --- | --- | --- |
| 파인튜닝 | TTS `Qwen3-TTS-12Hz-1.7B-Base` | KSS LoRA 후 merge, HF Hub `kimseunguk/qwen3-tts-kss-finetuned` |
| 파인튜닝 | STT `openai/whisper-large-v3-turbo` | QLoRA(4-bit NF4), 어댑터 `leeony/chefear-stt-large-v3-turbo`, 배포는 CTranslate2 int8 `kimseunguk/chefear-stt-ct2-int8` |
| 임베딩(비파인튜닝) | 의도분류 `jhgan/ko-sroberta-multitask` | 외부 API 없음 |
| 로컬 LLM | 요리명 추정·등록 의도 `EXAONE-3.5-2.4B-Instruct` | 팀 GPU 직접 로드 |
| 화자검증 | 관리자 2FA `speechbrain/spkrec-ecapa-voxceleb` | CPU |
| 데이터 | 한국 가정식 500개 | 요리명·재료·조회수는 실데이터, 조리순서는 규칙 생성(1.4) |

### 1.4 조리순서 데이터 구성 (있는 그대로)

만개의레시피 원본에는 조리순서 컬럼이 없다. 초기(08-16)에는 고유 요리명 60,282건 전량을 적재하고 조리순서를 ChatGPT로 오프라인 생성해 채웠다. 6만 건의 문장을 사람이 검수할 수 없어 2026-09-01에 **한국 가정식 500개**로 범위를 줄이고, 재료 목록을 근거로 규칙 기반 알고리즘이 조리순서 2,950단계를 생성한 뒤 조리 용어 926개에 `[TERM:용어]` 태그를 붙여 전면 교체했다(`db/migrate_500_recipes_step1_truncate.sql`, `src/orchestration/load_500_recipes.py`). 서비스는 저장된 문장을 조회만 하고 런타임에 생성하지 않는다.

### 1.5 외부 LLM API 배제 원칙

| 처리 | 방식 | 외부 API |
| --- | --- | --- |
| 의도분류 | 임베딩 코사인 유사도 | 아님 |
| 요리명 추정·등록 의도 | 로컬 LLM(EXAONE) | 아님(로컬 추론) |
| 조리순서 제공 | 사전 적재 데이터 조회 | 해당 없음 |
| 관리자 화자검증 | ECAPA-TDNN CPU | 아님 |

## 2. 범위 정의

In-Scope: 자유발화 조회, 단계 진행, 조리 중 전환 금지, 로그인(로컬/구글), 등록(로그인 필수), 마이레시피, 소유자 기준 공개, 관리자 페이지(레거시), 화면 병행 표시, 수동 버튼, TTS·STT 파인튜닝. Out-of-Scope는 PART 1 4.3과 같다.

## 3. 시스템 아키텍처

### 3.1 전체 처리 흐름

```
상시 마이크(WebRTC) → VAD(silero-vad) 발화 분리
  → STT(faster-whisper, CTranslate2 int8)
  → 단위 정규화 · 조리 문맥 숫자 보정 · 환각 방어
  → (조리 중 아니면) 로컬 LLM(EXAONE) 요리명 추정 + 등록 의도
  → 임베딩 의도분류(threshold 0.5, margin 0.05)
  → 라우팅: 조회 / 진행·재청취·이전 / 등록 / 감탄사(무시) / 미분류(되묻기)
  → 응답 텍스트 → [TERM] 태그 해석(음성용 설명 삽입) → TTS(Qwen3-TTS) → 자동 재생 + 화면 갱신
```

### 3.2 GPU 실행 구조

STT·임베딩·로컬 LLM·TTS는 `gpu_worker_pool.py`의 별도 프로세스 워커(기본 3개, `spawn`)에서 실행된다. Streamlit 메인 프로세스는 마이크 프레임 드레인만 담당하고 추론 결과는 `Future`로 받는다. 워커가 죽으면(`BrokenProcessPool`) 풀을 자동 재생성한다. 이 구조는 스레드 락 방식이 GIL 경합으로 "Queue overflow"를 일으킨 실측 결과에서 나왔다.

### 3.3 등록·공개 범위

로그인 사용자만 등록 가능. `save_recipe()`는 `owner_id` 없이는 저장을 거부하고 `approved='Y'`로 즉시 저장한다. `select_standard_recipe()`는 `api_standard` 또는 조회자 본인 소유 행만 후보로 삼는다. 관리자 페이지는 `approved='N'`인 레거시 행만 다룬다.

### 3.4 화면 구성

`login`/`signup` → `start` → `recipe_confirm` → `cooking_step`(반복) → `cooking_complete`. 그 외 `unclassified`, `register_dish_name` → `register_ingredients` → `register_steps` → `complete`, `my_recipes` → `edit_recipe`. 별도 페이지 `/admin`, `/enroll`. 화면 전환 잔상(streamlit/streamlit#8360)은 화면 본문을 재사용 `st.empty()` 슬롯 하나에 그리는 방식으로 대응한다.

### 3.5 상시 마이크

세션당 한 번 WebRTC 연결을 맺고 화면이 바뀌어도 유지한다. `MicVadSegmenter`가 "발화 시작 ~ 600ms 무음"을 한 발화로 잘라 넘기고, STT 내부 VAD는 끈다(이중 VAD로 작은 목소리가 걸러지던 문제). TTS 재생 중에는 재생 길이만큼 마이크 입력을 무시한다.

## 4. 기능 요구사항

| ID | 요구사항 | 상태 |
| --- | --- | --- |
| FR-01 | 자유발화 의도 판단(임베딩 유사도), 상시 마이크 | 완료 |
| FR-02 | 레시피 조회 → 진행 확인 → 1단계씩 안내 | 완료 (500건) |
| FR-03 | 다음/다시/이전 | 완료 |
| FR-05 | 동일 요리명 다건 시 조회수 1위 자동 채택 | 완료 |
| FR-06 | 신규 등록(로그인 필수) | 완료 |
| FR-09 | Whisper 파인튜닝·배포 | 완료 |
| FR-10 | Qwen3-TTS 파인튜닝·배포 | 완료 |
| FR-11 | 전/후 정량 평가 | 완료 |
| FR-13 | 화면 병행 표시 | 완료 |
| FR-14 | 숫자+단위 인식·보정 | 완료 |
| FR-15 | 기준 예문 세트(110개) | 완료 |
| FR-16 | 수동 버튼 | 완료 |
| FR-17 | 로컬 LLM 요리명 추정 | 완료 |
| FR-18 | 계정(로컬/구글) | 완료 (09-01 재도입) |
| FR-19 | 상시 마이크 + VAD | 완료 |
| FR-20 | 조리 중 전환 금지 | 완료 |
| FR-21 | 관리자 승인 | 레거시 전용 |
| FR-22 | 관리자 2FA(토큰+화자검증) | 완료 |
| FR-23 | 마이레시피(목록/수정/삭제) | 완료 |
| FR-24 | 등록 레시피 소유자 전용 노출 | 완료 |
| FR-25 | 조리 용어 태그(TTS 설명 삽입, 화면 용어 표시) | 완료 |
| ~~FR-04, 08~~ | 재료 대체, 개인 버전 우선 | 제거 |

## 5. 비기능 요구사항

| 구분 | 요구사항 | 기준/결과 |
| --- | --- | --- |
| 성능 | 1단계 안내 응답 | 5초 목표, TTS 단독 5.21초 |
| 인프라 | 배포 환경 | RunPod A40(48GB) Pod, Docker, Cloudflare Tunnel |
| 동시성 | GPU 자원 공유 | 프로세스 워커 풀 3개, 워커당 VRAM 약 10GB |
| 신뢰성 | STT 환각 방어 | `no_speech_prob` 0.85 초과 폐기, 상투구 블록리스트, 반복 토큰 감지 |
| 신뢰성 | 워커 장애 복구 | `BrokenProcessPool` 시 풀 자동 재생성 |
| 보안 | 등록 데이터 격리 | `owner_id` 필터, IDOR 테스트 |
| 보안 | 관리자 인증 | IP당 5회 실패 시 60초 잠금 |

## 6. 데이터 모델

### 6.1 데이터 소스

| 소스 | 역할 |
| --- | --- |
| KADX 만개의레시피 CSV | 요리명·재료·인분수·조회수 실데이터(원본 234,538건, 고유 요리명 60,282건) |
| `docs/한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv` | 서비스가 쓰는 500건. 요리명·재료는 원본에서, 조리순서는 규칙 생성 |

### 6.2 Supabase 테이블

| 테이블 | 컬럼 | 설명 |
| --- | --- | --- |
| recipes | id, dish_name, ingredients, source, origin_id, view_count, external_id, servings, owner_id, approved, created_at | source: api_standard/user_custom. owner_id: 등록자(09-01부터 필수). approved: 신규는 'Y', 'N'은 레거시 |
| recipe_steps | recipe_id, step_number, step_text, source | source: api_standard/user_custom/rule_generated. step_text에 [TERM] 태그 포함 |
| users | user_id_hash(PK), user_id, auth_provider, google_sub, password_hash, session_token_hash, created_at | 로컬/구글 계정 |

관리자 성문은 DB가 아니라 로컬 `data/admin_voiceprints.json`(커밋 금지).

### 6.3 요리명 인식 보정

완전일치 → 부분일치 → 자모 단위 편집거리("된장치게"→"된장찌개") 3단계에, 공백 무시·반복 축약("된장찌장찌개") 안전망을 더한다. 안전망은 내용이 완전히 같은 경우만 매칭한다.

### 6.4 의도분류

의도 집합: 조회/등록/진행/재청취/이전/감탄사/미분류. 1위 유사도 < 0.5이면 미분류, 1·2위 차이 < 0.05이면 미분류(되묻기). 조리 중 조회·등록 의도는 무시(FR-20).

## 7. 인터페이스 요약

| 함수 | 위치 | 역할 |
| --- | --- | --- |
| `stt_transcribe()` | src/stt/infer.py | 오디오 → 텍스트(정규화·보정·환각 방어) |
| `extract_intent_llm()` | src/orchestration/entity_extract_llm.py | {dish_name, wants_register} |
| `classify_intent()` | src/orchestration/intent_classifier.py | intent, similarity_score |
| `extract_dish_name()` / `select_standard_recipe()` | src/orchestration/recipe_search.py | 요리명 보정 / 소유자 필터 포함 표준 선정 |
| `handle_utterance()` / `advance_step()` | src/orchestration/pipeline.py | 발화 라우팅 / 단계 전이 |
| `register_recipe()` / `save_recipe()` / `update_recipe()` / `delete_recipe()` | src/orchestration/registration.py | 등록 상태 기계, 저장·수정·삭제 |
| `signup()` / `login()` / 구글 로그인 처리 | src/orchestration/auth.py | 계정 |
| `submit_stt()` / `submit_tts()` / `submit_llm_extract()` / `submit_handle_utterance()` | src/orchestration/gpu_worker_pool.py | 워커 풀 제출 |
| `resolve_for_tts()` / `resolve_for_display()` / `auto_tag_terms()` | src/orchestration/term_dict.py | 용어 태그 |
| `tts_synthesize()` | src/tts/infer.py | 텍스트 → (waveform, sr) |
| `embed()` / `verify()` / `enroll()` | src/orchestration/speaker_verify.py | 화자검증 |

## 8. 기술 스택 및 배포

| 구분 | 패키지 | 버전 |
| --- | --- | --- |
| 언어 | Python | 3.13 |
| UI | streamlit | 1.61.1 |
| 의도분류 | sentence-transformers | 5.6.1 |
| STT 추론 | faster-whisper | 1.2.1 |
| 학습·로컬 LLM | transformers / peft / bitsandbytes | 4.57.3 / 0.20.0 / 0.50.0 |
| TTS 추론 | qwen-tts | 0.1.1 |
| 평가 | jiwer | 4.0.0 |
| DB | supabase | 2.31.0 |
| 상시 마이크 | streamlit-webrtc / silero-vad / aiortc | 0.77.0 / 6.2.1 / 1.15.0 |
| 화자검증 | speechbrain / torchaudio | requirements-main.txt |
| 런타임 | torch (cu124) | 2.6.0 |

배포: 멀티스테이지 Dockerfile(CUDA 12.4 runtime, Python 3.13 소스 빌드, flash-attn 사전빌드 휠) → GitHub Actions로 GHCR 이미지 → RunPod A40 Pod → `docker/entrypoint.sh`가 cloudflared + Streamlit 기동 → `chefear.store`. 랜딩(Vercel)을 거쳐 `ACCESS_GATE_TOKEN`이 붙은 URL로 접속. 절차는 `docs/runpod_deploy.md`.

기술 선택 근거: Whisper large-v3-turbo(Small·wav2vec2 비교 후 WER 최저), Qwen3-TTS(Apache 2.0, 한국어, voice-clone), 임베딩 의도분류(외부 API 배제), EXAONE(한국어 네이티브 경량 모델), 프로세스 워커 풀(GIL 회피), RunPod(로컬 12GB VRAM 한계).

## 9. 팀 구성

| 역할 | 담당 | 책임 |
| --- | --- | --- |
| 오케스트레이션·통합·배포(조장) | 김승욱 | 의도분류, 검색·등록 로직, 상시 마이크, 워커 풀, Whisper 파인튜닝·평가, Docker·RunPod, 데이터 큐레이션, 문서 |
| TTS·UI·계정 | 홍민하 | Qwen3-TTS 파인튜닝, Streamlit 화면, 로그인·마이레시피, 소유자 격리 보안 |
| STT 평가·데이터 | 하주성 | Fixed100 검증셋, 학습 환경 고정, 단위 정규화·문맥 보정(08-24까지) |
