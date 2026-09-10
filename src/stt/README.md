# src/stt/ — STT (Whisper 파인튜닝·배포)

담당: 김승욱(파인튜닝·평가·배포), 하주성(검증셋·전처리·후처리, 08-24까지)

## 파일

| 파일 | 역할 |
|---|---|
| `infer.py` | `stt_transcribe(audio)` 배포용 추론. faster-whisper(CTranslate2 int8, GPU) + 단위 정규화 + 조리 문맥 기반 고위험 숫자 보정 + 환각 방어. 학습 어댑터(4-bit) 경로와 배치 평가 함수(`run_batch_test`)도 포함 |
| `export_ct2.py` | LoRA 어댑터 병합 → CTranslate2 int8 변환(오프라인 1회) |
| `evaluate_fixed100.py` | 배포 모델을 Fixed100으로 재평가해 `results/stt/`에 CSV·요약 저장 |
| `compare_realtime_models.py` | 파인튜닝 어댑터 vs 원본 모델을 실사용 음성으로 A/B 비교(진단용) |

## 학습 설정

| 항목 | 값 |
|---|---|
| 베이스 | `openai/whisper-large-v3-turbo` |
| 방식 | QLoRA, 4-bit NF4, r=16 / alpha=64 / dropout=0.05, target q_proj·k_proj·v_proj·out_proj |
| 환경 | Python 3.11.9, torch 2.5.1+cu124, transformers 4.46.3 → 4.57.3, peft 0.20.0, bitsandbytes 0.50.0 (`docs/stt.md`, `requirements-stt.txt`) |
| 데이터 | 조리문 텍스트(재료·계량·조리동작)를 TTS로 읽은 합성 음성. 단위는 한글로 정규화(`185 g → 185그램`, `2 T → 2큰술`) |
| 단계 | train300 → train1000 → reinforce250(숫자·단위 보강) → **MIX750**(리플레이 500 + 숫자보강 250, LR 1e-5) 최종 |
| 검증 | Fixed100(`data/evaluation_scripts/stt/`, 저장소 포함) · 신규500 · 고위험군 159문장 |
| 최종 어댑터 | `BEST_FINAL_mix750_replay_numeric` = HF `leeony/chefear-stt-large-v3-turbo` |
| 배포 | `kimseunguk/chefear-stt-ct2-int8` (CTranslate2 int8) |

학습 스크립트는 Colab·개인 작업 공간에서 실행했고 이 저장소에는 없다. 위 설정과 평가 자산으로 평가는 재현된다.

## 결과

| 체크포인트 | Fixed100 WER / CER | 신규500 WER / CER | 숫자·단위 |
|---|---|---|---|
| 기준(2 epoch) | 33.20% / 5.81% | — | — |
| train300 | 10.68% / 2.21% | 13.97% / 3.05% | 70.75% |
| train1000 | 7.26% / 1.49% | 10.98% / 2.33% | 86.79% |
| reinforce250 | 8.20% / 1.54% | 11.07% / 2.32% | 90.57% |
| **MIX750** | **7.68% / 1.44%** | **10.72% / 2.26%** | **90.57%** |

배포 int8 모델 Fixed100 재측정(2026-09-10): WER 11.83%, CER 1.81%, 완전 일치 55/100, 문장당 0.34초(RTX 5070). `results/stt/fixed100_summary.md`.

비교군: Whisper Small(경량), wav2vec2(숫자·단위·일부 음절 처리 한계로 중단). V1 어댑터 위 V2 추가 학습(신규 300문장, `ko-KR-SunHiNeural` 합성)은 개선이 없어 미채택.

## 후처리 설계

- **단위 정규화**: `g/kg/ml/L/T/tsp` → 한글 단위. TTS가 영문 단위를 잘못 읽는 문제를 줄인다.
- **문맥 기반 숫자 보정**: "다짐육 100그램"이 "다짐 600그램"으로 인식되는 패턴을 확인해, 현재 레시피 재료 정보(`ingredient_context`)가 있을 때만 조건부로 보정한다. 무조건 치환하지 않는다.
- **환각 방어**: `no_speech_prob` 0.85 초과 세그먼트 폐기, 유튜브·방송 상투구 블록리스트, 같은 토큰 반복 감지.
- **실시간 경로**: 호출부(`voice_io.py`)가 이미 silero-vad로 구간을 잘라 넘기므로 faster-whisper 내부 VAD는 끈다(이중 VAD로 작은 목소리가 걸러지던 문제). `beam_size=1`(beam 5에서 조기 종료 후보로 수렴하던 문제).

## 실행

```bash
python src/stt/evaluate_fixed100.py            # GPU, .env(HF_TOKEN, HF_STT_CT2_REPO)
python src/stt/export_ct2.py                   # 어댑터 → CT2 변환
```
