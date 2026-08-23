# src/tts/ — 담당: 홍민하 (B, TTS 파인튜닝/UI)

## 이 폴더가 하는 일

Qwen3-TTS-12Hz-1.7B(VoiceDesign)를 KSS 데이터셋으로 파인튜닝하고, HF Spaces CPU Basic(무료)
환경에서 목표 응답시간(5초) 안에 추론이 되는지가 핵심 리스크(R-13/OI-11, `docs/decisions.md`).

## 파일별 상태 (확인: 2026-08-19)

| 파일 | 상태 | 역할 |
|---|---|---|
| `prepare_data.py` | **비어있음(0줄)** | KSS 24kHz 리샘플링 — 실제로는 별도 개인 작업 공간(`test/scripts/prepare_qwen3_tts_data.py`)에서 이미 진행됨, 이 정식 위치로는 아직 이식 안 됨 |
| `finetune_qwen3tts.py` | **비어있음(0줄)** | Qwen3-TTS QLoRA 파인튜닝 — 마찬가지로 `test/scripts/train_qwen3_tts.py`에서 이미 진행됨(체크포인트 이력은 아래 참고), 이 정식 위치로는 아직 이식 안 됨 |
| `infer.py` | **완성, 13에포크 체크포인트 + voice-clone 방식으로 전면 교체(2026-08-19), max_new_tokens/시드 튜닝 완료(2026-08-19)** | `tts_synthesize(text) -> (waveform, sample_rate)`. 로드한 체크포인트의 `tts_model_type`을 보고 자동 분기: `"base"`(현재 기준 체크포인트)면 `assets/kss_reference.wav`로 목소리를 복제하는 `generate_voice_clone()`, `"custom_voice"`(과거 체크포인트로 되돌아갈 경우 대비)면 화자명 `SPEAKER="kss_speaker"`로 `generate_custom_voice()`. GPU 있으면 cuda/bfloat16, 없으면 CPU/float32로 자동 분기. `max_new_tokens` 기본값 **280**(600→170→180→190→195→200→300 순으로 실측 후 195로 확정했다가, **팀원 요청으로 195에서도 잘리는 게 확인돼 250으로 재조정(2026-08-19)**, 이후 **실서비스 청취 중 250에서도 살짝 끊기는 느낌이 있다는 보고로 280으로 재조정(2026-08-23, 정식 재벤치마크 전)**, 아래 실측 결과 ③ 참고). 매 합성 직전 `torch.manual_seed(42)`로 시드 고정(재현성 확보 — 이전엔 `do_sample=True`인데 시드 고정이 전혀 없어 같은 문장도 호출마다 결과가 달랐음) |
| `assets/kss_reference.wav` | **신규 추가(2026-08-19)** | voice-clone 레퍼런스 음성. KSS 원본 000008번(`나는 살아오면서 감기를 앓은 적이 한 번도 없다`) — `data/kss/metadata.csv`와 대본 페어 확인됨. Qwen 공식 데모의 영어 샘플 대신 실제 KSS 화자 목소리를 쓰려고 이걸로 골랐다 |
| `pronunciation.py` | **신규 추가(2026-08-19)** | `apply_pronunciation_fixes(text)` — 겹받침 연음을 모델이 잘못 읽는 것으로 확인된 단어만 정규식으로 직접 치환("닭을"→"달글"). `tts_synthesize()`가 TTS로 넘기는 사본에만 적용하고 화면/로그/DB용 원문은 안 건드림. 아래 "③ 발음 보정" 참고 |

## 체크포인트 이력 — epoch-8 → epoch-24(품질 저하) → 13에포크(현재, known-good)

**파인튜닝 자체는 끝났다**: `Qwen3-TTS-12Hz-1.7B-Base`를 KSS로 QLoRA 파인튜닝 후 merge_and_unload해서
HF Hub `kimseunguk/qwen3-tts-kss-finetuned`(private)에 업로드. 학습 코드
(`prepare_data.py`/`finetune_qwen3tts.py`에 해당하는 것)는 이 저장소가 아니라 별도 개인 작업 공간
(`test/`, git 추적 안 됨)에만 있다 — 나중에 정식 위치로 옮겨 담아야 재현 가능한 상태가 된다.

체크포인트를 두 번 교체하면서 화자/품질 이슈를 겪었다:

1. **checkpoint-epoch-8**(08-16 업로드) — 화자명 `kss_speaker_a100`, 5문장 평균 CER 1.37(편차 큼)
2. **checkpoint-epoch-24**(08-17 업로드) — 화자명이 코드 모르게 `kss_speaker`로 바뀌어
   `tts_synthesize()`가 100% 실패했고, 화자명만 우회해서 재측정해보니 CER이 **14.26**으로 급격히
   악화(반복 루프 발화 다수) — 상세 원인 분석은
   [tests/integration_issues_2026-08-18.md](../../tests/integration_issues_2026-08-18.md) 참고.
   결과 파일은 그대로 보존: `results/tts/roundtrip_cer_epoch24.csv`
3. **13에포크 체크포인트**(현재, 2026-08-19) — epoch-24의 과적합 의심으로 더 이전 에포크로
   되돌렸고, 동시에 `tts_model_type`이 `"base"`로 바뀌어 있어(화자 임베딩 테이블 없음) 코드를
   voice-clone 방식으로 전환. 아래 실측 결과 참고. 로컬 known-good 백업은
   `result_test_backup_ep13_working/`(git 미추적, 4.3GB) — 이후 다른 에포크와 비교할 때 기준으로 삼을 것.
   같은 날 HF Hub 리포(`kimseunguk/qwen3-tts-kss-finetuned`)의 기존 파일을 전부 지우고 이
   백업 폴더 내용으로 단일 커밋 전체 교체함(`upload_folder(delete_patterns="*")`, 커밋
   `6d893034`) — 이전 커밋 히스토리는 남아있어 필요하면 되돌릴 수 있음

## 실측 결과

**① TTS→STT roundtrip 재측정(2026-08-19, 13에포크 + voice-clone) — 5문장 전부 CER 0.0000**

`tests/tts_stt_roundtrip_test.py`를 GPU 환경에서 실행, 어제(epoch-24)와 동일한 5문장으로 재측정:

| 문장 | epoch-8 CER | epoch-24 CER | **13에포크 CER** |
|---|---|---|---|
| 약불로 5분간 끓여주세요 | 1.00 | 40.36 | **0.00** |
| 양파와 마늘을... 볶아주세요 | 0.70 | 18.70 | **0.00** |
| 1.5컵의 물을... 뜸을 들여주세요 | 5.84 | 0.92 | **0.00** |
| 두부와 감자를... 썰어 넣습니다 | 0.05 | 10.05 | **0.00** |
| 된장을 풀어줍니다 | 0.00 | 1.25 | **0.00** |
| **평균** | **1.37** | **14.26** | **0.00** |

결과 CSV: `results/tts/roundtrip_cer.csv`(git 커밋 대상). 합성 오디오는 `results/tts/new_sentences_test/*.wav`
— `tts_stt_roundtrip_test.py`의 `--sentences-file`로 어떤 문장 세트를 넣어도 오디오는 항상 이 폴더에
쌓이도록 통일함(2026-08-19, 파일명이 `{순번:02d}_{텍스트슬러그}.wav`라 세트가 달라도 구분됨).
용량 문제로 git 미커밋(개인 `.git/info/exclude`, 검증만 로컬에서 하면 됨).

`tests/integration_issues_2026-08-18.md`에 기록된 🔴 #1(화자명 불일치)·#2(품질 저하) 이슈는 이
체크포인트/코드 전환으로 **해소됨**. `AC-16`(TTS 딥러닝 검증)에 이 수치를 쓸 수 있다.

**② CPU/GPU 속도 — 13에포크+voice-clone 경로로 재측정 완료(2026-08-19), CPU는 여전히 FAIL**

`tests/tts_cpu_inference_test.py`(13에포크+voice-clone 경로로 갱신된 공식 스크립트)로 재측정:

- **CPU**: 4문장 기준 전체 평균 **26.11초**(목표 5초 FAIL) — 구 code path(197.48초) 대비 대폭 개선은
  됐지만 여전히 목표 미달. CSV: `results/tts/cpu_inference_test.csv`
- **GPU(RTX 5070) 참고치**: 같은 스크립트를 CPU 강제 없이 GPU로 실행하며 단계적으로 최적화 —
  eager 6.34초 → `attn_implementation="sdpa"`(PyTorch 내장 fused attention, 별도 설치 불필요)
  5.48초 → `torch.compile(dynamic=True)` 추가 5.21초. `flash-attn`은 이 환경(WSL, torch
  2.13+cu130, RTX 5070 Blackwell `sm_120`)에서 **설치 불가 재확인**(nvcc 없어 소스 빌드도 불가,
  두 번 실측). CSV: `results/tts/gpu_inference_test_20260819.csv`
- ⚠️ `SENTENCES`/`MAX_NEW_TOKENS`는 이후로도 팀에서 계속 실험적으로 바뀌고 있어(문장 추가/삭제,
  197→250→280 등) 위 수치는 특정 시점의 스냅샷이다 — 최신 수치는 CSV와 `docs/decisions.md`를 볼 것.
  `MAX_NEW_TOKENS`를 문장 길이 대비 너무 낮게 잡으면 긴 문장이 도중에 잘리는 걸 실측으로 확인함
  (98자 문장에서 197은 8회 중 5회 잘림, 250이면 여유 있음) — 문장을 늘릴 땐 상한도 같이 검토할 것.
  현재값 280은 2026-08-23 실서비스 청취 보고(250에서도 살짝 끊김)로 올린 값이라 아직 이
  표처럼 상한값별 수치 재실측은 안 됨 — 재현되는 문장을 확보하면 표를 다시 채울 것

**③ 발음 보정 — "닭을" 겹받침 연음 오발음 패치(2026-08-19)**

"닭을 손질하세요"의 "닭을"(ㄺ 겹받침 연음, 정확한 발음은 "달글")이 이 체크포인트에서 이상하게
발음되는 걸 청취로 확인. 한국어 G2P 라이브러리(`g2pk`, `g2pk3`)로 문장 전체를 일반화해서 고치는
것도 시도했으나, "소금을 넣고"→"소그믈 러코"처럼 "~을/를 넣고" 같은 흔한 조리 표현에서 단어
경계를 잘못 넘나드는 버그가 두 라이브러리 모두에 있어(콤마를 끼워 넣으면 버그가 사라지긴 하나
원본 레시피 텍스트에 콤마 위치를 통제할 수 없어 근본 해결 아님) 채택하지 않았다. 대신
`pronunciation.py`에 실제로 문제 확인된 단어만 정규식으로 직접 치환하는 방식을 도입 —
범용성은 낮지만 문장의 나머지 부분을 안 건드리므로 G2P 라이브러리의 교차-단어 버그에 노출되지
않는다. 새 단어에서 같은 문제가 발견되면 `pronunciation.py`의 딕셔너리에 추가하면 된다.
회귀테스트: `tests/test_tts_pronunciation.py`(torch 불필요, 빠른 pytest 스위트에 포함됨).

**③ `max_new_tokens` 튜닝(2026-08-19) — 600 → 170 → 180 → 190 → 195 → 200 → 300, 최종 250(팀원 요청)**

qwen_tts 라이브러리 기본값(2048)은 `do_sample=True`와 같이 쓰이면 운 나쁘게 멈춤 토큰을 늦게
뽑을 때 생성이 폭주할 위험이 있어(2026-08-17 확인) 상한을 낮춰왔는데, 값을 너무 낮추면 이번엔
정상적으로 긴 문장이 중간에 잘리는 반대 문제가 생긴다. 재료 목록이 긴 문장(분수 표현 다수 —
"소금8분의1스푼, 간장2분의1스푼, ..." 총 8개 재료) 하나로 상한값별 실측:

| max_new_tokens | 생성 길이 | 토큰 사용률 | 결과 |
|---|---|---|---|
| 170(≈14.17초) | 13.52초 | 95.4% | **잘림**(사용자 청취로 확인) |
| 180(≈15.00초) | 14.32초 | 95.5% | 잘림(추정) |
| 190(≈15.83초) | 15.12초 | 95.5% | **잘림**(사용자 청취로 확인, "잘려서 나왔네") |
| 195(≈16.25초) | 15.52초 | 95.5% | 잘림(추정) |
| 200(≈16.67초) | 15.92초 | 95.4% | **정상 완결** |
| 250(≈20.83초) | 15.92초 | 76.4% | **정상 완결** |
| 300(≈25.00초) | 15.92초 | 63.7% | **정상 완결** — EOS까지 자연스럽게 도달 후 정지 |

이 문장의 자연 완결 지점은 약 191토큰(15.92초)이다 — 200 미만 상한은 전부 그 지점보다 짧아
매번 강제로 끊겼다(생성 불안정 문제가 아니라 단순 상한 부족), 200 이상은 전부 15.92초로
동일하게 정상 완결됨을 실측으로 확인. `DEFAULT_MAX_NEW_TOKENS`는 처음 195로 확정했으나,
**팀원이 195에서도 잘린다고 확인해줘서 250으로 재조정(2026-08-19, 250 실측도 15.92초 정상
완결로 확인됨)** — 600(폭주 방지 목적)보다는 훨씬 낮게 유지.

**2026-08-23 재조정 — 250 → 280**: 실서비스 청취 중 250에서도 살짝 끊기는 느낌이 있다는
보고로 올림. 위 표의 재료-분수 문장 기준으로는 250도 15.92초 정상 완결로 나왔던 값이라, 이번
보고는 그보다 더 긴/다른 유형의 문장에서 나온 것으로 추정된다 — 어떤 문장에서 재현됐는지는
아직 특정되지 않았고, 280에 대한 상한값별 재실측(토큰 사용률·완결 여부)도 아직 없다(지어내지
않음, 1.5 원칙). 같은 문제가 다시 보고되면 그 문장으로 위 표 형식의 실측을 다시 채울 것.

## 진행 방법

1. ~~`data/kss/` 24kHz 리샘플링~~ → 완료(`test/` 쪽에서)
2. ~~QLoRA 파인튜닝~~ → 완료(체크포인트 이력은 위 참고)
3. ~~TTS→STT roundtrip 품질 검증~~ → 완료, **PASS**(13에포크 기준 CER 0.00, 위 실측 결과 ① 참고)
4. ~~CPU 5초 목표 재측정~~ → 완료(위 실측 결과 ②) — **CPU는 여전히 FAIL**(26.11초), GPU는
   SDPA+`torch.compile`로 5.21초까지 근접했으나 목표 미달. 대안 결정 필요: ① Modal 등 GPU
   플랫폼(SDPA+compile 적용해도 부족할 수 있음) ② 데스크탑을 Tailscale로 상시 노출 ③ Qwen3-TTS
   0.6B로 축소 ④ 길이 버킷팅
5. `prepare_data.py`/`finetune_qwen3tts.py`를 `test/scripts/`의 대응 코드로 채워서 이 저장소 안에서도
   재현 가능하게 이식(팀 문서상 정식 위치이므로 언젠가 필요)
6. `infer.py`의 `tts_synthesize()`를 `src/orchestration/pipeline.py`/`src/app.py`에 연결
   (`handle_utterance()`의 텍스트 응답을 이 함수에 넘기고 반환값을 `st.audio()`로 재생) — 품질
   문제는 해소됐으니 이제 CPU 속도(위 4번)만 확인되면 연결 가능
7. `requirements.txt`/`requirements-main.txt`에 `qwen_tts`·`python-dotenv` 패키지 버전 확정해서
   추가(`requirements-stt.txt`엔 이미 `qwen-tts==0.1.1`+`transformers==4.57.3` 조합이 실측 검증돼
   반영됨, `docs/decisions.md` 참고 — 다만 그건 STT 학습 환경이고 TTS/배포 쪽 requirements엔 아직
   없음)
8. `Qwen3TTSModel.from_pretrained(MODEL_ID, ...)`에 `revision=`(커밋 SHA) 고정 — 지금처럼 `main`
   최신을 그냥 참조하면 나중에 체크포인트가 또 바뀔 때 코드는 안 건드렸는데 서비스가 조용히 깨질
   수 있음(epoch-8→epoch-24 전환 때 실제로 겪은 문제, `tests/integration_issues_2026-08-18.md` #1)

## 필요한 것 / 막힌 것

- **CPU 배포 속도 목표(5초) 여전히 미달** — 재측정 완료(위 실측 결과 ②, CPU 26.11초/GPU
  SDPA+compile 5.21초), 대안 결정까지 팀 논의 필요
- 겹받침 연음처럼 `pronunciation.py`가 아직 커버 못 하는 단어가 실사용 중 더 나올 수 있음 —
  발견되면 딕셔너리에 추가(위 실측 결과 ③)
- `qwen_tts`·`python-dotenv` 패키지가 `requirements.txt`/`requirements-main.txt`엔 아직 없음(버전은
  실측 검증됨) — private repo라 배포 시 `HF_TOKEN`을 HF Spaces Repository secret으로 등록도 필요
- `prepare_data.py`/`finetune_qwen3tts.py` 이식 — 지금은 재현 코드가 이 저장소 밖에만 있음
- HF 모델 `revision` 고정 — 재발 방지용, 아직 미적용(위 진행 방법 8번)
- TTS 합성음을 STT 학습데이터로 쓰려면(`data/synthesized/`) `prepare_data.py`/`finetune_qwen3tts.py`
  이식이 선행되는 게 안전함
- **겹받침(복합 종성) 발음이 간헐적으로 부자연스러움** — G2P(발음열 변환) 전처리가 파이프라인에
  전혀 없고(`prepare_data.py`가 비어있음, 위 표 참고), KSS(~1.2만 문장)가 다양한 겹받침
  재음절화 맥락을 충분히 커버 못 했을 가능성이 원인으로 추정됨(확정 원인 규명은 안 됨) — G2P
  전처리 추가는 아직 계획에 없음

## 관련 문서

`docs/decisions.md`(OOM/CPU 속도 미확인 항목), `docs/ChefEar_팀_진행_가이드_v2.md` 6.1/9장,
`docs/ChefEar_PRD_SDD_v0.8.md` R-13/OI-11, `tests/integration_issues_2026-08-18.md`(화자명 불일치·
품질 저하 이슈의 최초 발견 기록).
