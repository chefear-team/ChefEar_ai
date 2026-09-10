# Fixed100 재평가 — 배포용 STT(faster-whisper, CTranslate2 int8)

- 평가 문장 수: 100
- Corpus WER: 11.83%
- Corpus CER: 1.81%
- 완전 일치 문장: 55/100
- 문장당 평균 추론 시간: 0.34초 (모델 로딩 제외, 첫 문장은 워밍업 포함)
- 총 소요: 33.9초

실행 스크립트: `src/stt/evaluate_fixed100.py`, 문장별 결과: `results/stt/fixed100_ct2_int8.csv`
