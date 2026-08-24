# results/ — 평가 결과물

## 이 폴더가 하는 일

STT/TTS 파인튜닝 전/후 정량 비교 자료(WER, 추론 속도 등)를 쌓는 곳. 발표자료(AC-16 딥러닝 검증)에
직접 쓰일 수치들이 여기서 나온다.

## 현재 상태 (확인: 2026-08-19)

`stt/`엔 아직 `.gitkeep`만 있다 — STT 평가 자체는 끝났지만([src/stt/README.md](../src/stt/README.md)
참고) 그 결과 CSV는 하주성님 로컬/별도 작업공간에만 있고 아직 이 폴더로 안 옮겨짐.

`tts/`는 체크포인트를 두 번 교체하며(epoch-8 → epoch-24 → 13에포크) 결과가 여러 번 갱신됐다.
상세 이력은 [src/tts/README.md](../src/tts/README.md) 참고:

| 파일 | 상태 | 만드는 스크립트 | 결과 요약 |
|---|---|---|---|
| `tts/cpu_inference_test_20260816_164450.csv` | main 브랜치에 커밋됨(2026-08-17) | `tests/tts_cpu_inference_test.py` (Colab 2 vCPU 실행) | epoch-8/구 code path 기준, 전체 평균 197.48초(목표 5초의 약 39.5배). 아래 새 결과로 대체됨(참고용으로 남김) |
| `tts/cpu_inference_test.csv` | **재측정 완료(2026-08-19)** | `tests/tts_cpu_inference_test.py` — 이미 `src/tts/infer.py`와 동일한 배포 모델/화자/레퍼런스 로딩 방식으로 팀원이 갱신해둔 공식 스크립트, 그대로 재실행함 | 4문장(3회 반복, 워밍업 제외 평균) 전부 FAIL이지만 **전체 평균 26.11초로 구버전(197.48초) 대비 대폭 개선**. 모델 로딩 9.23초 별도 |
| `tts/gpu_inference_test_20260819.csv` | **갱신(2026-08-19)** | 위와 동일 스크립트, CPU 강제 없이 GPU(cuda:0) + SDPA + `torch.compile(dynamic=True)` | 4문장 기준 eager 6.34→SDPA 5.48→compile 5.21초까지 개선했었으나, 이후 `tests/tts_cpu_inference_test.py`에 98자 긴 문장이 5번째로 추가되고 `MAX_NEW_TOKENS`가 250→197로 바뀌면서 같은 방식으로 재측정하니 **전체 평균 8.75초로 재악화**(CSV는 이 5문장 최신값) — 긴 문장 하나가 평균 20.1초를 차지. 이 문장이 197 토큰 한도에 거의 붙어서 끝나는 것도 확인함(아래 참고). `flash-attn`은 재시도했으나 여전히 설치 불가 |
| `tts/roundtrip_cer.csv` | **git 커밋됨, 최신 결과로 갱신(2026-08-19)** | `tests/tts_stt_roundtrip_test.py` (GPU 환경) | **13에포크 체크포인트 기준 5문장 전부 CER 0.0000** — 이전 epoch-8(평균 1.37)·epoch-24(평균 14.26, 아래 참고) 대비 완전 해소 |
| `tts/roundtrip_cer_epoch24.csv` | **로컬에만 있음, git 미커밋(의도적 결정, 2026-08-19)** | 동일(화자명 이슈 우회 스크립트) | epoch-24 체크포인트에서 나온 회귀 데이터(평균 CER 14.26, 반복 루프 발화 다수) — 필요시 로컬에서 참고, 저장소엔 안 올림 |
| `tts/roundtrip_audio/`, `tts/roundtrip_audio_epoch24/` | **git 미커밋(의도적, `.gitignore`)** | 위와 동일 | 합성 오디오 wav — 용량 문제로 커밋 대상에서 제외, CSV 결과만 기록으로 남김. 청취 확인은 로컬에서 직접 재생 |

파일명이 기존 계획(`roundtrip_wer.csv`)과 다른 이유: WER 대신 CER로 지표를 바꿔서
(`tests/README.md` 참고, 공백 제거 정규화와 WER 조합이 오류율을 왜곡시켜서 CER로 변경).

## 진행 방법

- TTS→STT 품질(CER)은 13에포크 체크포인트로 **해결됨** — `AC-16`(TTS 딥러닝 검증)에 이 수치를
  바로 쓸 수 있다.
- CPU 속도도 `tests/tts_cpu_inference_test.py`(이미 새 code path로 갱신돼 있던 공식 스크립트)로
  재측정 완료(2026-08-19) — 여전히 목표(5초) 미달이지만 구버전(197.48초) 대비 대폭 개선(전체
  평균 26.11초). 같은 코드로 GPU도 재봤는데(4문장, eager) 평균 6.34초 — 여기에
  `attn_implementation="sdpa"`(PyTorch 내장 fused attention, 별도 패키지 설치 불필요)를 추가로
  적용하니 평균 5.48초까지 줄었고, 그 위에 `torch.compile(dynamic=True)`까지 얹으니
  **평균 5.21초**까지 더 줄었다(목표까지 0.21초 차이). `docs/decisions.md`에도 반영함.
- `flash-attn` 설치는 이 환경(WSL, Python 3.14, torch 2.13+cu130, RTX 5070/Blackwell `sm_120`)에서
  **불가능 확인**(미리 빌드된 wheel 없음 + `nvcc` 자체가 없어 소스 빌드도 안 됨, CUDA 툴킷 새로
  설치해야 하는 큰 작업) — 2026-08-19에 실제 설치를 재시도(`uv run --with flash-attn`)해서 같은
  결론을 재확인함(빌드 단계에서 즉시 실패).
- 이전에 시도했던 `torch.compile()`(dynamic 미지정)은 **효과가 일관되지 않았음**: 문장 길이가
  바뀔 때마다 재컴파일이 일어나서(실제 서비스는 매번 다른 길이의 문장을 읽으므로), 5문장 테스트에서
  2개만 PASS·3개는 여전히 FAIL(하나는 오히려 9.48초로 원래보다 나쁨). 2026-08-19에
  **`dynamic=True`로 다시 시도하니 그 비일관성이 해소됨** — 4문장 기준 회차별 편차가 0.15~1.46초
  수준으로 줄었고 급격한 재컴파일 스파이크 없이 안정적으로 소폭 개선(SDPA 5.48초 → 5.21초). 다만
  실제 서비스 프로세스에서는 문장 길이별로 최초 1회 컴파일 워밍업 비용이 발생한다는 점은 유의.
- **새로 발견한 이슈(2026-08-19)**: `tests/tts_cpu_inference_test.py`의 `SENTENCES`에 98자짜리
  긴 양념 문장이 추가되고 `MAX_NEW_TOKENS`가 250→197로 낮아지면서, 이 문장이 197 토큰 한도에
  거의 붙어서 끝나는 걸 직접 토큰 개수로 확인함(196/197 토큰 사용, 이번 1회는 EOS로 자연 종료했지만
  `do_sample=True`라 다른 시행에선 197 한도에 걸려 실제로 잘릴 가능성이 높음). 파일 주석
  ("가장 긴 문장도 250토큰이면 충분")과 실제 값(197)이 이미 어긋나 있음 — 기존 이슈 #6과 같은
  유형. `tests/test-audio/4_소금8분의1스푼, .wav`(15.68초)로 직접 들어서 끝까지 재생되는지
  확인 권장.
- 결론적으로 5초 목표를 채우려면 ① GPU 인프라(Modal 등) ② `Qwen3-TTS 0.6B`로 축소 ③ 길이
  버킷팅 ④ `MAX_NEW_TOKENS`를 문장 길이에 비례해 동적으로 조정 등 추가 최적화 중 하나는 필요해
  보인다.
- `roundtrip_audio*/`(오디오 wav)는 git 업로드 제외로 확정 — CSV만 기록으로 남기는 쪽으로 결정됨.
- 나머지(STT 3모델 비교 CSV)는 이미 실행은 됐으니 결과 파일만 이 폴더로 옮겨 담으면 된다.

## 관련 문서

`docs/ChefEar_PRD_SDD_v0.8.md` AC-16(TTS 딥러닝 검증, 파인튜닝 전후 개선폭을 수치로 제시).
