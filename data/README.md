# data/ — 데이터

| 경로 | git | 용도 |
|---|---|---|
| `intent_examples/기준예문.csv` | 포함 | 의도분류 기준 예문 110개(조회/등록/진행/재청취/이전/감탄사/긍정). `intent_classifier.py`가 임베딩해 비교 |
| `evaluation_scripts/stt/ChefEar_test_fixed_100.csv` + `test_audio_100/` | 포함 | STT Fixed100 검증셋(문장 100개 + mp3 100개). `src/stt/evaluate_fixed100.py`가 사용 |
| `mos_participants/` | 제외 | TTS 블라인드 MOS 참여자별 원자료(13명). 집계는 `results/tts/mos/MOS_청취평가.html` |
| `consent/kss_license_check.md` | 포함 | KSS 라이선스(CC BY-NC-SA 4.0) 확인 기록. 팀원 목소리 미사용이라 동의서 불필요 |
| `admin_voiceprints.json` | 제외 | 관리자 화자검증 성문(음성 생체 임베딩). 배포 환경마다 `/enroll`로 등록 |
| `kss/` | 제외 | TTS·STT 학습 원본 음성 12,854개. HF `kimseunguk/recipe-kss-vits` |
| `standard/`, `kadx_raw/` | 제외 | 만개의레시피 원본 CSV(234,538건 시드, 고유 요리명 60,282건). 09-01 이후 서비스는 쓰지 않음 |
| `synthesized/` | 제외 | STT 학습용 합성 음성 |

서비스가 실제로 읽는 500건 레시피 CSV는 `docs/한국_가정식_500개_COOKING_STEPS_규칙기반생성_v2.csv`에 있고 `src/orchestration/load_500_recipes.py`로 적재한다.
