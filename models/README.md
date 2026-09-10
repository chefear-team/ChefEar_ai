# models/ — 로컬 모델 스테이징 (git 미추적)

배포는 이 폴더가 아니라 HF Hub에서 가중치를 내려받아 쓴다. 여기는 로컬 확인용 체크포인트와 CPU 화자검증 모델을 두는 곳이다.

| 폴더 | 내용 | 배포가 읽는 위치 |
|---|---|---|
| `stt_finetuned/ct2_int8/` | CTranslate2 int8 변환본(있으면 `HF_STT_CT2_REPO` 대신 사용) | HF `kimseunguk/chefear-stt-ct2-int8` (`HF_STT_CT2_REPO`) |
| `stt_finetuned/` | 학습 어댑터 로컬 사본 | HF `leeony/chefear-stt-large-v3-turbo` (`HF_STT_MODEL_REPO`) |
| `tts_finetuned/` | TTS 체크포인트 로컬 사본 | HF `kimseunguk/qwen3-tts-kss-finetuned` (`HF_TTS_MODEL_REPO`) |
| `spkrec-ecapa-voxceleb/` | 관리자 화자검증 ECAPA-TDNN(speechbrain), CPU 실행 | 로컬(이 폴더) |

세 HF 저장소는 private라 `HF_TOKEN`이 필요하다. 환경변수 목록은 `.env.example`.
