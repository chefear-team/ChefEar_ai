# data/ — 데이터 작업 공간

## 이 폴더가 하는 일

STT/TTS 학습 데이터, 조리순서 실데이터, 의도분류 기준예문, 평가용 데이터를 담는다. 대용량
파일(`kss/`, `synthesized/`, `standard/*.csv`, `kadx_raw/*.csv`, `models/`)은 `.gitignore`에 의해
git 대상이 아니다 — 팀원 간 별도 공유(드라이브 등) 필요.

## 하위 폴더 상태 (확인: 2026-08-16)

| 폴더 | 상태 | 용도 |
|---|---|---|
| `standard/` | **실물 확보(각자 배포 완료, git 업로드 안 함)** | 요리명별_조리과정 60,282건 CSV — 서비스가 쓰는 조리순서 전량(실데이터). `load_data.py --csv`로 Supabase 적재. git-ignored |
| `kadx_raw/` | **실물 확보(각자 배포 완료, git 업로드 안 함)** | KADX 원본 CSV 4개(234,538건 시드: 재료·요리명·메타). git-ignored |
| `intent_examples/기준예문.csv` | **확보됨(99줄, 2026-08-25 기준 계속 보강 중)** | 의도별 예문 세트(조회/진행/재청취/긍정 등) — `intent_classifier.py`가 참조. 실사용 리포트로 "조회" 표현(존댓말/격식체/반말/조리시작 요청형)이 여러 차례 확장됨 |
| `kss/wavs/` | **전체 확보(12,854개, 개인 보유·팀 미배포) + HF Hub 업로드 완료(`kimseunguk/recipe-kss-vits`). 로컬엔 412개만 스테이징** | TTS·STT 학습 원본 음성(공개 데이터셋, CC BY-NC-SA 4.0). git-ignored |
| `synthesized/` | **비어있음** | Qwen3-TTS가 만들 합성음(STT 학습용 페어) — TTS 파인튜닝이 먼저 끝나야 채워짐. git-ignored |
| `evaluation_scripts/stt/` | **확보됨** | `ChefEar_test_fixed_100.csv` + `test_audio_100/`(mp3 100개) — STT WER 실측용 검증셋 |
| `mos_participants/` | 비어있음(.gitkeep) | TTS 청취평가(MOS) 참여자 기록(5명 이상), 학습용 아님 |
| `consent/` | **확보됨** | `kss_license_check.md` — KSS 라이선스(CC BY-NC-SA 4.0, 비상업) 확인 기록. 팀원 동의서는 불필요(본인 목소리 미사용) |

## 진행 방법

- `standard/`, `kadx_raw/`는 팀원 각자 배포받아 실물 확보 완료. 대용량(수십MB) CSV라 git엔 절대
  올리지 않음(`.gitignore`) — 드라이브 등에서 받아 로컬에 두고 `load_data.py --csv`로 Supabase에
  직접 적재
- `kss/wavs/`는 전체 12,854개를 팀장(김승욱)이 개인 보유 + HF Hub(`kimseunguk/recipe-kss-vits`)에
  업로드까지 마친 상태. 로컬 스테이징분(412개)만 git-ignored로 두고 있고, 나머지는 아직 팀 공유 전 —
  필요하면 위 HF repo에서 받거나 팀장에게 요청. 해당 repo README에 KSS 라이선스(CC BY-NC-SA 4.0,
  비상업) 출처·고지 문구 반영 완료(`data/consent/kss_license_check.md` 참고)
- `synthesized/`는 [../src/tts/README.md](../src/tts/README.md)의 파인튜닝이 끝나야 생성 가능,
  그 산출물을 [../src/stt/README.md](../src/stt/README.md)가 기다리는 중
- `evaluation_scripts/stt/`, `intent_examples/기준예문.csv`, `consent/`는 이미 확보됐으므로 바로 사용
  가능 — `.gitignore` 대상(대용량 원본 CSV)이 아니므로 git에 커밋해야 함

## 관련 문서

`docs/ChefEar_팀_진행_가이드_v2.md` 2장 디렉토리 구조.
