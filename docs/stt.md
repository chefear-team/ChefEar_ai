# ChefEar STT 모델 환경

## 모델

**Base Model:** `openai/whisper-large-v3-turbo`  
**Fine-tuning:** `QLoRA (4-bit NF4)`  
**최종 모델:** `BEST_FINAL_mix750_replay_numeric`

## 사용 라이브러리 / 패키지

| 패키지 | 버전 | 용도 |
|---|---|---|
| Python | 3.11.9 | 실행 환경 |
| PyTorch | 2.5.1+cu124 | 모델 학습 / GPU 연산 |
| transformers | 4.46.3 | Whisper 모델 및 Processor |
| peft | 0.20.0 | LoRA / QLoRA Adapter |
| bitsandbytes | 0.50.0 | 4-bit NF4 양자화 |
| accelerate | 1.14.0 | GPU / Device 관리 |
| librosa | 0.11.0 | 음성 파일 로드 및 전처리 |
| pandas | 3.0.5 | CSV 데이터 처리 |
| jiwer | 4.0.0 | WER / CER 계산 |
| tqdm | 4.70.0 | 학습 / 추론 진행률 |
| soundfile | 0.14.0| 음성 파일 처리 |

## 주요 QLoRA 설정

`r=16 / alpha=64 / dropout=0.05 / target=q_proj,k_proj,v_proj,out_proj`

> PyTorch/CUDA 환경은 실행 PC의 GPU 환경에 따라 달라질 수 있으며, 위 버전은 ChefEar STT 모델 학습 당시 사용한 환경이다.