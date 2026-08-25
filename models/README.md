# models/ — 로컬 학습 산출물 스테이징

## 이 폴더가 하는 일

STT/TTS 파인튜닝 체크포인트를 로컬에 임시로 두는 곳. **git 대상 아님**(`.gitignore`). 실제 배포는
이 폴더를 직접 읽지 않고 HF Hub(`.env`의 `HF_STT_MODEL_REPO`/`HF_TTS_MODEL_REPO`)에서 가중치를
다운로드해서 쓴다 — 그러니 여기 체크포인트를 쌓아두는 건 "학습 중 로컬 확인용"이지 배포 경로가 아니다.

## 현재 상태 (확인: 2026-08-16)

| 폴더 | 상태 |
|---|---|
| `stt_finetuned/` | `.gitkeep`만 있음, 로컬 체크포인트 없음. HF Hub에 두 repo가 역할을 나눠서 대신한다 — 어댑터 원본은 `leeony/chefear-stt-large-v3-turbo`(`HF_STT_MODEL_REPO`), 실제 배포(`load_ct2_model()`이 쓰는 실시간 경로)는 CTranslate2 int8로 변환된 `kimseunguk/chefear-stt-ct2-int8`(`HF_STT_CT2_REPO`, private — 로딩 시 `HF_TOKEN` 필요, 2026-08-25 추가)이 담당한다([src/stt/infer.py](../src/stt/README.md) 참고) |
| `tts_finetuned/` | 로컬은 `.gitkeep`만 있어 비어있지만, **파인튜닝 자체는 완료**돼 HF Hub `kimseunguk/qwen3-tts-kss-finetuned`(private)에 업로드까지 끝남([src/tts/README.md](../src/tts/README.md) 참고) — `src/tts/infer.py`의 `tts_synthesize()`가 이 HF Hub repo를 직접 로드해서 쓰므로, 로컬 폴더가 비어있어도 서비스 코드는 정상 동작함 |

`tests/tts_cpu_inference_test.py`는 `tts_finetuned/` 안에서 가장 최근 수정된 체크포인트 폴더를 자동으로
찾아 쓰고, 없으면 사전학습 베이스 모델로 폴백하도록 이미 짜여 있다.

## 진행 방법

- 학습이 끝나면 체크포인트를 `stt_finetuned/`, `tts_finetuned/` 아래 하위 폴더로 저장
- 검증이 끝나면 HF Hub 저장소에 업로드하고 `.env`의 `HF_STT_MODEL_REPO`/`HF_TTS_MODEL_REPO`에 repo id 기록
  (이게 실제 배포가 참조하는 값)

## 관련 문서

`docs/ChefEar_팀_진행_가이드_v2.md` 2장(`models/` 역할), `.env.example.local`(HF repo 환경변수).
