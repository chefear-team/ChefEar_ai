# results/ — 평가 결과물

STT/TTS 파인튜닝 전/후 정량 비교 자료. 요약은 `README.md` 5장.

## stt/

| 파일 | 내용 | 생성 |
|---|---|---|
| `STT_평가지표_대시보드.html` | 체크포인트별 Fixed100/신규500 WER·CER·숫자단위 정확도, 3모델 비교 대시보드(발표용) | 학습 환경 |
| `fixed100_ct2_int8.csv` | 배포 중인 int8 모델의 Fixed100 문장별 정답/인식결과/WER/CER | `python src/stt/evaluate_fixed100.py` |
| `fixed100_summary.md` | 위 결과 요약(Corpus WER 11.83%, CER 1.81%, 완전 일치 55/100) | 동일 |

발표 표(MIX750 Fixed100 WER 7.68%)는 학습 환경의 4-bit 어댑터 기준이고, `fixed100_*`는 CTranslate2 int8 변환본 기준이라 수치가 다르다. 검증셋은 `data/evaluation_scripts/stt/`에 커밋돼 있어 누구나 재실행할 수 있다.

## tts/

| 파일 | 내용 |
|---|---|
| `TTS_정량지표_대시보드.html` | Full/LoRA/QLoRA 파인튜닝 비교, 후보 모델 7종 WER·CER·MOS 대시보드 |
| `roundtrip_cer.csv` | epoch-13 + voice-clone 재인식 CER(5문장 전부 0.00) |
| `cpu_inference_test*.csv` | CPU 추론 속도(26.11초, 배포 불가 판정) |
| `gpu_inference_test_20260819.csv` | GPU 추론 속도(eager → SDPA → compile) |
| `eval/*.csv` | 파인튜닝 방식별·체크포인트별 WER/CER/RTF 원자료(Qwen3-TTS, Chatterbox) |
| `mos/MOS_청취평가.html` | 블라인드 MOS 집계(13명, 909건). 참여자별 원자료는 개인정보 성격이라 저장소에 넣지 않음 |

합성 오디오(`roundtrip_audio*/`)는 용량 때문에 git에 넣지 않는다.

## 재실행

```bash
python src/stt/evaluate_fixed100.py          # GPU + .env(HF_TOKEN, HF_STT_CT2_REPO)
python tests/tts_stt_roundtrip_test.py       # GPU, --phase synthesize / transcribe
python tests/tts_cpu_inference_test.py       # CPU 속도
```
