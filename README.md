---
title: ChefEar
emoji: 👨‍🍳
colorFrom: yellow
colorTo: orange
sdk: streamlit
sdk_version: "1.61.1"
app_file: src/app.py
pinned: false
---

# 👨‍🍳 AI Human 7기 : Chef Ear

## 👥 팀 정보

| 항목 | 내용 |
|---|---|
| 프로젝트 | Chefear |
| 조명 | A조 |
| 조장 | 김승욱 |
| 조원 | 홍민하, 하주성 |

## 👨‍🍳 조원 소개

| 이름 | GitHub | 역할 | 담당 업무 |
|---|---|---|---|
| 김승욱 | [@seungwook-kim](https://github.com/seungwook-kim) | 조장 / 오케스트레이션·통합 | 의도분류, 단계 진행·재료대체 로직, Supabase 검색, HF Spaces 배포 및 통합테스트 |
| 홍민하 | [@minhahamin](https://github.com/minhahamin) | TTS 파인튜닝 / UI | Qwen3-TTS-12Hz-1.7B-VoiceDesign + KSS 학습 환경 구성 및 파인튜닝, Streamlit UI 구현 |
| 하주성 | [@leeony2636](https://github.com/leeony2636) | STT 파인튜닝 | Whisper Small·wav2vec2 비교 실험, openai/whisper-large-v3-turbo QLoRA 파인튜닝, Fixed100/New500 WER·CER 평가 및 최종 STT 모델 선정 |

🍳 AI Human Recipe  
STT/TTS 도메인 파인튜닝을 기반으로, 요리 초보자가 손을 사용하기 어려운 상황에서도 음성만으로 레시피를 단계별로 진행하고 재료 변경까지 반영할 수 있도록 설계한 음성 레시피 에이전트입니다.

---

🎯 Product Goal

AI 휴먼 레시피는 요리 경험이 거의 없는 사용자가 칼질, 반죽, 재료 손질 등 손을 자유롭게 사용하기 어려운 상황에서도 화면을 반복해서 확인하지 않고 음성으로 조리 흐름을 이어갈 수 있도록 돕는 것을 목표로 합니다.

| Priority | Value | Description |
|---|---|---|
| 1 | 조리 완성도 유지 | 화면을 다시 확인하는 동안 발생할 수 있는 조리 타이밍 손실 방지 |
| 2 | 안전성 | 칼질이나 조리도구 사용 중 화면 조작 최소화 |
| 3 | 편의성 | 다음, 다시 알려줘 등 자연스러운 음성으로 조리 진행 |

---

👤 Target User

주요 사용자는 부모님과 따로 살기 시작한 직후이거나 요리를 거의 해본 적 없는 완전 초보 사용자입니다.

- 재료명과 계량 단위에 익숙하지 않음
- 조리 순서를 기억하기 어려움
- 요리 중 손이 젖거나 더러워 화면 조작이 불편함
- 조리 도중 재료가 없거나 다른 재료를 사용해야 하는 상황이 발생함
- 긴 레시피를 한 번에 듣기보다 현재 필요한 단계만 안내받기를 원함

---

🧭 Core Scenario

사용자: "된장찌개 만드는 법 알려줘"

AI  
↓  
레시피 검색  
↓  
간단한 개요 안내  
↓  
조리 시작 여부 확인  
↓  
1단계 안내

사용자: "다음"  
↓  
다음 단계 안내

사용자: "애호박 없는데 바지락 넣어도 돼?"  
↓  
실제 레시피 데이터에서 대체 가능한 레시피 검색  
↓  
변경된 레시피 기준으로 진행

사용자: "다시 알려줘"  
↓  
현재 단계 재청취

요리 완료  
↓  
변경된 레시피를 사용자 버전으로 저장

---

⚙️ Core Features

| Feature | Description | Priority |
|---|---|---|
| 음성 레시피 조회 | 자유발화를 STT로 변환하고 사용자 의도 분석 | Must |
| 단계별 조리 안내 | 전체 레시피를 한 번에 읽지 않고 한 단계씩 안내 | Must |
| 진행 / 재청취 | 다음, 다시, 한 번 더 등 다양한 표현 인식 | Must |
| 재료 대체 | 조리 중 다른 재료 사용 요청 시 실제 레시피 데이터 검색 | Must |
| 사용자 레시피 저장 | 변경한 레시피를 user_custom으로 별도 저장 | Must |
| STT 도메인 파인튜닝 | Whisper Small·wav2vec2 비교 후 Whisper Large-v3-turbo 최종 선정 및 요리 도메인 평가 | Must |
| TTS 도메인 파인튜닝 | Qwen3-TTS 기반 짧은 단계 안내용 자연스러운 음성 생성 및 통합 테스트 | Must |
| 화면 보조 UI | 현재 단계, 재료, 최근 대화를 Streamlit 화면에 표시 | Must |

현재 UI는 HTML 11개 화면과 이에 대응하는 Streamlit 화면 프로토타입으로 구현되었으며, 최종 `src/app.py` 기반 통합은 진행 중입니다.

---

✨ Differentiation

기존 AI 스피커 기반 요리 서비스의 핸즈프리 장점은 유지하면서 실제 조리 상황에서 발생하는 불편을 보완하는 것을 차별화 포인트로 합니다.

| Existing Limitation | AI Human Recipe |
|---|---|
| 정해진 레시피를 읽어주는 방식 | 사용자의 진행 속도에 맞춰 단계별 안내 |
| 주방 소음으로 음성 인식 성능 저하 | 요리 용어와 잡음환경을 반영한 STT 파인튜닝 |
| 재료가 없을 경우 대응 제한 | 실제 레시피 DB 기반 재료 대체 검색 |
| 개인의 변경사항 유지 어려움 | 변경된 레시피를 개인 버전으로 저장 |
| 음성만 제공할 경우 이전 내용을 확인하기 어려움 | 음성 중심 + 화면 보조 방식 |
| 일반적인 STT 모델 사용 | 재료명·계량단위·진행표현에 특화된 STT 구축 |

---

🗂️ Data & Models

### Recipe Data

KADX 만개의 레시피 데이터를 기준 데이터로 사용합니다.

- 고유 레시피 약 234,538건
- 고유 요리명 약 60,282개
- 동일 요리명이 여러 개인 경우 조회수 1위 레시피를 표준으로 선택

### STT

`openai/whisper-large-v3-turbo`

Whisper Small과 wav2vec2를 비교군으로 실험한 뒤, ChefEar 요리 도메인에서 가장 안정적인 WER/CER를 보인 Whisper Large-v3-turbo를 최종 STT 모델로 선정했습니다.

주요 인식 대상:

- 요리명
- 재료명
- 계량단위
- 진행 표현
- 긍정 / 확인 표현
- 숫자 / 단위
- 조리 행동 표현

### TTS

`Qwen3-TTS-12Hz-1.7B-VoiceDesign + KSS`

짧은 조리 단계 안내에 적합한 자연스러운 발화를 목표로 QLoRA 기반 파인튜닝을 완료했습니다
(HF Hub 비공개 업로드 완료). TTS→STT 재인식 검증(CER)은 체크포인트를 13에포크로 교체한 뒤
5문장 전부 CER 0.0000으로 확인되어 품질 문제는 해소되었습니다(2026-08-19). 다만 HF Spaces
CPU Basic 목표 응답시간(5초) 충족 여부는 옛 코드 경로 기준 실측(평균 197초, FAIL)만 있고
새 체크포인트/코드 경로로는 아직 재측정 전이라 배포 경로 대안 검토가 계속 필요합니다.

---

🔄 Service Flow

사용자 음성  
↓  
`openai/whisper-large-v3-turbo` STT  
↓  
의도 분류  
↓  
레시피 검색 / 진행 / 재청취 / 재료대체  
↓  
현재 조리 단계 결정  
↓  
`Qwen3-TTS-12Hz-1.7B-VoiceDesign + KSS` TTS  
↓  
음성 안내

의도 분류는 서비스 실행 중 외부 LLM API를 호출하지 않고 임베딩 유사도 비교 방식으로 처리합니다.

현재 STT 최종 모델 선정과 UI 프로토타입 구현은 완료되었으며, TTS 학습과 STT/TTS/Streamlit 통합 테스트를 진행 중입니다.

---

📌 Scope

### In-Scope

- 자유발화 기반 레시피 조회
- 단계별 조리 진행
- 진행 / 재청취 음성 명령
- 재료 대체 검색
- 사용자 레시피 등록 및 저장
- Whisper Small / wav2vec2 / Whisper Large 비교 및 STT 파인튜닝
- `openai/whisper-large-v3-turbo` 최종 STT 모델 선정
- `Qwen3-TTS-12Hz-1.7B-VoiceDesign + KSS` TTS 파인튜닝
- HTML + Streamlit 기반 화면 프로토타입 구현
- STT Fixed100 / New500 WER·CER 평가
- STT → 의도분류 → 레시피 처리 → TTS 통합 테스트

### Out-of-Scope

- 사진 기반 레시피 등록 및 OCR
- 서비스 실행 중 외부 LLM API 호출
- 데이터에 존재하지 않는 레시피의 실시간 생성
- AI 자체 판단에 의한 음식 궁합 조언
- TTS 발화 중 사용자 끼어들기 기능
- 실제 판매 및 결제 기능

---

🚦 Priority

### Must

STT/TTS 파인튜닝 · 음성 레시피 조회 · 단계별 진행 · 재청취 · 재료 대체 · 사용자 레시피 저장 · 화면 보조 UI

### Should

STT/TTS 통합 안정화 · 다양한 사용자 표현 대응 · 숫자·계량단위 인식 강화 · 실사용 발화 검증

### Could

TTS 음성 톤 다양화 · 추가 STT 모델 비교 · UI 시각적 완성도 향상 · STT 배포 경량화

---

✅ Validation

| Evaluation | Criteria |
|---|---|
| STT 성능 | Fixed100 / New500 기준 WER 비교 |
| STT 보조 평가 | CER 비교 및 모델 간 성능 비교 |
| STT 비교군 | Whisper Small / wav2vec2 / Whisper Large 결과 비교 |
| TTS→STT 검증 | TTS 생성 음성을 최종 STT 모델로 재인식하여 원문 보존 여부 확인 |
| TTS 성능 | 계량단위 발음 및 짧은 안내 자연스러움 평가 |
| 재료 대체 완료율 | 손을 씻지 않고 음성만으로 재료 대체 완료율 90% 이상 |
| 사용성 | 손에 재료가 묻은 상황에서도 화면 조작 없이 조리 진행 가능 |
| 진행 정확도 | 다음, 다시 등의 발화에 현재 상태가 정상적으로 유지 |
| 재료 대체 | 요청한 재료가 실제 레시피 DB에 존재할 경우 정상 반영 |
| 응답 속도 | 조리 단계 안내 5초 이내 |

---

🏁 Success Criteria

이 프로젝트의 성공은 단순히 레시피를 조회할 수 있는지 여부가 아니라 요리 중 실제로 음성만으로 조리 흐름을 유지할 수 있는지를 기준으로 판단합니다.

- Whisper Small 및 wav2vec2 비교군 대비 Whisper Large-v3-turbo에서 더 안정적인 STT 오류율 확보
- 사용자가 화면을 반복해서 확인하지 않고 단계 진행, 재청취, 재료 변경 수행
- 손을 씻지 않고 음성만으로 재료 대체 완료율 90% 이상 달성
- TTS 생성 음성이 STT 재검증 과정에서 재료명, 숫자, 단위, 조리 행동 등 핵심 정보를 안정적으로 보존

---

💡 One-Line Definition

기존 음성비서가 레시피를 읽어주는 서비스라면, AI 휴먼 레시피는 사용자의 조리 진행과 재료 변경에 맞춰 레시피가 함께 변하는 음성 요리 에이전트입니다.