# ChefEar 음성 파이프라인 전체 점검 — 2026-08-26 (프리징 전날)

## 범위

`app.py` 진입점부터 `ui/voice_io.py`(WebRTC/STT) → `orchestration/intent_classifier.py`(임베딩) →
`orchestration/pipeline.py`(라우팅) → `orchestration/recipe_search.py`/`db.py`(DB) →
`ui/screens/cooking.py`, `ui/screens/register.py`(전체 화면) 까지 소스 전체를 직접 읽고,
라이브 서버(`run_local.sh`, GPU 데스크탑) 실제 로그로 교차검증함. 브랜치: `seunguk`
(uncommitted 변경 다수 포함, `git diff --stat` 995줄 추가/136줄 삭제).

## A. 오늘 확정 수정 (라이브 반영됨)

| 항목 | 파일 | 상태 |
|---|---|---|
| 등록 시 dish_name에 trailing 문장부호(`.`) 그대로 저장되던 버그 | `orchestration/registration.py` | 수정 + pytest 23개 통과 + 라이브 재시작 반영 |
| STT 세그먼트 신뢰도(`avg_logprob`/`no_speech_prob`) 진단 로그 추가 | `src/stt/infer.py` | 로깅만 추가(동작 변경 없음), 라이브 반영, 데이터 수집 중 |

## B. 검증 완료 — 실제로 고쳐진 것 확인됨

- **"Queue overflow" 경고**: 과거엔 TTS 합성 대기·`process_utterance()`의 미분류 분기·
  `register_intro`/`no_match` 등 여러 화면에서 `st.rerun()` 없이 종료되던 지점들이 각각
  원인이었음. 오늘 읽은 전체 화면 코드에서 **모든 무시/미분류 분기가 예외 없이
  `st.rerun()`으로 마이크 드레인 루프를 유지**하도록 일관되게 처리돼 있음을 직접 확인.
  라이브 로그(총 1300줄+) 전수조사 결과 "Queue overflow" **0건**.
- **"0.4초 로딩바"**: 버그 아님. `_drain_mic_while()`의 `_SHOW_DELAY_S=0.4`는 표시 임계값일
  뿐, 실제 처리시간은 TTS 합성(GPU 기준 1.8~6.6초 실측) + STT/임베딩/DB 순차 호출이 원인 —
  거의 매 턴이 0.4초를 넘기는 게 정상.

## C. 되돌린 것

- **재료대체 기준예문 3줄**: git diff상 삭제로 보여서 복구했었으나, **팀의 의도적 결정**이라는
  피드백을 받고 즉시 원상복구함(diff가 원래 상태와 동일함을 `git diff --stat`으로 재확인).
  → **건드리지 않음.**

## D. 아직 열려있는 문제 (설계 판단 필요, 오늘 밤 성급히 손대지 않는 게 나음)

1. **`pipeline.py::handle_utterance()`의 dish_name 우선순위**: 로컬 LLM(`entity_extract_llm.py`)의
   비검증 추측이 `extract_dish_name()`의 자모분해 편집거리 보정보다 항상 우선함 — STT가
   "된장찌개"를 "된장찌장찌개"로 오인식하면 보정 기회 자체가 없음. **다만 이 정확한
   fallback을 팀이 이미 시도했다가 "초코민트 된장찌개"→"토마토된장찌개" 오매칭 회귀로
   되돌린 이력이 코드 주석에 있음** — 재도입하면 같은 회귀 재현 위험. 단순 버그 수정이
   아니라 정밀도/재현율 트레이드오프 설계 결정 필요.
2. **동시 다수 사용자 시 지연**: `_GPU_LOCK`(voice_io.py) 하나로 STT/임베딩/로컬LLM/TTS
   전부를 직렬화 — 여러 명이 동시에 말하면 GPU 하나를 줄서서 기다림. "1 GPU 데스크탑
   상시 노출" 배포 구조 자체의 한계(팀 기결정 사항, 인프라 변경 없인 해결 불가) — 알려진
   한계로 문서화 권장.

## E. 프리징 전 권장 순서

1. 서버 재시작으로 A 항목 라이브 반영(완료됨, pid 확인 필요시 재확인)
2. 핵심 플로우 스모크테스트 1회: 조회 → 진행/다시/이전 → 취소 → 다음 → 완료
3. D-1, D-2는 "알려진 한계"로 문서화만 하고 코드 변경은 보류 — 남은 시간에 새 리스크
   추가하는 것보다 지금 상태를 안정적으로 굳히는 쪽이 낫다고 판단됨
