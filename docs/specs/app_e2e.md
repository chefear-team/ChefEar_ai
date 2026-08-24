# Spec — `src/app.py` 종단간 통합 (마이크 → STT → 오케스트레이션 → TTS)

관련: `tests/integration_issues_2026-08-18.md` 이슈 #4, `docs/ChefEar_PRD_SDD_v0.8.md` 3.3/6장/FR-16,
`ui/README.md`, `src/README.md`, Spec `docs/specs/stt_deploy.md`.

## Why

- **페르소나**: 요리 경험이 거의 없고 칼질·반죽 등으로 손을 쓰기 어려운 사용자(셰프이어 ICP)
- **상황**: `orchestration.pipeline.handle_utterance()`와 `tts.infer.tts_synthesize()`는 이제
  완성됐고 실측으로 검증됐다(2026-08-19 재검증: 오케스트레이션 31/31 PASS, TTS↔STT 라운드트립
  5/5 CER 0.0000). `ui/`(최상위, 별도 폴더)에 mock 데이터 기반 화면 프로토타입도 11개 다 있다.
  하지만 `src/app.py`가 완전히 비어있어(0줄) 실제로 마이크에 대고 말해서 확인하는 진짜
  종단간(end-to-end) 테스트가 물리적으로 불가능하다.
- **문제**:
  1. PRD 6장 AC-14("화면 터치 없이 음성만으로 전체 조리 과정 진행")를 화면 단위로 검증할
     방법이 없음 — 지금까지는 `handle_utterance()` 직접 호출로 우회 검증만 했음
     (`tests/integration_test.md`)
  2. HF Spaces에 배포할 실제 엔트리포인트가 없어 데모/발표 자체가 불가능
  3. `ui/`의 목업이 `ui/mock_data.py` 가짜 데이터만 쓰고 있어 실제 DB/모델과 분리돼 있음
- **측정 지표**: PRD 6장 AC-14(중단 없이 마지막 단계까지 완료), 3.2 KPI(반복 테스트 성공률,
  실측 후 확정)

## Goal

- **해결 목표**: 마이크 입력 → STT → `handle_utterance()` → TTS 재생까지 한 화면 루프로 엮은
  `src/app.py`를 작성해서, 사람이 실제로 마이크에 대고 말해 `tests/integration_test.md`
  시나리오 A~D를 화면에서 재현할 수 있게 한다.
- **성공 기준**:
  1. `streamlit run src/app.py`로 로컬 실행 시 마이크 녹음 → 텍스트 → 응답 → 음성 재생까지
     예외 없이 1회전 완료
  2. `tests/integration_test.md` 시나리오 A(조회/진행)를 화면에서 사람이 직접 말해서/눌러서
     재현 가능(자동화 테스트가 아니라 사람이 확인하는 통합테스트 문서와 동일한 성격)
  3. FR-16(음성 인식/의도분류 실패 시 수동 [이전][다시][다음] Fallback) 동작 확인
- **Out of Scope**:
  - 화면 디자인 자체 개선(PRD 3.3 "핵심 기능 완료 후 여유 시간에 다듬는다" — `ui/`의 기존
    구조를 그대로 재사용, 새로 디자인하지 않음)
  - HF Spaces 실제 배포(별도 작업 — 이 Spec은 로컬에서 도는 `app.py` 완성까지)
  - STT/TTS 자체 성능·정확도 개선(각각 `docs/specs/stt_deploy.md`와 TTS 트랙에서 별도 진행)
  - "응"(긍정) 의도를 `classify_intent()`의 정식 분류 대상에 추가하는 것 — 의도적으로 제외돼
    있음(`tests/integration_test.md` 기록) — `app.py`가 아래 EC-02처럼 화면 상태 기반의 별도
    규칙으로 처리

## What

**Happy Path**
1. 시작 화면 — 자유발화 유도(FR-01), 마이크 입력 대기
2. STT(`stt.infer.stt_transcribe()` — `docs/specs/stt_deploy.md` 완료 전이면 임시로 기존 GPU
   경로 `_transcribe_audio()`로 로컬 개발 진행 가능) → 텍스트
3. `handle_utterance(session, text, ...)` 호출 → intent별 응답
4. 응답 텍스트를 `tts_synthesize()`로 음성 변환 → `st.audio()`로 재생
5. 화면에 현재 단계·재료(대체분 별도 표시)·최근 대화를 텍스트로 병행 표시
   (FR-13, `ui/streamlit_screens/` 재사용)
6. 사용자가 "다음/다시/이전" 등 발화 → 2~5 반복

**Edge Cases** (최소 5개 + 처리 방식)

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | STT/의도분류 실패("미분류") | FR-16 수동 [이전][다시][다음] 버튼 노출, `result["fallback_message"]`를 화면+TTS 양쪽으로 안내 |
| EC-02 | "레시피 확인" 화면에서 "응"(긍정) 발화 | `classify_intent()`가 처리 안 함(Out of Scope 참고) — `app.py`가 해당 화면 상태에서만 문자열 매칭으로 우회 처리 후 1단계로 진행 |
| EC-03 | 재료대체 매칭 완전 실패(시나리오 C) | `match_type == "none"` 응답을 화면에 정직하게 표시 + TTS로도 동일 문구 안내(1.5 원칙) |
| EC-04 | 마이크 권한 거부/오디오 입력 없음 | 화면에 안내 메시지 표시, FR-16 수동 버튼으로 계속 진행 가능하게 |
| EC-05 | TTS 합성 실패/예외(`tts_synthesize()`가 `ValueError` 던지는 경우 등) | 화면 텍스트 표시는 그대로 유지하고, 음성 재생만 실패했다는 걸 조용히 삼키지 않고 화면/로그에 표시 |

## How

**기존 자산 재사용 (새로 안 만듦)**
- `orchestration.pipeline.handle_utterance()` — 라우팅(이미 완성, 31/31 PASS)
- `tts.infer.tts_synthesize()` — 음성 합성(이미 완성, 라운드트립 CER 0.0000)
- `stt.infer.stt_transcribe()`(`docs/specs/stt_deploy.md`) 또는 개발 중 임시로 `_transcribe_audio()`
- `ui/streamlit_screens/` 11개 화면 컴포넌트, `ui/theme.py`, `ui/nav.py`의 화면 전환 구조 —
  `src/app.py`가 그대로 가져다 쓰되 `ui/mock_data.py` 대신 실제 함수 호출로 교체

**세션 상태**
- `st.session_state`에 `handle_utterance()`가 쓰는 `session` dict(`current_recipe_id`,
  `step_number`, `previous_recipe_id`, `registration` 등)를 그대로 보관 — 새 세션 구조를
  만들지 않고 `orchestration.pipeline`의 기존 계약을 그대로 따른다.

**마이크 입력**
- Streamlit 마이크 입력 컴포넌트 사용(정확한 API명은 설치된 `streamlit==1.61.1` 기준으로
  착수 시 직접 확인 필요 — **Open Issue**, 버전에 따라 `st.audio_input` 등 이름이 다를 수 있음)

**클라이언트**
- `orchestration.db.get_client()` 재사용 — 자격증명 없으면 mock 자동 폴백(이미 구현된 안전장치
  그대로 사용, 새로 만들지 않음)

**제약**
- `src/stt/infer.py`는 HF Spaces 배포 환경에서 `python-dotenv` 없이 로드되도록 이미 수정됨
  (`tests/integration_issues_2026-08-18.md` 이슈 #3 완료, 2026-08-19) — `app.py`가 이 모듈을
  import해도 배포 환경에서 안 죽음
- PRD 5장 "5초 이내" 응답 목표는 이 Spec의 완료 기준이 아니라 별도 성능 측정 대상(STT/TTS
  각각의 실측치를 합산해서 추후 확인 — `docs/specs/stt_deploy.md` AC-03, TTS CPU 벤치마크 참고)

## AC (Given-When-Then)

**AC-01 · 시나리오 A 화면 재현(조회+진행)**
- GIVEN: `streamlit run src/app.py` 로컬 실행, 실제 Supabase 연결
- WHEN: 마이크(또는 수동 버튼)로 "된장찌개 어떻게 만들어?" → "다음" → "다시" → "이전" 순서로 조작
- THEN: `tests/integration_test.md` 시나리오 A와 동일한 단계 전이가 화면에 표시되고 음성이 재생됨

**AC-02 · 시나리오 B 화면 재현(재료대체+취소)**
- GIVEN: AC-01 이어서 진행 중
- WHEN: "바지락 넣어도 돼?" → "취소해줘"
- THEN: 화면 레시피가 바지락된장찌개로 바뀌었다가 취소 시 된장찌개로 복원됨(재료 칩 표시 포함, FR-13)

**AC-03 · 의도분류 실패 시 Fallback**
- GIVEN: 애매한 발화(임계값 미만) 또는 마이크 입력 없음
- WHEN: 발화가 "미분류"로 분류되거나 STT 결과가 빈 문자열
- THEN: [이전][다시][다음] 버튼이 항상 화면에 노출돼 있어 눌러서 진행 가능(FR-16)

**AC-04 · 재료대체 매칭 실패 정직 안내**
- GIVEN: 시나리오 C(문어+성게 등 매칭 불가 조합)
- WHEN: 재료대체 발화
- THEN: 화면과 음성 모두 "레시피가 없다"는 정직한 문구를 보여줌(그럴싸하게 지어내지 않음, 1.5 원칙)
