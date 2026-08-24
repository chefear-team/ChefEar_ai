# 통합테스트 이슈 리포트 (2026-08-18)

담당: 김승욱 세션 보조(Claude Code) — `seunguk` 브랜치, 커밋 `2de1721` 기준. 오케스트레이션
전체 + TTS→STT 라운드트립을 직접 실행하고 확인한 결과만 적었다. **"확인됨"은 이 세션에서
직접 재현·측정한 사실이고, "가능성"은 근거는 있지만 단정할 수 없는 추정이다** — 섞어서 읽지
말 것.

## 한눈에 보기 (우선순위순)

| # | 이슈 | 심각도 | 상태 |
|---|---|---|---|
| 1 | TTS 라이브 체크포인트 화자명 불일치 — `tts_synthesize()` 100% 실패 | 🔴 Blocker | **확인됨(신규)** |
| 2 | TTS 라이브 체크포인트(epoch-24) 품질이 어제(epoch-8) 대비 급격히 저하 | 🔴 Blocker | **확인됨(신규)**, 원인은 가능성 |
| 3 | `src/stt/infer.py`가 배포 의존성 목록에 없는 `python-dotenv`를 씀 | 🔴 Blocker(배포 시) | **확인됨(신규)** |
| 4 | `src/app.py` 완전히 비어있음(0줄) — 화면 단위 종단간 테스트 불가 | 🟠 High | 확인됨(기존에 알려짐, 재확인) |
| 5 | STT 배포 경로 부재 — 4bit 양자화가 CUDA 전용, 목표 배포 환경(HF Spaces CPU)에서 로드 불가 | 🟠 High | 확인됨(기존에 알려짐, 재확인) |
| 6 | `max_new_tokens=600` 상한 때문에 긴 문장 오디오가 도중에 잘림 | 🟡 Medium | 확인됨(기존+오늘 재현) |
| 7 | TTS CPU 추론 속도 FAIL(197초, 목표 5초) | 🟡 Medium | 기존 실측치 — **이번엔 재검증 안 함**(아래 범위 참고) |
| 8 | 재료대체 매칭 실패 시 `match_type` 필드에 대한 pytest 회귀테스트 없음 | 🟡 Medium | 확인됨(기존에 알려짐, 재확인) |
| 9 | 의도분류 THRESHOLD/MARGIN이 임시값(실측 미확정) | 🟢 Low | 확인됨(기존에 알려짐, 재확인) |
| — | 오케스트레이션 레이어(의도분류→라우팅→DB) | — | **이상 없음** — pytest 50/50, 실DB 시나리오 31/31 PASS |

---

## 오늘 실제로 실행한 것 / 안 한 것 (테스트 범위)

**실행함(직접 재현):**
- `pytest tests/ --ignore=tts_cpu_inference_test.py --ignore=tts_stt_roundtrip_test.py --ignore=integration_scenario_test.py` → **50/50 PASS**
- `uv run ... python tests/integration_scenario_test.py`(실제 Supabase 연결, `allow_mock=False`) → **31/31 PASS** (시나리오 A~D, AC-15 반복 15회)
- `tests/tts_stt_roundtrip_test.py`를 GPU 환경에서 재실행 시도 → 이슈 #1로 즉시 실패, 화자명을 우회해서 재측정 → 이슈 #2 발견(아래 상세)

**안 함(범위 밖, 솔직히 밝힘):**
- `tests/tts_cpu_inference_test.py`(CPU 추론 속도 벤치마크) 재실행은 안 함 — 기존 결과(2026-08-17, 197.48초)를 그대로 인용만 했다. CPU 강제 벤치마크는 수 분~수십 분이 걸리고, 이번 세션의 초점(오케스트레이션+TTS/STT 품질 검증)과 겹치지 않아 생략했다. 재검증이 필요하면 별도로 요청 바람.
- `src/app.py`가 비어있어 실제 화면(마이크 입력→화면 출력) 기준 종단간 테스트는 애초에 불가능했다(아래 #4).

**중간에 있었던 일:** 라운드트립 재검증 도중 WSL 환경이 재부팅되어(호스트 절전모드 추정, 확정은
아님) 백그라운드 작업이 한 번 끊겼다. `/tmp` 임시 파일만 날아갔고 프로젝트 파일·모델 캐시는
`/mnt/c`·WSL 디스크에 남아있어 재다운로드 없이 이어서 완료했다 — 결과 자체에는 영향 없음.

---

## 🔴 #1. TTS 라이브 체크포인트 화자명 불일치 — `tts_synthesize()` 100% 실패

**확인됨.** `src/tts/infer.py:45`가 `SPEAKER = "kss_speaker_a100"`를 하드코딩하는데, 지금 Hugging
Face에 올라가 있는 `kimseunguk/qwen3-tts-kss-finetuned`(private repo) 최신 커밋은 이 화자명을
지원하지 않는다. 아무 문장이나 `tts_synthesize()`를 호출하면 예외로 죽는다.

```
ValueError: Unsupported speakers: ['kss_speaker_a100']. Supported: ['kss_speaker']
```

재현: `uv run --with-requirements requirements-stt.txt --with qwen-tts==0.1.1 --python 3.12 python tests/tts_stt_roundtrip_test.py`

**원인(확인됨, HF API로 커밋 이력 직접 조회):** 이 repo는 커밋이 3개다 — `initial commit`
(08-16 12:43) → `checkpoint-epoch-8, merged`(08-16 12:47, **어제 라운드트립 테스트가 쓴 버전**)
→ `checkpoint-epoch-24`(**08-17 09:40, 지금 최신**). epoch-8에서 epoch-24로 재업로드되면서
화자 슬롯 이름이 `kss_speaker_a100` → `kss_speaker`로 바뀌었다. 즉 코드가 낡은 게 아니라, **모델
쪽이 코드 모르게 먼저 바뀌었다.**

**영향:** `src/tts/infer.py`뿐 아니라 `tests/tts_cpu_inference_test.py:46`도 같은 문자열을
하드코딩하고 있어 똑같이 깨진다. `app.py`가 완성돼서 이 함수를 실제로 연결하면 서비스 첫 호출부터
100% 실패한다.

**개선방안:**
1. (즉시, 저위험) `src/tts/infer.py`의 `SPEAKER`와 `tests/tts_cpu_inference_test.py`의 `SPEAKER`를
   `"kss_speaker"`로 수정 — 이 세션에서 이 값으로 실제 합성 성공까지 검증했다(아래 #2의 데이터가
   그 결과물).
2. (재발 방지, 더 중요) `Qwen3TTSModel.from_pretrained(MODEL_ID, ...)` 호출에 `revision=`(커밋
   SHA)을 명시해서 버전을 고정할 것. 지금처럼 브랜치 최신(`main`)을 그냥 참조하면, TTS 담당자가
   재학습해서 push하는 순간 오케스트레이션/배포 쪽 코드는 아무것도 안 건드렸는데 서비스가 조용히
   깨진다 — 이번이 정확히 그 사례다. 모델을 갱신할 땐 코드 쪽 `revision`도 같이 올리는 걸
   PR 체크리스트에 넣는 걸 제안한다.
3. 팀에 **지금 바로 공유 필요** — 이 문제를 몰랐다면 `docs/decisions.md`·`src/tts/README.md`에
   적힌 "roundtrip CER 1.37" 수치가 이미 낡은 값이라는 뜻이다(아래 #2).

---

## 🔴 #2. TTS 라이브 체크포인트(epoch-24) 품질이 어제(epoch-8) 대비 급격히 저하

**확인됨(직접 재측정).** 위 #1의 화자명만 우회해서(코드는 안 고치고 별도 스크립트로 `speaker="kss_speaker"`
직접 호출) 어제와 동일한 5문장을 다시 합성 → 같은 STT로 재인식 → CER 계산까지 전 과정을 오늘
다시 실행했다.

| 문장 | 어제(epoch-8) CER | 오늘(epoch-24) CER | 오늘 STT 인식 결과(발췌) |
|---|---|---|---|
| 약불로 5분간 끓여주세요 | 1.00 | **40.36** | "이틀은 시장에 있는 장소한 장소한 장소한..."(같은 단어 반복 150회+) |
| 양파와 마늘을... 볶아주세요 | 0.70 | **18.70** | "다는 데에다가는 데에다가는..."(반복) |
| 1.5컵의 물을... 뜸을 들여주세요 | 5.84 | 0.92 | "다음 영상에서 만나요." |
| 두부와 감자를... 썰어 넣습니다 | 0.05 | **10.05** | "이틀은 또한 이틀은 또한..."(반복) |
| 된장을 풀어줍니다 | 0.00 | **1.25** | "어떻게 하는지 모르겠고," |
| **평균** | **1.37** | **14.26** | |

결과 파일: `results/tts/roundtrip_cer_epoch24.csv`, 오디오: `results/tts/roundtrip_audio_epoch24/*.wav`
(둘 다 미커밋 — 기존 `roundtrip_cer.csv`/`roundtrip_audio/`와 마찬가지).

**오디오 자체가 무음/깨진 파일인지도 확인함(테스트 스크립트 버그 배제 목적):** RMS·피크 진폭을
어제 파일과 비교했는데 둘 다 정상 범위(무음이나 클리핑 아님) — 즉 스크립트가 빈 파일을 잘못
읽은 게 아니라, 실제로 소리는 나지만 STT가 알아들을 수 없는 내용으로 생성되고 있다는 뜻이다.

**주목할 점 — 짧은 문장도 나빠짐:** "된장을 풀어줍니다"(2초짜리 짧은 문장, `max_new_tokens` 한도와
무관)조차 어제 CER 0.00(완벽)이었는데 오늘은 1.25로 나빠졌다. 반면 가장 CER이 나빴던 문장(1.5컵...)은
오히려 오늘이 나아졌다(5.84→0.92) — 즉 단순히 "긴 문장이라 잘림" 문제만은 아니고, 체크포인트 자체의
전반적인 음질/발화 안정성이 흔들리는 것으로 보인다.

**원인(가능성, 확정 아님):**
- epoch-24가 epoch-8보다 더 많이 학습된 체크포인트인데, 소규모 데이터셋(KSS) 파인튜닝에서는 에폭을
  늘릴수록 오히려 과적합(overfitting)으로 품질이 나빠지는 경우가 흔하다 — **가능성 있는 원인이지
  학습 로그(loss curve)를 직접 보지 않아 확정할 수 없다.**
- 화자 슬롯 이름이 `kss_speaker_a100`→`kss_speaker`로 바뀐 걸 보면 학습 스크립트 자체가 바뀌었을
  수 있고, 그 변경 과정에서 의도치 않은 부작용이 있었을 가능성도 배제 못 한다.
- STT가 반복되는 단어 루프("장소한 장소한...", "이틀은 또한...")를 뱉는 패턴은, 원래 있던 "TTS가
  멈춤 토큰을 못 찾고 생성을 반복한다"는 이슈(`docs/decisions.md`, `max_new_tokens` 관련)와 결이
  비슷해 보이지만 — 이번엔 45초 이상 걸리지 않은 짧은 문장에서도 나타나서, 완전히 같은 원인인지는
  불확실하다.

**개선방안:**
1. **지금 바로 TTS 담당(홍민하)에게 알릴 것** — 지금 Hub에 있는 게 최신이라고 그냥 쓰면 안 되는
   상태다. 학습 로그(loss)를 epoch-8 시점과 epoch-24 시점 비교해서 과적합 여부부터 확인 필요.
2. 비교가 끝나기 전까지는 **epoch-8 커밋(`794431d22ca868eaa71da4fdd54bfe33c838d1cb`)으로 되돌리는
   걸 임시 조치로 권장** — 어제 데이터 기준으로는(CER 1.37, 그 자체도 나쁘지만) 오늘보다는 훨씬
   낫다. 되돌릴 때도 위 #1의 `revision` 고정을 같이 적용하면 이런 "모르는 새 바뀜" 재발을 막을 수
   있다.
3. 청취 평가(주관 점수)를 최소 1인 이상 직접 귀로 들어보고 병행 판단할 것 — CER만으로는 "STT가
   특정 목소리에 약한 것"과 "TTS 발음 자체가 깨진 것"을 완전히 구분하기 어렵다.
4. AC-16(TTS 딥러닝 검증)에 이 수치를 그대로 쓰면 안 된다 — "파인튜닝 후 개선됨"을 보여야 하는데
   지금 라이브 버전은 오히려 어제보다 악화된 상태다.

---

## 🔴 #3. `src/stt/infer.py`가 배포 의존성 목록에 없는 `python-dotenv`를 씀

**확인됨(코드+requirements 직접 대조).** `src/stt/infer.py:44`가 `from dotenv import load_dotenv`를
쓰는데, `python-dotenv`는 `requirements-stt.txt`(STT 학습 전용 환경)에만 있고, 실제 배포/서비스가
쓰는 `requirements.txt`·`requirements-main.txt`엔 없다.

```
$ grep -n dotenv requirements*.txt
requirements-stt.txt:13:python-dotenv==1.2.3
```

**`docs/decisions.md`의 기존 기록과 다른 점:** 그 문서(2026-08-17 항목)는 "`seunguk` 브랜치의
`src/tts/infer.py`는... `load_env()` 재사용으로 우회 해결(이미 실측 검증됨)"이라고만 적혀 있어서
`tts/infer.py` 얘기임이 명확한데, 옆에서 읽으면 "seunguk은 해결됐다"로 오해하기 쉽다. 실제로
`src/tts/infer.py`는 `orchestration.db.load_env()`로 이미 고쳐져 있지만(의존성 없음, 확인함),
**`src/stt/infer.py`는 아직 그대로 `python-dotenv`를 쓴다** — 같은 문제가 이 파일엔 안 고쳐진 채
남아있다.

**영향:** 지금은 STT 통합테스트를 GPU 환경(`requirements-stt.txt` 설치됨)에서만 돌려서 안 드러났을
뿐, HF Spaces(`requirements.txt`만 설치되는 배포 환경)에서 `app.py`가 `stt.infer`를 import하는
순간 `ModuleNotFoundError: No module named 'dotenv'`로 즉시 죽는다.

**개선방안:**
1. `src/stt/infer.py`도 `tts/infer.py`와 동일하게 `from orchestration.db import load_env` +
   `load_env()`로 바꾸는 걸 권장(이미 검증된 패턴을 재사용, 새 의존성 안 늘어남).
2. 대안으로 `python-dotenv`를 `requirements.txt`/`requirements-main.txt`에 추가해도 되지만, 그러면
   배포 최소 의존성 파일에 STT 학습용 라이브러리 의존이 섞여 들어가는 셈이라 1번 쪽을 더 권장한다.
3. 이 김에 `requirements.txt`에 `qwen_tts`도 아직 없다는 기존 기록(`src/tts/README.md`)도 같이
   처리하는 게 효율적 — 배포 직전에 한꺼번에 `ModuleNotFoundError` 두 개를 순서대로 만나는 것보단
   지금 미리 정리하는 게 낫다.

---

## 🟠 #4. `src/app.py` 완전히 비어있음(0줄)

**확인됨(재확인).** `wc -l src/app.py` → 0. `tests/integration_test.md`(2026-08-16 기록)에 이미
같은 내용이 있고, 오늘도 그대로다 — 새로운 사실은 아니지만 "총체적 통합테스트"에서 가장 큰 공백이라
다시 짚는다.

**영향:** 마이크 입력 → STT → `handle_utterance()` → TTS 응답까지 한 화면에서 눌러보는 진짜
종단간(end-to-end) 통합테스트가 물리적으로 불가능하다. 지금까지의 모든 통합테스트(이 리포트 포함)는
"오케스트레이션 함수 직접 호출"과 "TTS→STT 파이프라인만 별도 검증"으로 나눠서 우회 검증한 것이지,
실제 사용자 흐름을 검증한 게 아니다.

**개선방안:** 이미 준비된 조각(`orchestration.pipeline.handle_utterance()`, `tts.infer.tts_synthesize()`,
`ui/` 프로토타입 화면 11개)을 엮기만 하면 되는 단계 — 다만 위 #1~#3을 먼저 고치지 않으면 `app.py`를
완성해도 TTS 호출에서 바로 깨지므로, 순서상 이 리포트의 🔴 항목들을 먼저 해결하고 `app.py`
작업에 들어가는 걸 권장한다.

---

## 🟠 #5. STT 배포 경로 부재 — 4bit 양자화가 CUDA 전용

**확인됨(코드 직접 확인, 기존에도 알려진 내용).** `src/stt/infer.py`는
`BitsAndBytesConfig(load_in_4bit=True, ...)`로 4bit NF4 양자화를 쓰는데, 이건 CUDA 커널 기반이라
GPU 없는 환경에선 로드 자체가 안 된다(`tests/tts_stt_roundtrip_test.py` 모듈 docstring에도 같은
내용이 명시돼 있음). 그런데 `AGENTS.md`에 적힌 실제 배포 타깃은 "HF Spaces(CPU Basic, 무료)"고,
같은 문서가 "배포는 faster-whisper 1.2.1(int8 양자화)로 추론"이라고 못 박고 있다 — 즉 지금
`src/stt/infer.py`는 배포용이 아니라 평가용 스크립트이고, faster-whisper 기반 배포용 함수는
아직 작성되지 않았다(`src/README.md`, `src/stt/README.md` "남은 작업" 목록에 이미 기재됨).

**개선방안(기존 계획 재확인 성격):** `src/stt/infer.py`에 `stt_transcribe(audio) -> str` 같은
단일 발화용 함수를 faster-whisper 기반으로 새로 작성 필요. 지금 있는 `_transcribe_audio()`는
이름부터 "배치 테스트 내부용, 외부 호출 대상 아님"이라고 docstring에 명시돼 있어 그대로 갖다 쓰면
안 된다.

---

## 🟡 #6. `max_new_tokens=600` 상한으로 긴 문장 오디오가 도중에 잘림

**확인됨(오늘도 재현).** 5문장 중 2문장("약불로...", "1.5컵의 물을...")이 어제·오늘 두 체크포인트
모두에서 정확히 47.92초(=600 토큰 상한)에 걸려 있다 — 우연이 아니라 상한에 막혀 강제 종료된 것으로
보인다. 이미 `src/tts/infer.py`·`docs/decisions.md`에 기록된 이슈이고 오늘 데이터로 재확인만 했다.

**개선방안:** 상한값을 문장 길이에 비례해서 동적으로 잡거나(예: 글자 수 기반 추정), 그게 여의치
않으면 최소한 "생성이 상한에 걸려 잘렸는지" 여부를 `tts_synthesize()`가 반환값에 플래그로
알려주면(예: `hit_max_tokens: bool`) 최소한 잘린 걸 알고 재시도하거나 사용자에게 안내라도 할 수
있다 — 지금은 잘려도 조용히 그 오디오를 그대로 반환한다.

---

## 🟡 #7. TTS CPU 추론 속도 FAIL — 이번 세션 재검증 안 함

기존 실측(2026-08-17, `tests/cpu_inference_test_20260816_164450.csv`): 3문장 평균 197.48초,
목표(5초)의 약 39.5배. **이번 세션에서 다시 돌리지 않았다** — 정직하게 밝혀둔다(위 "테스트 범위"
참고). 다만 위 #2에서 라이브 체크포인트 자체 품질이 바뀐 걸 확인했으므로, CPU 속도도 체크포인트가
바뀌었으니 재측정하면 값이 달라질 가능성이 있다(속도는 보통 파라미터 수·구조에 좌우되니 크게
안 바뀔 가능성이 더 높지만, 확인 전엔 단정할 수 없다).

---

## 🟡 #8. `match_type` 필드 pytest 회귀테스트 없음

**확인됨(재확인).** `src/orchestration/pipeline.py:165`가 매칭 완전 실패 시
`{"match_type": "none", ...}`을 반환하는데, `tests/test_substitution.py`는 `apply_substitution()`
함수 자체만 합성 딕셔너리로 테스트하고, `tests/test_pipeline.py`도 이 필드를 검증하는 케이스가
없다. 이 필드는 원래 `tests/integration_test.md` 시나리오 C를 **수동으로** 실행하다가 빠진 걸
발견해서 추가된 것(2026-08-16)인데, 그걸 지키는 자동 회귀테스트가 여전히 없다.

**개선방안:** `test_pipeline.py`에 `handle_utterance()`를 매칭 실패 케이스로 호출해서
`result["match_type"] == "none"`을 직접 assert하는 테스트 1개만 추가하면 된다 — 다음에 누가
브랜치 병합하다 이 필드를 조용히 빠뜨려도 pytest가 바로 잡아준다.

---

## 🟢 #9. 의도분류 THRESHOLD/MARGIN 임시값

**확인됨(재확인, `src/orchestration/intent_classifier.py:52-53`).** `THRESHOLD = 0.5`,
`MARGIN = 0.05` — 코드 주석에도 "일단 기능이 돌아가게 만든 개발용 임시값"이라고 명시돼 있고
(`OI-09`), 오늘 pytest·실DB 테스트 전부 이 값 기준으로 PASS했지만 "정답 판정 기준값 자체가
아직 실측 확정이 아니다"라는 사실은 변하지 않는다. 새로 발견한 문제는 아니고 그대로 남아있음을
재확인.

**개선방안:** 기존 계획대로 실제 사용자 발화 샘플을 모아 threshold/margin 근처에서 오분류가
얼마나 나는지 측정 후 확정 필요 — 우선순위는 위 🔴 항목들보다 낮다고 판단(오분류 시 최소한
"다시 말씀해주세요"로 안전하게 fallback하는 설계라 서비스가 죽지는 않음).

---

## ✅ 문제 없음 — 오케스트레이션 레이어

의도분류→라우팅→DB(Supabase 실연결) 전 구간은 오늘 재실행 기준으로 **회귀 없음**:

- `pytest tests/`(가짜 DB, `FakeSupabaseClient`): **50/50 PASS**
- `tests/integration_scenario_test.py`(실제 Supabase, `allow_mock=False`): **31/31 PASS**
  (시나리오 A 조회/진행, B 재료대체+취소, C 매칭실패 정직 안내, D 미등록 요리→신규등록 유도,
  AC-15 15회 반복 일관성 전부 포함)

`tests/integration_test.md`에 이미 기록된 2026-08-16/17 결과와 수치까지 동일하게 재현됐다.

---

## 참고 — 재현 명령어 모음

```bash
# 1) 오케스트레이션 유닛테스트 (가짜 DB, GPU/네트워크 불필요)
pytest tests/ --ignore=tests/tts_cpu_inference_test.py \
              --ignore=tests/tts_stt_roundtrip_test.py \
              --ignore=tests/integration_scenario_test.py

# 2) 실제 Supabase 연동 시나리오 (.env 필요)
uv run --with sentence-transformers==5.6.1 --with supabase==2.31.0 --python 3.12 \
    python tests/integration_scenario_test.py

# 3) TTS→STT 라운드트립 (GPU + HF_TOKEN 필요, src/tts/infer.py의 SPEAKER를
#    "kss_speaker"로 고친 뒤 실행할 것 — 안 고치면 #1 그대로 재현됨)
uv run --with-requirements requirements-stt.txt --with qwen-tts==0.1.1 --python 3.12 \
    python tests/tts_stt_roundtrip_test.py
```

## 관련 문서

`tests/integration_test.md`(오케스트레이션 수동 시나리오), `tests/README.md`,
`src/tts/README.md`, `src/stt/README.md`, `docs/decisions.md`.
