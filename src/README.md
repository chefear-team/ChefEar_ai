# src/ — 소스 맵

기준일: 2026-10-20 (서버리스 리뉴얼 반영). Streamlit 앱(`app.py`, `ui/`)은 리뉴얼에서 제거했고, 서비스 진입점은 `server/chefear_api/`(API)와 `web/`(웹)이다.

| 폴더 | 담당 | 역할 |
|---|---|---|
| `orchestration/` | 김승욱·홍민하 | 의도분류, 레시피 검색·단계 전이, 등록·수정·삭제, 용어 사전, DB 클라이언트, 데이터 적재 스크립트. API 서버가 그대로 가져다 쓴다 |
| `llm/` | 김승욱 | 로컬 LLM(EXAONE-3.5-2.4B) 로드·JSON 생성. 서비스 경로에서는 호출하지 않는다(정확도 A/B용으로 남김) |
| `stt/` | 김승욱·하주성 | 배포용 STT 추론(faster-whisper), 후처리(`postprocess.py`), CTranslate2 변환, Fixed100 재평가 스크립트 |
| `tts/` | 홍민하·김승욱 | 배포용 TTS 추론(Qwen3-TTS), TTS 직전 발음 보정, 참조 음성 |

## 실행 흐름

```
web/ (브라우저)  --토큰 + 발화 WAV 또는 글자-->  server/chefear_api (Modal CPU)
  ├─ guard.py                 입력 정리·길이 제한·공격 문구 차단
  ├─ service.py               대화 상태 기계(상태는 Supabase sessions 표에 저장)
  │    ├─ inference/ Stt      발화 WAV → 글자 (Modal GPU, src/stt 후처리 공유)
  │    └─ orchestration/      요리명 매칭 → 의도분류 → DB 조회 → 다음 화면
  └─ speech.py / audio.py     응답 문장의 지문으로 미리 만든 mp3 찾기, 없으면 inference/ Tts (Modal GPU)
```

`orchestration/`, `stt/`, `tts/`는 `src/`를 `sys.path`에 올려 import한다(`PYTHONPATH=server:src`). 구조 전체는 `docs/specs/renewal_serverless.md`와 `renewal/API_CONTRACT.md`.

## 요리명 추출

서비스 경로에서는 `orchestration/recipe_search.py::extract_dish_name()`이 DB 실존 요리명으로 완전일치→부분일치→편집거리 보정 + 공백 무시·반복 축약 안전망을 적용한다. 리뉴얼 전에는 로컬 LLM(`orchestration/entity_extract_llm.py`)이 자유발화에서 요리명 후보를 먼저 뽑았으나 서비스에서 뺐다(정확도 비교는 아직 안 했다). 최종 매칭은 항상 DB 기준이다.

각 폴더의 README에 함수 목록과 설계 근거가 있다.
