# src/ — 소스 맵

기준일: 2026-09-10 (최종본)

| 폴더 | 담당 | 역할 |
|---|---|---|
| `app.py` | 김승욱 | 서비스 엔트리포인트. 세션 초기화 → 로그인/게이트 → 화면 렌더 → `listen()`으로 발화 수신 → `process_utterance()` 디스패치 |
| `orchestration/` | 김승욱·홍민하 | 의도분류, 레시피 검색·단계 전이, 등록·수정·삭제, 계정, GPU 워커 풀, 용어 사전, 화자검증, DB 클라이언트, 데이터 적재 스크립트 |
| `llm/` | 김승욱 | 로컬 LLM(EXAONE-3.5-2.4B) 로드·JSON 생성 |
| `stt/` | 김승욱·하주성 | 배포용 STT 추론(faster-whisper), CTranslate2 변환, Fixed100 재평가 스크립트 |
| `tts/` | 홍민하·김승욱 | 배포용 TTS 추론(Qwen3-TTS), TTS 직전 발음 보정, 참조 음성 |
| `ui/` | 홍민하·김승욱 | Streamlit 화면 컴포넌트: 세션, 음성 입출력, 디스패처, 레시피 뷰, 화면 모듈 |

## 실행 흐름

```
app.py::main()
  ├─ init_state() / 로그인 확인 / ACCESS_GATE_TOKEN 확인
  ├─ SCREENS[screen]()          화면 본문을 st.empty() 슬롯 하나에 렌더 (잔상 방지)
  ├─ listen()                   상시 마이크(WebRTC) → VAD 세그먼트 → gpu_worker_pool.submit_stt()
  └─ process_utterance(text)    홈/관리자/등록 단축어 → 조리 중 여부 → LLM 요리명 추정 → 의도분류 → 라우팅
         └─ speak(text)         resolve_for_tts() → submit_tts() → 캐시 → 자동 재생
```

`src/ui/`는 `src`가 `sys.path`에 있어 `ui.dispatch`처럼 import되고, 저장소 루트의 `ui/`(`theme.py`, `mic_vad.py`)는 별도로 `sys.path`에 얹혀 `from theme import ...`로 쓴다. 이름만 같고 다른 경로다.

## 요리명 추출

`orchestration/entity_extract_llm.py`(로컬 LLM이 자유발화에서 요리명 후보 추출) → `orchestration/recipe_search.py::extract_dish_name()`(DB 실존 요리명으로 완전일치→부분일치→편집거리 보정 + 공백 무시·반복 축약 안전망). LLM 결과는 후보일 뿐이고 최종 매칭은 항상 DB 기준이다.

각 폴더의 README에 함수 목록과 설계 근거가 있다.
