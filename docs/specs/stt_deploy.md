# Spec — STT 배포용 `stt_transcribe()` (faster-whisper, HF Spaces CPU Basic)

관련: `tests/integration_issues_2026-08-18.md` 이슈 #5, `docs/ChefEar_PRD_SDD_v0.8.md` 7.1/8.1/8.2, `src/stt/README.md`.

## Why

- **페르소나**: 요리 경험이 거의 없고 손에 재료가 묻어 화면을 만지기 어려운 사용자(셰프이어 ICP, PRD 1.1)
- **상황**: 실제 배포 환경은 Hugging Face Spaces CPU Basic(GPU 없음, PRD 8.2)로 확정돼 있는데,
  지금 있는 `src/stt/infer.py`는 `BitsAndBytesConfig(load_in_4bit=True)` 4bit(NF4) 양자화를
  쓴다 — 이건 CUDA 커널 기반이라 GPU 없는 환경에선 로드 자체가 안 된다.
- **문제**:
  1. `app.py`가 완성돼도 배포 환경에서 첫 STT 호출 즉시 크래시한다(`ModuleNotFoundError`나
     import 에러가 아니라 모델 로드 시점의 CUDA 에러 — 더 늦게, 더 눈에 띄게 실패함)
  2. PRD 7.1 인터페이스 명세에 `stt_transcribe(오디오) -> 텍스트`가 정의돼 있지만 아직 없다 —
     지금 있는 `_transcribe_audio()`는 "배치 테스트 내부용, 외부 호출 대상 아님"이라고
     docstring에 명시돼 있어 그대로 갖다 쓰면 안 된다
  3. faster-whisper(1.2.1, int8 양자화)로 배포한다는 결정은 이미 확정(PRD 8.1)이고
     `requirements.txt`에도 이미 포함돼 있지만, 실제 변환·로딩 코드가 없다
- **측정 지표**: PRD 5장 "1단계 안내 응답시간 5초 이내"(전체 파이프라인 목표, STT는 그 중
  일부), FR-11(파인튜닝 전/후 WER 비교)

## Goal

- **해결 목표**: `src/stt/infer.py`에 `stt_transcribe(audio) -> str`를 faster-whisper 기반으로
  추가해서, GPU 없는 HF Spaces CPU Basic 환경에서도 로드·추론이 되게 한다.
- **성공 기준**:
  1. `CUDA_VISIBLE_DEVICES=""`(GPU 미가시) 환경에서 모델 로드 성공 + 예외 없이 텍스트 반환
  2. 기존 GPU 4bit 버전(`_transcribe_audio()`) 대비 정확도 손실을 Fixed100 테스트셋 기준
     WER 비교표로 확인(합격선 자체는 미정 — 1차 실측 후 팀 논의해서 확정, PRD도 "실측 후
     확정"으로 열어둔 항목과 동일한 취급)
  3. 2vCPU 흉내 조건(`cpu_threads=2`)에서 문장 1개 응답시간 실측 및 기록 — 목표치는 PRD
     5초(전체 파이프라인) 중 STT 몫으로 팀이 별도 배분 필요(Open Issue)
- **Out of Scope**:
  - STT V2 어댑터 학습/전환(`src/stt/README.md`의 별도 진행 트랙)
  - 마이크 입력 UI 자체(`app.py`, 별도 Spec `app_e2e.md`)
  - 4bit GPU 평가 경로(`_transcribe_audio()`) 교체 — 그대로 유지, 학습/평가용으로 계속 사용
  - 스트리밍 인식(부분 결과 실시간 표시) — 문장 단위 일괄 인식만

## What

**Happy Path**
1. `app.py`가 마이크로 녹음한 오디오(파일 경로 또는 파형 배열)를 `stt_transcribe(audio)`에 전달
2. 최초 호출 시 int8 양자화된 CTranslate2 포맷 모델을 1회 로드(캐싱, 이후 호출은 재사용)
3. faster-whisper가 텍스트를 반환
4. `app.py`가 그 텍스트를 `orchestration.pipeline.handle_utterance()`에 그대로 전달

**Edge Cases** (최소 5개 + 처리 방식)

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 무음/너무 짧은 오디오(<0.5초 등) | 빈 문자열 반환 — app.py가 "다시 말씀해주세요"로 안내(그럴싸하게 지어내지 않음, 1.5 원칙) |
| EC-02 | 모델 로드 실패(변환본 다운로드 실패 등) | 예외를 삼키지 않고 그대로 올려서 app.py가 "일시적 오류"로 안내 |
| EC-03 | 지원 안 되는 오디오 포맷/샘플레이트 | faster-whisper 내부 리샘플링에 맡기되, 실패 시 명확한 에러 메시지 유지 |
| EC-04 | LoRA→CTranslate2 변환본이 아직 준비 안 된 상태(배포 전 오프라인 작업 누락) | 로드 시점에 명확한 에러로 실패 — 조용히 사전학습 베이스로 폴백하지 않음(잘못된 모델로 응답하는 게 더 위험) |
| EC-05 | 숫자+단위 조합("1.5컵") 인식(FR-14) | 파인튜닝 어댑터가 이미 처리하는 영역 — 변환 후에도 Fixed100 기준 동일 정확도 유지되는지 확인 |

## How

**기술적 제약 (확정 필요한 부분)**

faster-whisper는 HuggingFace `transformers` 체크포인트를 직접 못 읽는다 — CTranslate2 포맷으로
변환이 먼저 필요하다(`ct2-transformers-converter`). 지금 STT는 base(`openai/whisper-large-v3-turbo`)
+ LoRA 어댑터(`leeony/chefear-stt-large-v3-turbo`) 구조라, 변환 전에 `merge_and_unload()`로
먼저 병합한 단일 체크포인트를 만들어야 한다 — TTS가 이미 같은 패턴을 씀(`src/tts/infer.py`
상단 주석 "QLoRA 파인튜닝 + merge_and_unload" 참고).

변환 파이프라인(1회 오프라인 작업, 매 배포마다 반복 아님):
1. `WhisperForConditionalGeneration` + `PeftModel`로 로드 → `merge_and_unload()`
2. 병합된 모델을 HF 포맷으로 저장
3. `ct2-transformers-converter --model <병합 경로> --output_dir <ct2 경로> --quantization int8`
4. 변환 결과물 반입 방식 — **Open Issue**: (a) HF Hub 새 private repo로 업로드(TTS와 동일
   패턴, 예: `HF_STT_CT2_REPO` env var로 관리) vs (b) 저장소 직접 커밋. PRD 8.2가 "git 저장소에
   가중치 직접 커밋 금지"를 이미 못박아서 (a)가 원칙에 맞지만, 팀 확인 후 확정할 것

**함수 시그니처**
```python
def stt_transcribe(audio: str | Path | np.ndarray, *, sample_rate: int | None = None) -> str:
    """faster-whisper(int8)로 오디오 하나를 텍스트로 변환. HF Spaces CPU Basic 배포용.

    audio: 파일 경로(mp3/wav) 또는 numpy 파형 배열(이 경우 sample_rate 필수).
    반환: 인식된 텍스트 하나. 무음/인식 실패 시 빈 문자열(예외 아님, EC-01).
    """
```

- 모델 로드: `WhisperModel(ct2_model_path_or_repo, device="cpu", compute_type="int8", cpu_threads=2)`
  — `tests/tts_cpu_inference_test.py`가 쓰는 "2 vCPU 흉내" 조건과 동일하게 맞춘다.
- `.env`의 `HF_STT_MODEL_REPO`(기존 패턴, 원본 HF transformers 어댑터 repo)와는 별도로
  CTranslate2 변환본을 가리키는 새 env var가 필요함(이름은 팀 논의 — 위 Open Issue와 연결).
  두 포맷을 같은 변수로 섞으면 혼란스럽다.
- `.env` 로딩은 `orchestration.db.load_env()` 재사용 — 새 `python-dotenv` 의존성 추가 안 함
  (`tests/integration_issues_2026-08-18.md` 이슈 #3과 동일한 이유, 이미 `src/stt/infer.py`의
  기존 함수들에 적용 완료).

**제약**
- `requirements.txt`엔 이미 `faster-whisper==1.2.1` 포함(확인됨) — 배포 런타임에 새 패키지
  추가 불필요. 단 변환 작업 자체는 오프라인(로컬/Colab)에서 `ctranslate2` 별도 설치가 필요함
  (배포 런타임 의존성 아님, `requirements-main.txt`에도 넣을 필요 없음).
- PRD 8.2: "모델 반입 방식 — git 저장소에 가중치 직접 커밋 금지, HF Hub에서 앱 시작 시
  다운로드" — 변환 결과물도 이 규칙을 따라야 함.

## AC (Given-When-Then)

**AC-01 · CPU 전용 환경에서 로드 성공**
- GIVEN: `CUDA_VISIBLE_DEVICES=""`로 GPU를 숨긴 환경
- WHEN: `stt_transcribe(audio)`를 처음 호출
- THEN: 예외 없이 모델이 로드되고 텍스트가 반환됨

**AC-02 · 기존 GPU 버전과 정확도 비교**
- GIVEN: Fixed100 테스트셋(`ChefEar_test_fixed_100.csv` + `test_audio_100/`)
- WHEN: `stt_transcribe()`(CPU, int8)와 `_transcribe_audio()`(GPU, 4bit)를 동일 오디오 100개에
  각각 실행
- THEN: WER 비교표가 산출됨(합격선은 결과 확인 후 팀 논의 — Goal 참고)

**AC-03 · 응답시간 실측**
- GIVEN: 2vCPU 흉내 조건(`cpu_threads=2`)
- WHEN: 평균 길이 문장 하나를 인식
- THEN: 소요 시간이 기록되고 `results/stt/` 밑에 CSV로 저장됨(`tests/tts_cpu_inference_test.py`와
  동일한 산출물 패턴)

**AC-04 · 무음 입력 정직 처리**
- GIVEN: 무음 또는 0.3초 미만 오디오
- WHEN: `stt_transcribe()` 호출
- THEN: 예외 없이 빈 문자열 반환 — app.py가 이를 보고 "다시 말씀해주세요" 안내로 이어갈 수 있음
