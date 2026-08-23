# src/stt/ — 담당: 하주성 (C, STT 파인튜닝)

## 이 폴더가 하는 일

`openai/whisper-large-v3-turbo`를 QLoRA(4-bit NF4) 방식으로 ChefEar 요리 도메인에 파인튜닝하고, 평가 및 통합환경에서 STT 추론을 담당합니다.

Whisper Small, wav2vec2 비교 실험을 거쳐 Whisper Large-v3-turbo를 최종 STT 모델로 선정했습니다.

V1 Adapter 기반 V2 추가 파인튜닝 실험도 진행했지만 성능 개선이 확인되지 않아, 현재 최종 STT 모델은 V1 Adapter인 `BEST_FINAL_mix750_replay_numeric`을 유지합니다.

학습 환경 및 패키지 버전은 `docs/stt.md`, `requirements-stt.txt`를 기준으로 합니다.

## 파일별 상태 (확인: 2026-08-19)

`prepare_data.py`는 STT 학습 데이터 준비 및 전처리에 사용합니다.

`finetune_whisper.py`는 현재 비어 있습니다.

`infer.py`는 최종 Adapter 로딩 및 STT 추론에 사용합니다.

2026-08-19 기준 `python-dotenv` 의존성을 제거하고, `HF_STT_MODEL_REPO` 환경변수가 없으면 기본 Adapter인 `leeony/chefear-stt-large-v3-turbo`를 사용하도록 수정했습니다.

또한 STT 출력의 `g`, `kg`, `ml`, `L` 단위를 각각 `그램`, `킬로그램`, `밀리리터`, `리터`로 정규화하는 후처리를 추가했습니다.

고위험군 159개 테스트에서 `다짐육 100그램`이 `다짐 600그램`으로 인식되는 패턴을 확인하여, 숫자를 무조건 치환하지 않고 현재 레시피의 재료 정보가 있을 때만 조건부로 보정하도록 `ingredient_context` 기반 로직을 추가했습니다.

**2026-08-19 추가**: `infer.py`가 배포 환경(`requirements.txt`)에 없는 `python-dotenv` 대신
`orchestration.db.load_env()`로 `.env`를 읽도록 바뀌었습니다(`src/tts/infer.py`와 동일한 방식,
아래 "환경변수 적용" 절의 `load_dotenv` 설명은 이 변경 전 기준이라 참고만 할 것). 또한
**배포용 단일 발화 함수 `stt_transcribe(audio) -> str`이 신규 추가**됐습니다 — 기존 `_transcribe_audio()`는
배치 평가 내부용이라 그대로 못 쓰고, 배포 환경(HF Spaces CPU Basic, GPU 없음)에 맞춰
4bit 양자화 대신 faster-whisper(int8, CPU)를 씁니다. faster-whisper는 HF transformers
체크포인트를 직접 못 읽어서, 먼저 `export_ct2.py`(신규, 오프라인 1회 실행 스크립트)로
LoRA merge → CTranslate2 int8 변환을 해둬야 합니다. 상세: `docs/specs/stt_deploy.md`.

## 현재 STT 모델

Base Model은 `openai/whisper-large-v3-turbo`를 사용합니다.

현재 V1 Adapter는 `leeony/chefear-stt-large-v3-turbo`이며, 로컬 최종 Adapter는 `BEST_FINAL_mix750_replay_numeric`을 기준으로 사용합니다.

V2 추가 파인튜닝 실험도 진행했지만 V1 대비 성능 개선이 확인되지 않아 최종 모델은 V1 Adapter를 유지합니다.

## infer.py 환경변수 적용

기존에는 `.env`와 `python-dotenv`를 사용하여 `HF_STT_MODEL_REPO`를 불러왔으나, 2026-08-19 기준 `python-dotenv` 의존성을 제거했습니다.

현재는 `HF_STT_MODEL_REPO` 환경변수가 있으면 해당 값을 사용하고, 없으면 기본값인 `leeony/chefear-stt-large-v3-turbo`를 사용합니다.

따라서 `.env` 파일 없이도 기본 STT Adapter를 불러올 수 있으며, 필요하면 실행 환경의 `HF_STT_MODEL_REPO` 값만 변경하여 다른 Adapter를 사용할 수 있습니다.

## 현재까지 진행

1. Whisper Small 파인튜닝 및 평가 완료
2. Whisper Large-v3-turbo QLoRA 파인튜닝 완료
3. Fixed100 / New500 평가 완료
4. wav2vec2 비교군 실험 완료
5. 비교 결과 기준 Whisper Large-v3-turbo 최종 선정
6. V1 최종 Adapter 구성 완료
7. `infer.py` 내부 STT Adapter Repo 하드코딩 제거
8. `HF_STT_MODEL_REPO` 환경변수 기반 모델 로딩 적용
9. STT 통합환경 패키지 버전 재검증
10. `requirements-stt.txt`를 현재 검증된 통합환경 기준으로 수정
11. V2용 전체 학습 후보 CSV 전처리 보강
12. 기존 학습 / Validation / Test 데이터와 신규 V2 후보 문장 중복 검사
13. 기존 데이터와 겹치지 않는 신규 V2 학습 문장 300개 선정
14. V2 추가 파인튜닝 실험 진행 후 V1 Adapter 최종 유지
15. `python-dotenv` 의존성 제거 및 기본 Adapter fallback 적용
16. STT 단위 표기 후처리(`g/kg/ml/L → 한글 단위`) 추가
17. 고위험군 159개 테스트 및 `다짐육 100그램 → 600그램` 계열 오인식 패턴 확인
18. 재료 문맥(`ingredient_context`) 기반 조건부 보정 로직 추가

## V2 데이터 전처리

V2에서는 기존 모델이 상대적으로 어려워했던 숫자·단위·온도·시간·복합 조리 표현을 추가로 학습하기 위해 기존 요리 텍스트 데이터의 정규화를 보강했습니다.

V2 전체 후보 데이터는 `ChefEar_STT_V2_train.csv`를 사용합니다.

전체 후보 문장 약 207,000건을 대상으로 전처리 및 중복 제거를 수행했습니다.

영문 단위가 실제 서비스에서 잘못 읽히는 문제를 줄이기 위해 숫자와 단위를 한국어 표현으로 정규화했습니다.

예시는 다음과 같습니다.

`185 g → 185그램`

`13 ml → 13밀리리터`

`5 mg → 5밀리그램`

`1.5 L → 1.5리터`

`2 T → 2큰술`

`1 tsp → 1작은술`

`187 도에서 → 187도에서`

추가로 `그램 을 → 그램을`, `밀리리터 을 → 밀리리터를`, `도 에서 → 도에서`, `분 간 → 분간`과 같은 단위와 조사 사이의 불필요한 공백도 정리했습니다.

전처리 후 `g`, `kg`, `mg`, `ml`, `L/l`, `T`, `TS`, `tsp`, `tbsp` 등의 대상 영문 단위가 남아있는지 다시 검사했고, 현재 대상 패턴은 모두 0건으로 확인했습니다.

## V2 신규 학습 문장 300개

V2는 기존 학습 데이터를 그대로 반복해서 사용하는 방식이 아니라, 기존 모델이 학습하지 않은 독립 문장을 새로 선정하는 방식으로 진행합니다.

최종 신규 학습 파일은 `ChefEar_train_sample_300.csv`입니다.

신규 300문장은 기존 STT 학습 데이터, Numeric reinforcement 데이터, Replay / Mix 학습 데이터, Validation 500, Fixed Test 100, 별도 외부 검증 문장과 겹치지 않도록 중복 검사를 수행했습니다.

V2 신규 문장은 단순 랜덤 추출이 아니라 기존 모델이 상대적으로 어려워했던 표현을 우선 포함하도록 구성했습니다.

주요 대상은 숫자 + 단위, 단위 + 조사, 온도 표현, 시간 표현, 수량 표현, 긴 조리 문장, 여러 조리 동작이 포함된 문장, 생소한 재료명 및 복합 요리 표현, 일반 조리 지시문입니다.

현재 신규 독립 학습 문장 300개 선정 및 CSV 저장까지 완료했습니다.

## V2 신규 학습 음성

신규 300문장에 대응하는 STT 학습용 음성을 별도로 생성합니다.

음성 파일은 CSV의 `v2_id`와 1:1로 연결합니다.

예시는 다음과 같습니다.

`v2_0001 → v2_0001.mp3`

`v2_0002 → v2_0002.mp3`

`v2_0003 → v2_0003.mp3`

현재 신규 학습 음성은 `ko-KR-SunHiNeural` 기반으로 생성하고 있습니다.

현재 수정 중인 ChefEar 팀 TTS 모델은 STT V2 신규 학습 데이터 생성에 사용하지 않습니다.

STT V2 학습용 음성 생성은 팀 TTS와 분리하여 진행합니다.

## 모델 비교

Whisper Small은 경량 비교군으로 사용했습니다.

wav2vec2는 타 STT 구조 비교군으로 사용했으며, 숫자·단위·일부 한국어 음절 처리에서 한계가 확인되어 추가 실험을 중단했습니다.

Whisper Large-v3-turbo를 최종 STT 모델로 선정했습니다.

V1 Adapter 기반 V2 추가 파인튜닝도 진행했지만 성능 개선이 없어 최종 모델은 `BEST_FINAL_mix750_replay_numeric`을 유지합니다.

상세 결과:

`ChefEar_STT_3model_comparison_final.csv`

`ChefEar_Whisper_small_실험요약.csv`

`wav2vec2_experiment_summary.csv`

## TTS → STT 통합 테스트

통합 테스트 스크립트는 `tests/tts_stt_roundtrip_test.py`입니다.

TTS가 생성한 음성을 STT로 전달하고 원문과 결과를 비교합니다.

2026-08-19 기준 `infer.py`에서 `python-dotenv` 의존성을 제거했으며, `HF_STT_MODEL_REPO` 환경변수가 없으면 기본 Adapter인 `leeony/chefear-stt-large-v3-turbo`를 사용합니다.

또한 `g`, `kg`, `ml`, `L` 단위를 한글 단위로 정규화하고, 고위험 숫자 오인식은 실제 재료 정보가 있을 때만 `ingredient_context`를 이용해 조건부 보정합니다.

## 현재 진행 / 남은 작업

* TTS → STT 통합 테스트 완료
* `transformers` 버전 충돌 해결 및 검증
* 고위험군 159개 STT 테스트 완료
* `다짐육 100그램 → 다짐 600그램` 계열 오인식 확인
* STT 단위 후처리 및 재료 문맥 기반 조건부 보정 적용
* 실제 통합환경 오류 유형 추가 수집
* 팀 TTS 수정 후 통합 재검증
* `src/orchestration/pipeline.py` 연결 확인
* Streamlit / HF Spaces 배포 환경 검증
* 필요 시 faster-whisper / CTranslate2 경량화 검토

## 2026-08-23 버그 수정 — `stt_transcribe` 이름 충돌로 실서비스가 베이스 모델을 쓰고 있었음

`infer.py`에 `stt_transcribe`라는 이름의 함수가 두 개(배포용 파인튜닝 어댑터 버전 + 2026-08-20에
"상시 마이크 파이프라인 확인용"으로 추가했던 원본 모델 버전) 있었습니다. 파이썬은 같은 이름의
나중 정의로 조용히 덮어쓰기 때문에, 실제로 `src/ui/voice_io.py`의 `listen()`(실서비스 마이크
경로)이 호출하는 `stt_transcribe`는 파인튜닝 어댑터가 아니라 **원본(파인튜닝 전)
`openai/whisper-large-v3-turbo`**로 바인딩되고 있었습니다(AppTest로 실측 확인). 워밍업 때
`load_ct2_model()`이 파인튜닝 어댑터를 GPU에 올리긴 했지만 실제 추론에는 안 쓰이는 죽은
코드였습니다.

원본 모델 버전을 `stt_transcribe_realtime_base()`로 이름을 바꿔서 충돌을 없앴습니다 — 파인튜닝
전/후 비교가 필요할 때만 직접 불러 쓰는 함수로 남겨뒀고, 실서비스 경로는 이제 정상적으로 파인튜닝
어댑터(`stt_transcribe()`, `load_ct2_model()`)를 씁니다. 이 함수를 위치 인자로 호출하던
`ui/streamlit_screens/stt_tts_test.py`도 함께 고쳤습니다(배포용 함수는 `sample_rate`가 키워드
전용 인자라 위치 인자로 주면 `TypeError`가 남).

## 주의

현재 STT는 `transformers + peft + bitsandbytes + Whisper Large-v3-turbo + LoRA Adapter` 구조를 사용합니다.

숫자 오인식은 무조건 치환하지 않고 실제 재료 정보가 확인되는 경우에만 보정합니다.

Validation / Test 데이터는 평가용으로 유지하며 정답 데이터를 문맥 보정에 사용하지 않습니다.

HF Spaces 배포에서는 메모리와 추론 속도를 고려해 별도 경량화가 필요할 수 있습니다.

## 관련 문서

* `docs/stt.md`
* `docs/ChefEar_PRD_SDD_v0.8.md`
* `docs/ChefEar_팀_진행_가이드_v2.md`
* `requirements-stt.txt`
* `src/tts/README.md`
* `tests/tts_stt_roundtrip_test.py`
