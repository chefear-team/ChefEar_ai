# Open Issues / 결정 안 된 것들

가이드(`ChefEar_팀_진행_가이드_v2.md`) 기준으로, 착수 초반 반드시 실측/확정해야 할 항목.

항목별로 상태·담당·비고를 구분해 적었습니다 (표 형식은 옆으로 길어 편집하기 어려워 목록으로 변경).

## 1. Qwen3-TTS 1.7B 파인튜닝 — 노트북(RTX 4060 8GB)/데스크탑(RTX 5070 12GB) OOM 없이 완주 가능한지
- 상태: **해결**
- 담당: 김승욱
- 비고: Colab A100에서 QLoRA로 checkpoint-epoch-8까지 완주, merge 후 HF Hub(`kimseunguk/qwen3-tts-kss-finetuned`) 업로드 완료

## 2. Qwen3-TTS 추론 배포 방식 — CPU(HF Spaces Basic) → **GPU 기반으로 방향 전환**
- 상태: **배포 방향 결정됨(2026-08-19)** — CPU는 목표(5초) 안에 못 들어와서 포기, 전부 GPU 기반으로 간다
- 담당: 홍민하 / 김승욱
- 비고: **1차 방안: Tailscale + 로컬 데스크탑(RTX 5070) 상시 노출로 확정.** 2차/대안 방안으로
  HF Spaces 배포 + 유료 GPU API 호출도 검토됐으나 1차는 아니고 백업. ⚠️ `AGENTS.md`
  "기술 스택" 절에는 아직 `Hugging Face Spaces(CPU Basic, 무료)`가 배포 대상으로 명시돼
  있어 이 결정과 어긋난다 — `AGENTS.md`가 지도 강사 가이드 요건과 연결된 문서라 CPU Basic
  무료 배포가 단순 기술 선택이 아니라 과제 요건일 수도 있음, `AGENTS.md`/팀 가이드 문서도
  같이 갱신할지 팀 확인 필요.
  아래는 GPU 전환 결정 전까지 쌓인 CPU/GPU 실측 이력(참고용으로 남김):
  CPU: 2026-08-17 구 code path 197.48초 → 2026-08-19 공식 스크립트(`tests/tts_cpu_inference_test.py`)
  재측정 전체 평균 26.11초, `results/tts/cpu_inference_test.csv`. GPU(RTX 5070): 4문장
  (eager→SDPA→SDPA+compile 6.34→5.48→5.21초) 이후 문장이 5개(가장 긴 양념 문장 98자 추가)·
  `MAX_NEW_TOKENS` 250→197로 변경된 버전으로 재측정하니 SDPA+`torch.compile(dynamic=True)`
  전체 평균 8.75초로 다시 악화(긴 문장 하나가 평균 20.1초). `results/tts/gpu_inference_test_20260819.csv`
  (최신값). `flash-attn`은 이 환경(WSL/torch 2.13+cu130/`sm_120`)에서 설치 불가 재확인(nvcc
  없어 소스 빌드도 불가, 두 번 실측 동일 결론). 기존 `torch.compile()`(dynamic 미지정)은
  재컴파일로 비일관적이었으나 `dynamic=True`로는 안정적으로 개선됨(4문장 기준 5.48→5.21초).
  98자 문장이 `MAX_NEW_TOKENS=197`에서 8회 중 5회 잘리는 것도 확인(250이면 여유 있음) —
  기존 이슈 #6(`tests/integration_issues_2026-08-18.md`)과 같은 유형, 문장 늘릴 땐 상한도
  같이 검토할 것.

## 3. STT 학습 스택(transformers/peft/accelerate/bitsandbytes) 버전
- 상태: 학습용은 확정(`requirements-stt.txt`)
- 담당: 하주성
- 비고: 가이드 6.2

## 4. [2026-08-16] STT+TTS 통합 실행환경 버전 충돌
- 상태: **해결**
- 담당: 하주성
- 비고: `qwen-tts==0.1.1`이 `transformers==4.57.3`을 요구해서 `requirements-stt.txt`의 기존 고정 버전(`4.46.3`)과 충돌(`ImportError: cannot import name 'ALL_ATTENTION_FUNCTIONS'`)했던 건 — `transformers`를 낮추지 않고 `4.57.3`으로 올리는 쪽으로 `requirements-stt.txt` 자체를 갱신해서 해결(Whisper+PEFT+bitsandbytes 로딩도 최신 transformers에서 문제없이 동작 확인). 이 조합(`transformers==4.57.3` + `qwen-tts==0.1.1`)으로 `tests/tts_stt_roundtrip_test.py`를 2026-08-17 실제로 통과 실행해서 결과까지 확보함(`results/tts/roundtrip_cer.csv`, 상세: `tests/README.md`)

## 5. TTS 학습 LoRA 저장소 버전 (instavar/qwen3-tts-lora-finetuning 등, 비공식)
- 상태: **해결**
- 담당: 김승욱
- 비고: 자체 QLoRA 스크립트(`train_qwen3_tts.py`)로 진행, 위 항목 참고

## 6. TTS 추론 저장소 버전
- 상태: **해결**
- 담당: 김승욱
- 비고: `qwen-tts==0.1.1` 패키지, `src/tts/infer.py` 참고. 위 통합환경 충돌 해결로 `transformers==4.57.3`과의 조합이 실측 검증됨 — 다만 이 버전 고정은 아직 `requirements-stt.txt`(STT 학습 환경)에만 반영돼 있고, TTS/배포가 쓰는 `requirements.txt`·`requirements-main.txt`에는 `qwen_tts`/`python-dotenv` 버전이 아직 없음(아래 참고)

## 7. [신규 2026-08-17] `src/tts/infer.py`·`src/stt/infer.py` 브랜치 간 불일치
- 상태: **미해결, 병합 전 정리 필요**
- 담당: 김승욱
- 비고: `main`(`fix/stt-dotenv`, `fix/tts-dotenv` PR)은 두 파일 모두 `python-dotenv`로 `.env`를 읽도록 바꿨는데, `requirements.txt`/`requirements-main.txt`(배포·TTS가 실제 쓰는 파일)엔 `python-dotenv`가 없어서 그대로면 HF Spaces 배포 시 `ModuleNotFoundError` 위험이 있음(`requirements-stt.txt`에만 추가됨). `seunguk` 브랜치의 `src/tts/infer.py`는 같은 문제를 `src/orchestration/db.py`의 의존성 없는 `load_env()` 재사용으로 우회 해결(이미 실측 검증됨, 아래 tests/README.md 참고) — 병합 시 어느 방식으로 통일할지 결정 필요. 또한 `main`의 `pipeline.py`는 재료대체 매칭 실패 시 `match_type`을 응답에 안 넣는데(`seunguk`은 시나리오 C 실측 중 발견해서 넣도록 수정함, `tests/integration_test.md` 참고), pytest 스위트에 이를 지키는 회귀 테스트가 없어 병합 시 조용히 빠질 위험 있음


| 항목 | 상태 | 담당 | 비고 |
|---|---|---|---|
| Qwen3-TTS 1.7B 파인튜닝 — 노트북(RTX 4060 8GB)/데스크탑(RTX 5070 12GB) OOM 없이 완주 가능한지 | **해결** | 김승욱 | Colab A100에서 QLoRA로 checkpoint-epoch-8까지 완주, merge 후 HF Hub(`kimseunguk/qwen3-tts-kss-finetuned`) 업로드 완료 |
| HF Spaces CPU Basic에서 Qwen3-TTS 추론이 목표 응답시간(5초) 이내인지 | **확인됨 — FAIL** (2026-08-17, 전체 평균 197.48초, 목표의 약 39.5배. `tests/cpu_inference_test_20260816_164450.csv`, 상세: `src/tts/README.md`) | 홍민하 | 가이드 9. 대안 결정 필요: ① Modal 등 GPU 플랫폼 ② Tailscale로 데스크탑 상시 노출 ③ Qwen3-TTS 0.6B로 축소 |
| STT 학습 스택(transformers/peft/accelerate/bitsandbytes) 버전 | 학습용은 확정(`requirements-stt.txt`) | 하주성 | 가이드 6.2 |
| **[2026-08-16] STT+TTS 통합 실행환경 버전 충돌** | **해결** | 하주성 | `qwen-tts==0.1.1`이 `transformers==4.57.3`을 요구해서 `requirements-stt.txt`의 기존 고정 버전(`4.46.3`)과 충돌(`ImportError: cannot import name 'ALL_ATTENTION_FUNCTIONS'`)했던 건 — `transformers`를 낮추지 않고 `4.57.3`으로 올리는 쪽으로 `requirements-stt.txt` 자체를 갱신해서 해결(Whisper+PEFT+bitsandbytes 로딩도 최신 transformers에서 문제없이 동작 확인). 이 조합(`transformers==4.57.3` + `qwen-tts==0.1.1`)으로 `tests/tts_stt_roundtrip_test.py`를 2026-08-17 실제로 통과 실행해서 결과까지 확보함(`results/tts/roundtrip_cer.csv`, 상세: `tests/README.md`) |
| TTS 학습 LoRA 저장소 버전 (instavar/qwen3-tts-lora-finetuning 등, 비공식) | **해결** | 김승욱 | 자체 QLoRA 스크립트(`train_qwen3_tts.py`)로 진행, 위 항목 참고 |
| TTS 추론 저장소 버전 | **해결** | 김승욱 | `qwen-tts==0.1.1` 패키지, `src/tts/infer.py` 참고. 위 통합환경 충돌 해결로 `transformers==4.57.3`과의 조합이 실측 검증됨 — 다만 이 버전 고정은 아직 `requirements-stt.txt`(STT 학습 환경)에만 반영돼 있고, TTS/배포가 쓰는 `requirements.txt`·`requirements-main.txt`에는 `qwen_tts`/`python-dotenv` 버전이 아직 없음(아래 참고) |
| **[2026-08-19] `src/stt/infer.py` 환경변수 의존성 정리** | **STT 해결 / TTS·orchestration 확인 필요** | 하주성 | STT의 `src/stt/infer.py`에서 `python-dotenv` 및 `load_dotenv()` 의존성을 제거함. `HF_STT_MODEL_REPO` 환경변수가 있으면 해당 값을 사용하고, 없으면 기본 Adapter(`leeony/chefear-stt-large-v3-turbo`)를 사용하도록 수정하여 `.env` 없이도 실행 가능. STT의 `python-dotenv` 관련 배포 오류 위험은 해결됨. `src/tts/infer.py`와 `src/orchestration/db.py`의 환경변수 처리 방식 및 실제 HF Spaces 실행 환경은 별도 확인 필요 |


