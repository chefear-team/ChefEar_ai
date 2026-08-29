# tests/ — 테스트 작업 공간

## 이 폴더가 하는 일

두 가지 서로 다른 성격의 테스트가 섞여 있다.

1. **pytest 유닛테스트** — `src/orchestration/`의 로직을 `FakeSupabaseClient`로 격리해서 검증
2. **수동 통합테스트 문서/벤치마크 스크립트** — pytest가 아니라 사람이 직접 실행/체크하는 형태로
   의도된 것(`docs/ChefEar_팀_진행_가이드_v2.md` 106번째 줄에 명시)

## 파일별 상태 (확인: 2026-08-28)

| 파일 | 상태 | 성격 |
|---|---|---|
| `conftest.py` | 완성 | `src/`를 `sys.path`에 등록 |
| `fake_supabase.py` | 완성 | `orchestration/mock_client.py`와 동일 엔진(그걸 그대로 가져다 씀) |
| `test_pipeline.py` | 완성 | AC-07~09, AC-12/13 (재료대체 관련 케이스는 기능 제거와 함께 삭제됨) |
| `test_intent_classifier.py` | 완성 | AC-01/02/10, EC-01~05. 재료대체/취소 의도 케이스는 2026-08-27 제거 |
| `test_recipe_search.py` | 완성 | AC-03~05, EC-06~09, EC-18~20. `approved` 필터링 케이스 포함 |
| `test_registration.py` | 완성 | AC-06, EC-15~17. `save_recipe()`가 `approved='N'`으로 저장하는지 포함 |
| `test_mock_client.py` | 완성 | `db.get_client()` mock 자동 폴백 확인 |
| `test_tts_pronunciation.py` | 완성 | `src/tts/pronunciation.py`의 발음 보정 회귀테스트. `torch`/`qwen_tts` 불필요 — 순수 문자열 치환이라 pytest 전체 스위트에 GPU 의존성 안 늘림 |
| `test_llm_infer.py` | 완성 | `src/llm/infer.py`의 `generate_json()` mock 기반 유닛테스트 — GPU·실제 모델 로딩 불필요 |
| `test_entity_extract_llm.py` | 완성 | `src/orchestration/entity_extract_llm.py`의 `extract_dish_name_llm()` mock 기반 유닛테스트 |
| `test_speaker_verify.py` | **신규(2026-08-28)** | 관리자 화자검증(ECAPA-TDNN) — `embed()`/`verify()`/`enroll()` mock 기반 유닛테스트 + 관리자 페이지 진입 발화 트리거(`_is_admin_trigger`) 매칭 테스트. GPU 불필요(임베딩 목킹) |
| `test_ui.py` | pytest 대상 아님 | STT→LLM(요리명 추출)→Supabase 조회→TTS 단계를 화면에 그대로 보여주는 수동 확인용 Streamlit 앱(`streamlit run tests/test_ui.py` 또는 `../run_local.sh tests/test_ui.py`). `if __name__ == "__main__":` 가드 안에 있어서 pytest가 모듈로 import해도 아무것도 실행 안 됨(수집되는 `test_` 함수 없음) |
| `integration_scenario_test.py` | pytest 대상 아님, `handle_utterance()` 직접 호출 진단 스크립트 | 실제 DB 연결(`allow_mock=False`) 필요, GPU 불필요. `integration_test.md`(아래)의 시나리오를 코드로 순차 실행 |

`test_substitution.py`/`test_identity.py`는 재료대체·익명 쿠키 개인화 기능 삭제와 함께(2026-08-27) 파일째 제거됐다.
| `integration_test.md` | **작성 완료(137줄), AC-14/15 전체 PASS(2026-08-16)** | AC-14~16(GWT) 기준 **수동** 시나리오 체크리스트(시나리오 A~D + AC-15 반복테스트 + AC-16 자리) — `handle_utterance()`를 파이썬에서 직접 호출하는 방식, `app.py`가 없어도 지금 바로 실행 가능. AC-16(TTS)만 아직 블로킹 표시 |
| `integration_scenario_test.py` | 작성됨, **31/31 PASS(2026-08-16)** | 위 `integration_test.md`의 시나리오 A~D + AC-15를 코드로 그대로 옮겨 순차 실행하는 진단 스크립트. 실제 DB 연결(`allow_mock=False`) 필요, GPU 불필요. 실행 결과(PASS/FAIL)를 보고 `integration_test.md` 체크박스를 채우는 용도 — pytest 아님, assert로 죽지 않고 끝까지 돌고 마지막에 요약 출력. ⚠️ 이 파일은 아직 `seunguk` 브랜치에만 있고 `main`엔 없음 — 병합 필요 |
| `tts_cpu_inference_test.py` | 버그 2개 수정 후 Colab(2 vCPU)에서 정식 실행 완료(2026-08-17) | Qwen3-TTS CPU 추론 속도 실측(HF Spaces CPU Basic 2 vCPU 흉내), 5초 목표 PASS/FAIL 판정. `qwen_tts` 패키지 필요. **결과: 3문장 전부 FAIL, 전체 평균 197.48초(목표의 약 39.5배)** — CSV는 `cpu_inference_test_20260816_164450.csv`, 상세는 `../src/tts/README.md` 참고 |
| `tts_stt_roundtrip_test.py` | **13에포크+voice-clone 기준 재실행(2026-08-19), 평균 CER 0.0000** | `src/tts/infer.py`로 합성 → `src/stt/infer.py`로 재인식 → CER 계산(AC-16 관련, WER 아니라 CER로 변경됨). **GPU 필요**(STT의 4bit 로딩이 CUDA 전용) + private TTS repo라 `HF_TOKEN` 필요. `requirements-stt.txt`(`transformers==4.46.3`)와 `qwen-tts`(`transformers==4.57.3` 요구) 버전 충돌은 `requirements-stt.txt`를 `4.57.3`으로 올려서 해결(`docs/decisions.md` 참고). TTS↔STT를 같은 프로세스에서 로드하면 bitsandbytes 4bit 양자화가 CUDA 전역 상태를 오염시켜 TTS가 50배 이상 느려지는 문제도 발견해 `--phase synthesize`/`--phase transcribe` 별도 프로세스 구조로 우회. **결과(기본 5문장, 13에포크+voice-clone): 평균 CER 0.0000(5문장 전부)** — 상세 비교표는 `../src/tts/README.md` 실측 결과 ① 참고. `--sentences-file <줄마다 문장 하나인 txt>` 옵션으로 커스텀 문장 세트도 합성 가능(2026-08-19 추가) — 오디오는 세트에 상관없이 항상 `results/tts/new_sentences_test/`에 `{순번:02d}_{텍스트슬러그}.wav`로 저장되고(예: `00_소금8분의1스푼간장2분의1스푼발사믹식.wav`), CSV는 문장 파일 이름을 따라 분리됨(`results/tts/<stem>.csv`/`<stem>_pending.csv`, 헤더는 `텍스트/오디오/길이(초)/상태`·`텍스트/음성인식결과/CER`). `max_new_tokens`는 긴 문장 잘림 실측(170~300까지 비교) 끝에 195로 확정했다가 **팀원 요청으로 195에서도 잘리는 게 확인돼 250으로 재조정(2026-08-19)** — 상세는 `../src/tts/README.md` 실측 결과 ③, 매 합성 직전 `seed=42` 고정으로 재현성 확보 |

## 진행 방법

- 유닛테스트는 지금 바로 실행 가능: `pytest tests/ -k "not tts_cpu_inference"`
  (`tts_cpu_inference_test.py`는 pytest 규약이 아니라 `python tests/tts_cpu_inference_test.py`로 직접 실행)
- `integration_test.md`는 이미 채워졌다 — 문서에 적힌 `uv run` 명령으로 파이썬 셸을 열고, 각
  시나리오의 `handle_utterance(...)` 호출을 순서대로 실행하며 PASS/FAIL 체크박스를 채우면 된다.
- `tts_cpu_inference_test.py`는 GPU 없는 머신(또는 `CUDA_VISIBLE_DEVICES=""` 강제)에서 실행해서
  실제 HF Spaces CPU 환경과 비슷한 조건으로 측정한다. 결과는 `results/tts/cpu_inference_test.csv`.

## 필요한 것 / 막힌 것

- AC-16(TTS)은 roundtrip CER은 13에포크+voice-clone 전환으로 **해소됨**(평균 0.0000, 위 표 참고) — 배포는 이미 GPU(RTX 5070) 상시 구동으로 확정됐으므로(`docs/decisions.md` #2) CPU 배포 속도는 더 이상 배포 기준이 아니다
- `src/app.py`가 실제 서비스 엔트리포인트로 완성돼 있어 브라우저로 직접 눌러보는 게 가능하다 — `integration_test.md`의 함수 단위(`handle_utterance()`) 확인은 여전히 pytest 없이 빠르게 회귀를 잡는 용도로 유효
- pytest 전체 스위트는 2026-08-28 기준 **87개 전부 PASS** 확인(`pytest tests/`). 재료대체 관련 `match_type` 필드는 기능 자체가 제거되면서 더 이상 검증 대상이 아니다
- `docs/audits/chefear-voice-pipeline-debug-20260826/README.md`에 실서비스 로그 기반 전체 파이프라인 점검 기록이 있다 — pytest로는 못 잡는 "Queue overflow"류 실사용 이슈는 그쪽을 참고

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` 6장 AC-14~16, `docs/ChefEar_팀_진행_가이드_v2.md` Day5~7 일정.
