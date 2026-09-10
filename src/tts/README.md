# src/tts/ — TTS (Qwen3-TTS 파인튜닝·배포)

담당: 홍민하(파인튜닝·평가), 김승욱(배포 추론·속도·잘림 수정)

## 파일

| 파일 | 역할 |
|---|---|
| `infer.py` | `tts_synthesize(text) -> (waveform, sample_rate)`. 체크포인트 로드(bfloat16, flash-attn 있으면 사용, 없으면 SDPA), 참조 음성 voice-clone, `max_new_tokens` 동적 계산, 끝 구간 무음 판정·재시도, 꼬리 아티팩트 트리밍, 조용한 끝음절 게인 보정 |
| `pronunciation.py` | TTS 직전 텍스트 보정: "닭을"→"달글"(겹받침 연음), "3. "→"삼단계, ", 문장 종결 부호 보정. 화면·DB 원문은 건드리지 않음 |
| `assets/kss_reference.wav` | voice-clone 참조 음성(KSS 원본 000008번) |

## 학습 설정

| 항목 | 값 |
|---|---|
| 베이스 | `Qwen3-TTS-12Hz-1.7B-Base` |
| 데이터 | KSS(12,854문장, CC BY-NC-SA 4.0), 24kHz 리샘플링 |
| 방식 | LoRA 파인튜닝 후 `merge_and_unload`, Colab A100 |
| 체크포인트 | epoch-8 → epoch-24(회귀) → **epoch-13 채택** |
| 저장소 | HF `kimseunguk/qwen3-tts-kss-finetuned` (private) |
| 추론 | qwen-tts 0.1.1, `tts_model_type="base"` → `generate_voice_clone()` |

학습 스크립트는 개인 작업 공간에서 실행했고 이 저장소에는 없다.

## 결과

**TTS → STT 재인식 CER**(`tests/tts_stt_roundtrip_test.py`, 5문장):

| 문장 | epoch-8 | epoch-24 | epoch-13 |
|---|---|---|---|
| 약불로 5분간 끓여주세요 | 1.00 | 40.36 | 0.00 |
| 양파와 마늘을 볶아주세요 | 0.70 | 18.70 | 0.00 |
| 1.5컵의 물을 넣고 뜸을 들여주세요 | 5.84 | 0.92 | 0.00 |
| 두부와 감자를 썰어 넣습니다 | 0.05 | 10.05 | 0.00 |
| 된장을 풀어줍니다 | 0.00 | 1.25 | 0.00 |
| 평균 | 1.37 | 14.26 | **0.00** |

epoch-24는 화자 임베딩 테이블이 바뀌어 화자명 호출이 실패했고, 우회해 측정하니 반복 발화가 늘어 CER이 급등했다. 과적합으로 판단해 epoch-13으로 되돌리고 voice-clone 방식으로 전환했다.

**파인튜닝 방식 비교**(별도 실험 공간, `results/tts/eval/`): Full FT는 base 대비 WER·CER·MOS 모두 회귀(MOS 2.10), LoRA·QLoRA는 base와 동등. 블라인드 MOS(13명, 909건)에서 LoRA 4.67로 1위.

**속도**(RTX 5070, 4문장 평균): CPU 26.11초 → GPU eager 6.34 → SDPA 5.48 → `torch.compile(dynamic=True)` 5.21초. 긴 문장은 여전히 5초를 넘긴다.

## 배포 중 해결한 문제

- **긴 문장 잘림**: `max_new_tokens` 고정값을 170~360까지 올려도 재발해, 글자당 10토큰 비례 계산(하한 200, 상한 1200)으로 전환.
- **끝음절 잘림**: 원인은 TTS 캐시 파일을 읽는 중에 다른 스레드가 덮어쓰는 레이스. 임시파일 + 원자적 교체로 해결. 무음 패딩·더미 기호(`^`) 같은 우회는 튀는 소리 등 부작용만 남겨 모두 되돌림.
- **겹받침 발음**: g2pk/g2pk3 전체 적용은 "소금을 넣고"→"소그믈 러코"처럼 단어 경계를 넘는 버그가 있어 미채택. 문제 확인된 단어만 치환.
- **재현성**: 매 합성 전 시드 고정(`do_sample=True`라 시드 없이는 호출마다 결과가 달랐음).
