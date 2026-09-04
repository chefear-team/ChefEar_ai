"""ChefEar TTS - 런타임 음성 합성 (조리 단계 안내 문장 등을 음성으로).

[모델]
Base:
    Qwen/Qwen3-TTS-12Hz-1.7B-Base

QLoRA 파인튜닝 + merge_and_unload (KSS 데이터셋):
    kimseunguk/qwen3-tts-kss-finetuned (private repo)

[2026-08-19] 13에포크 체크포인트로 교체하면서 `tts_model_type`이 "base"로 바뀌었다(이전
체크포인트는 "custom_voice"였음, `config.json`으로 실측 확인). base 타입은
generate_custom_voice()를 지원하지 않아서(모델 자체에 화자 임베딩 테이블이 없음, `spk_id={}`),
레퍼런스 음성으로 목소리를 복제하는 generate_voice_clone() 방식으로 전환했다. 레퍼런스는
`assets/kss_reference.wav`(KSS 원본 음성 000008번, `data/kss/metadata.csv` 대본과 페어) —
Qwen 공식 데모의 영어 샘플이 아니라 실제 KSS 화자 목소리를 쓰기 위해 이걸로 골랐다.

혹시 나중에 custom_voice 타입 체크포인트로 되돌아가는 경우를 대비해 그 경로도 남겨뒀다
(SPEAKER="kss_speaker" — 화자명이 "kss_speaker_a100"이 아니라 "kss_speaker"로 심어져 있었음,
2026-08-18 실측 확인). `load_tts_model()`이 로드한 모델의 `tts_model_type`을 보고 자동으로
분기한다.

private repo라 로딩에 HF_TOKEN이 필요하다(.env, HF Spaces 배포 시엔 Repository secret으로 등록).

[호출 예시]

from src.tts.infer import tts_synthesize

waveform, sample_rate = tts_synthesize("약불로 5분간 끓여주세요")
# app.py에서: st.audio(waveform, sample_rate=sample_rate)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import torch

from orchestration.db import load_env
from tts.pronunciation import apply_pronunciation_fixes

# db.py의 get_client()와 동일한 방식 — python-dotenv 없이 .env를 os.environ에 채워 넣는다.
# 아래 MODEL_ID가 이 시점의 os.environ을 바로 읽으므로, HF_TOKEN을 쓰는 load_tts_model()보다
# 먼저(모듈 import 시점에) 호출해야 한다.
load_env()

# ============================================================
# 모델 설정
# ============================================================

# .env의 HF_TTS_MODEL_REPO로 덮어쓸 수 있게 하되(.env.example.local 참고), 기본값은 확정된 모델로 고정.
MODEL_ID = os.environ.get("HF_TTS_MODEL_REPO") or "kimseunguk/qwen3-tts-kss-finetuned"


# custom_voice 타입 체크포인트로 되돌아갈 경우를 대비한 화자명("kss_speaker_a100"이 아니라
# "kss_speaker"로 심어져 있었음, 2026-08-18 실측 확인).
SPEAKER = "kss_speaker"

# base 타입 체크포인트(현재 기준, 2026-08-19)의 목소리 복제용 레퍼런스 — KSS 원본 음성.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VOICE_CLONE_REF_AUDIO = str(_ASSETS_DIR / "kss_reference.wav")
VOICE_CLONE_REF_TEXT = "나는 살아오면서 감기를 앓은 적이 한 번도 없다."  # data/kss/metadata.csv 000008



# 모델은 최초 1번만 로드하고 이후 호출에서 재사용
_model = None

# 2026-08-22 실측 추정 버그 대응 — "Cannot copy out of meta tensor; no data!" 에러가
# 실사용 중 한 번 보고됨. GPU 메모리 자체는 넉넉했다(직접 재현 시 STT+LLM+TTS 순서로
# 다 로드해도 8.4GB/12.2GB로 여유 있음) — 그래서 유력한 원인은 _warm_up_models()가
# 화면(세션)이 뜰 때마다 호출되는데, load_tts_model()엔 "이미 로딩 중"을 막는 보호가
# 없어서, 브라우저 탭이 겹치거나 새로고침이 겹치는 등으로 두 스레드가 거의 동시에
# `if _model is not None:` 검사를 통과해버리면 같은 GPU에 같은 모델을 동시에
# device_map="cuda:0"로 두 번 올리려다 한쪽이 완전히 못 끝난 상태로 뒤섞여 이 에러가
# 날 수 있다(재현은 못 했지만 코드상 이 경합 자체는 실제로 존재함). speak()의
# 실시간 합성만 직렬화하던 _TTS_LOCK과 별개로, "로딩 자체"도 한 번에 하나만 하도록
# 이 락으로 막는다.
_LOAD_LOCK = threading.Lock()

# base 타입 체크포인트일 때만 쓰는 voice-clone 프롬프트 — 레퍼런스 오디오가 고정이라 최초
# 1번만 만들고 재사용(모델 로드와 마찬가지로 매 합성마다 다시 만들 필요 없음).
_voice_clone_prompt = None


# ============================================================
# TTS 모델 로드
# ============================================================

def load_tts_model():

    global _model

    # 이미 모델이 로드되어 있으면 재사용
    if _model is not None:

        return _model

    # _LOAD_LOCK 정의부 주석 참고 — 두 스레드가 동시에 여기 들어와서 위 "이미 로드됨"
    # 검사를 둘 다 통과해버리는 경합을 막는다. 락을 기다리는 동안 다른 스레드가 이미
    # 로딩을 끝냈을 수 있으니, 락을 잡은 뒤에도 한 번 더 확인한다(이중 확인 잠금).
    with _LOAD_LOCK:

        if _model is not None:

            return _model

        from qwen_tts import Qwen3TTSModel

        # 2026-08-21: models/tts_finetuned/(프로젝트 폴더, 네트워크 드라이브 CIFS ~9MB/s)에 받아둔
        # 파인튜닝 체크포인트를 그대로 읽으면 STT(model.bin 778MB → 87초)와 같은 문제가 TTS(4.3GB라
        # 훨씬 오래 걸림)에서 재발한다. HF 캐시(이미 로컬 디스크, ~/.cache/huggingface)에서 진짜
        # 로컬 전용 경로(~/models/chefear_tts_finetuned)로 한 번 더 복사해서 그걸 최우선으로
        # 읽는다 — src/stt/infer.py의 STT_LOCAL_CACHE_DIR과 동일한 패턴.
        local_cache_dir = os.environ.get("TTS_LOCAL_CACHE_DIR")
        model_source = MODEL_ID
        use_local = False
        if local_cache_dir and Path(local_cache_dir).expanduser().exists():
            model_source = str(Path(local_cache_dir).expanduser())
            use_local = True

        token = os.environ.get("HF_TOKEN")

        if not use_local and not token:

            raise RuntimeError(
                f"HF_TOKEN이 필요함 ({MODEL_ID}는 private repo) — .env에 설정하거나 "
                "HF Spaces 배포 시엔 Repository secret으로 등록할 것"
            )


        # 2026-08-19 팀 결정(docs/decisions.md #2): CPU(HF Spaces Basic)는 목표 응답시간(5초)을
        # 못 맞춰 포기하고, 배포를 GPU 데스크탑(RTX 5070) 상시 노출(Tailscale)로 전환했다 —
        # CPU 폴백은 더 이상 배포 대상이 아니라서 없애고 GPU를 필수로 요구한다.
        if not torch.cuda.is_available():

            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2). "
                "CUDA 드라이버/torch 설치를 확인할 것."
            )

        device_map, dtype = "cuda:0", torch.bfloat16


        try:

            import flash_attn  # noqa: F401

            attn_impl = "flash_attention_2"

        except ImportError:

            attn_impl = "sdpa"


        # 2026-08-22/23 실사용 보고 — "Cannot copy out of meta tensor; no data!" 에러가
        # 반복 확인됨(재현 시도로는 원인 100% 확정 못 함 — GPU 메모리는 항상 여유
        # 있었음). accelerate가 device_map= 로딩 시 모델을 먼저 meta 디바이스에 뼈대만
        # 만들고 체크포인트에서 실제 가중치를 읽어와 채우는데, 이 과정이 일시적 이유로
        # (디스크 I/O 순간 끊김, CUDA 초기화 타이밍 등) 중간에 실패하면 일부 텐서가
        # 데이터 없이 meta로 남는다 — 근본 원인을 확정할 수 없는 만큼, 일시적 실패일
        # 가능성에 대비해 최대 2번 재시도한다. 재시도 전 torch.cuda.empty_cache()로
        # 이전 시도가 남긴 부분 할당을 정리한다.
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                _model = Qwen3TTSModel.from_pretrained(

                    model_source,

                    token=None if use_local else token,

                    device_map=device_map,

                    dtype=dtype,

                    attn_implementation=attn_impl,
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 — 재시도 대상인지 여기선 구분 안 하고 다 재시도
                last_exc = exc
                suffix = "재시도합니다." if attempt < 3 else "재시도 횟수를 다 씀."
                print(f"[TTS] 모델 로드 실패(시도 {attempt}/3): {exc!r} — {suffix}")
                torch.cuda.empty_cache()

        if last_exc is not None:
            raise last_exc

        print(f"[TTS] 모델 로드 완료: {model_source} (device={device_map}, attn={attn_impl}, local={use_local})")


        return _model


# ============================================================
# 런타임 음성 합성
# ============================================================

# qwen_tts 기본값은 max_new_tokens=2048(라이브러리 하드 디폴트) — do_sample=True(확률적
# 샘플링)와 같이 쓰이다 보니, 운이 나쁘면(멈춤 토큰을 늦게 뽑으면) 짧은 문장도 최대치까지
# 생성을 계속해서 실측상 20배 이상 느려지는 경우가 있었다(2026-08-17 확인). ChefEar는 조리
# 안내 한 문장(몇 초 분량)만 읽으면 되므로 훨씬 낮게 잡아도 충분하다.
# 170→180→190→195→200→300 순으로 실측(2026-08-19, 재료 분수 표현이 많은 긴 문장 기준) —
# 이 문장의 자연 완결 지점은 약 191토큰(15.92초)이라 200 이상이어야 안 잘린다. 195로
# 확정했다가 팀원이 195에서도 잘린다는 걸 확인해줘서 250으로 재조정(2026-08-19).
# 200/300 실측상 200 이상은 자연 완결됐으니 250도 여유 있게 안전할 것으로 판단
# (src/tts/README.md 실측 결과 ③ 참고).
# 2026-08-23: 실서비스 청취 중 250에서도 살짝 끊기는 느낌이 있다는 팀원 보고로 280으로
# 재조정. 정식 상한값별 재벤치마크(위 표처럼 토큰 사용률·완결 여부를 수치로 다시 잰 것)는
# 아직 없음 — 지어내지 않고(1.5 원칙) 청취 보고 기반의 잠정 조정이라고 남겨둔다. 더 긴
# 문장에서 또 끊긴다는 보고가 나오면 그때 실측 표를 다시 채울 것.
# 2026-08-25: 280에서도 조리 단계 안내문 끝이 살짝 잘린다는 청취 보고로 320으로 재조정.
# 여전히 정식 재벤치마크는 아님(위와 같은 잠정 조정) — 다음에 또 잘린다는 보고가 나오면
# 이번엔 값을 더 올리기보다, 실제 각 문장의 토큰 사용량을 로그로 찍어 자연 완결 지점을
# 정확히 재는 쪽으로 전환할 것(무작정 올리면 문장 시작이 늦게 들리기 시작해서 "밀린다"는
# 인상만 키운다는 2026-08-24 지적과 같은 이유).
#
# 2026-08-25 재조정 — 320에서도 재료 나열이 많은 긴 문장(예: "당근 약간, 파프리카 약간,
# 목이버섯, 부추 약간, 잡채용 돼지고기를 먹기 좋은 크기로 썰어주세요")의 끝 음절("요")이
# 살짝 잘린다는 청취 보고로 360으로 재조정.
#
# 2026-08-26 재요청 — 360도 여전히 잘리는 문장이 있다는 보고에, "고정 상수를 계속
# 찔끔찔끔 올리는" 방식 자체가 근본적으로 안 맞다는 정확한 지적을 받았다: 조리 안내
# 문장은 짧은 것("소금을 뿌려주세요")부터 긴 것(재료 나열)까지 길이가 제각각이라, 어떤
# 고정값을 골라도 "긴 문장엔 부족, 짧은 문장엔 과함"(과하면 시작이 늦게 들리는 인상만
# 커진다는 2026-08-24 기존 지적)이 항상 같이 온다. 그래서 고정 상수 대신 **문장 길이에
# 비례하는 동적 계산**으로 바꾼다 — DEFAULT_MAX_NEW_TOKENS는 이제 "문장이 아주 짧을 때의
# 최소 하한"으로만 쓰이고, 실제 상한은 매 호출마다 텍스트 길이 기준으로 계산된다.
# 글자당 배수(_TOKENS_PER_CHAR)는 정식 토크나이저 기반 실측이 아니라(그런 실측 도구가
# 아직 없음, 1.5 원칙 — 지어내지 않되 정직하게 잠정치임을 밝힘) 마지막으로 잘렸던
# 문장(위 재료 나열 예문, 약 45자)이 360 토큰으로도 부족했던 사례를 기준으로 여유
# 있게(그 사례의 실측 부족분보다 확실히 크게) 잡은 값 — 다음에 또 잘리는 보고가 나오면
# 이 배수 자체를 올릴 것.
DEFAULT_MAX_NEW_TOKENS = 400  # 아주 짧은 문장(예: "다음 단계로 가주세요")의 최소 하한
# 2026-08-26 재조정(300->400, 배수 15->20, 상한 1200->1500) — 실사용 TTS_DEBUG 로그
# 29건 전수 확인 결과, implied_tokens_per_s(초당 생성 토큰 추정)로 역산한 실제
# 소비량이 29건 *전부* 그때 상한(배수 10 기준)의 90% 이상이었다 — "여유 있게
# 잡았다"던 배수 10이 실측으론 거의 여유가 없었다는 뜻. "한 글자씩 잘려 들린다"는
# 반복 리포트와 정확히 들어맞는다. 15로 한 번 올렸는데도 계속 잘린다는 재확인으로
# 20으로 재조정 — 절대 상한도 같이 1500으로 올려서 긴 문장이 새 배수로 계산해도
# 천장에 눌리지 않게 함께 맞췄다. 정식 토크나이저 기반 실측은 아직 없음(1.5 원칙 —
# 지어내지 않되 잠정치임을 밝힘) — 이번에도 청취/로그 기반 잠정 조정이라, 다음에도
# 잘린다는 보고가 나오면 이 배수를 더 올리기보다 정식 토큰 카운트 로깅으로 전환할 것.
_TOKENS_PER_CHAR = 20  # 글자당 예상 생성 토큰 수(잠정치, 위 문서 참고) — 아래 토크나이저
# 기반 추정이 실패할 때만 쓰는 폴백으로 강등(2026-09-01, 아래 문서 참고).
_MAX_NEW_TOKENS_CEILING = 1500  # do_sample=True에서 운 나쁘게 못 멈추는 경우의 상한선
# (2026-08-19 실측: 2048 하드 디폴트에서 20배 이상 느려지는 사례가 있었음 — 상한 없이
# 문장 길이만 따라가게 두면 같은 위험이 재현될 수 있어 안전장치로 둔다.)

# 2026-09-01 — "글자수 x 20"은 처음부터 "정식 토크나이저 기반 실측이 아님"이라고 위에
# 스스로 밝혀둔 잠정치였다(청취 보고로 20까지 올라간 것). 텍스트를 실제 토크나이저로
# 인코딩해서 진짜 토큰 수를 재면 더 정확한 추정이 가능하다 — 다만 qwen_tts 라이브러리가
# Qwen3TTSModel 래퍼(model.generate_voice_clone() 등) 뒤에 정확히 어떤 토크나이저
# 객체를 어떤 속성으로 노출하는지 이 저장소에서 검증할 방법이 없다(로컬 환경엔 GPU가
# 없어 qwen_tts 자체가 설치 안 됨). 그 래퍼 내부를 추측해서 건드리는 대신, MODEL_ID의
# HF 토크나이저를 transformers.AutoTokenizer로 **독립적으로** 로드해서 길이 추정에만
# 쓴다 — generate_voice_clone()/generate_custom_voice() 호출 자체에는 아무 변경이
# 없으므로, 바로 위 2026-08-27 문서에 적힌 것과 같은 "검증 안 된 파라미터로 TTS 전체가
# 조용히 죽는" 위험이 없다(최악의 경우에도 로딩 실패 -> 아래 except가 잡아서 기존
# 글자수 추정으로 조용히 폴백할 뿐, 실제 합성 경로는 항상 그대로 동작한다).
_tts_tokenizer = None
_tts_tokenizer_load_failed = False


def _get_tts_tokenizer():
    global _tts_tokenizer, _tts_tokenizer_load_failed
    if _tts_tokenizer is not None or _tts_tokenizer_load_failed:
        return _tts_tokenizer
    try:
        from transformers import AutoTokenizer

        _tts_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    except Exception as exc:  # noqa: BLE001 — 실패하면 그냥 폴백, TTS 자체는 안 죽어야 함
        print(f"[TTS] 토크나이저 기반 길이 추정용 AutoTokenizer 로드 실패(글자수 추정으로 폴백): {exc!r}")
        _tts_tokenizer_load_failed = True
    return _tts_tokenizer


def _dynamic_max_new_tokens(text: str) -> int:
    """문장 길이에 비례해서 생성 예산을 계산한다 — 위 DEFAULT_MAX_NEW_TOKENS 문서 참고."""
    tokenizer = _get_tts_tokenizer()
    if tokenizer is not None:
        try:
            # 실제 생성은 텍스트 토큰 수보다 더 걸릴 수 있어(운율/화자 임베딩 등 TTS 특유의
            # 프레임 확장) 안전 여유를 곱해서 잡는다 — 1.3배는 정식 실측치가 아니라 보수적인
            # 잠정 배수다(위 글자수x20 배수들의 잠정치 원칙과 동일하게 여기도 명시).
            # 2026-09-01 — resolve_for_tts()로 [TERM:...] 설명 문장이 붙으면서 문장이
            # 길어졌는데, 실측(TTS_DEBUG 로그)으로 "2단계" 안내(텍스트 56자)가
            # implied_tokens_per_s × duration_s ≈ max_new_tokens(=400)로 딱 예산에
            # 맞아떨어져 끝음절이 잘리는 게 확인됐다 — 여유가 사실상 없었다는 뜻. 1.3 ->
            # 1.5로 올려서 여유를 더 준다.
            token_count = len(tokenizer(text).input_ids)
            estimated = int(token_count * 1.5)
            return min(_MAX_NEW_TOKENS_CEILING, max(DEFAULT_MAX_NEW_TOKENS, estimated))
        except Exception as exc:  # noqa: BLE001 — 인코딩 실패해도 폴백으로 계속 진행
            print(f"[TTS] 토크나이저 기반 길이 추정 실패(글자수 추정으로 폴백): {exc!r}")
    estimated = len(text) * _TOKENS_PER_CHAR
    return min(_MAX_NEW_TOKENS_CEILING, max(DEFAULT_MAX_NEW_TOKENS, estimated))


# 2026-08-27 시도했다 즉시 되돌림 — "요"처럼 끝음절이 잘린다는 리포트에 min_new_tokens
# (HF generate() 표준 파라미터)로 EOS를 늦게 허용해보려 했으나, **실제 청취 검증 없이
# 넣은 값이라고 스스로 경고했던 바로 그 위험이 현실화됐다**: 재시작 직후부터 TTS_DEBUG
# 로그가 단 한 줄도 안 찍혔다(실측 확인 — 재시작 이후 전체 로그에서 0건). speak()의
# 예외 처리가 st.warning()(화면에만 표시, 서버 콘솔엔 안 남음)이라 콘솔상으론 아무
# 흔적도 없이 TTS가 전면 침묵했다 — 로그인 안 된 상태의 "등록" 안내 음성("로그인 후
# 이용해 주세요")도 이 때문에 전혀 안 나와서 "등록 기능이 고장났다"는 리포트로 이어짐
# (사용자가 화면이 안 바뀐다고 마이크에 대고 말한 것까지 그대로 STT에 잡힘). 이
# qwen_tts 버전의 generate_voice_clone()/generate_custom_voice()이 min_new_tokens를
# 실제로 받아들이는지 검증 없이 넣은 게 원인으로 추정 — 확정 원인 조사보다 되돌리는
# 게 급선무라 바로 제거한다. 끝음절 잘림 완화는 이 방법 말고, 실제 청취로 먼저
# 검증되는 다른 방법으로 다시 시도할 것.

# do_sample=True(확률적 샘플링)라 시드 고정 없이는 같은 문장도 호출마다 결과가 달라진다
# (2026-08-19 확인: 그동안 시드 고정이 전혀 없었음). 재현 가능한 테스트/비교를 위해 매
# 합성 직전에 이 시드로 리셋한다(팀원 노트북 test_epoch1_inference2.ipynb와 동일 패턴).
DEFAULT_SEED = 42


# ============================================================
# 끝음절 볼륨 보정 (2026-09-04)
# ============================================================
# "문장 끝 음절(주로 '~요')이 작게/흐리게 발음돼 안 들린다"는 반복 리포트 대응 —
# 앞서 시도한 텍스트 힌트(tts/pronunciation.py::apply_pronunciation_fixes()의 마침표+
# 공백 추가)는 실제 청취 검증 결과 "어느 정도 효과는 있지만 완전히 고쳐지진 않음"으로
# 확인됐다(2026-09-04). 텍스트로 모델을 설득하는 방식만으로는 생성 자체의 음량/운율을
# 다 바꾸지 못하는 것으로 보여, 이번엔 생성된 파형을 직접 검사해서 고친다 — 문장 끝
# 구간의 RMS 음량이 그 앞부분보다 확연히 작으면 그 구간만 게인을 올린다.
#
# 텍스트가 아니라 실제 오디오 데이터를 바꾸는 방식이라(캐시 파일에 그대로 반영됨)
# 텍스트 힌트보다 더 직접적이지만, 이것도 아직 실제 청취 검증 전이다(1.5 원칙 — 효과를
# 지어내지 않는다). 부작용(끝만 부자연스럽게 커지거나 노이즈가 도드라짐)이 있거나
# 효과가 없으면 아래 상수부터 조정하거나 이 함수 자체를 되돌아볼 것.
_TAIL_BOOST_WINDOW_MS = 400  # 분석/부스트 대상 구간 — 끝에서부터 이만큼
_TAIL_BOOST_RAMP_MS = 60  # 경계에서 게인이 갑자기 바뀌면 클릭음이 나서, 이 구간 동안만 서서히 올린다
_TAIL_BOOST_TRIGGER_RATIO = 0.35  # 끝 구간 RMS가 앞부분 RMS의 이 비율보다 작아야 "너무 작다"고 판단
_TAIL_BOOST_TARGET_RATIO = 0.7  # 부스트 목표 = 앞부분 RMS의 이 비율까지만(완전히 맞추면 과할 수 있어 여유를 둠)
_TAIL_BOOST_MAX_GAIN = 4.0  # 무음에 가까운 구간을 노이즈까지 증폭하지 않도록 게인 상한
_TAIL_BOOST_MIN_RMS = 1e-4  # 끝 구간이 이보다도 작으면 "진짜 무음"(발화가 아님)으로 보고 손대지 않는다


def _boost_quiet_tail(
    waveform: np.ndarray, sample_rate: int
) -> tuple[np.ndarray, float | None]:
    """문장 끝 구간이 그 앞보다 확연히 작게 생성됐으면 그 구간만 게인을 올린다.

    반환값은 (보정된 파형, 적용된 게인 — 안 건드렸으면 None). 게인을 로그로 남길 수
    있게 함께 돌려준다(호출부의 [TTS_DEBUG] 참고).
    """
    n = waveform.shape[0]
    tail_samples = int(sample_rate * _TAIL_BOOST_WINDOW_MS / 1000)
    if tail_samples <= 0 or tail_samples >= n:
        return waveform, None  # 문장이 너무 짧아 앞/뒤로 나눌 수 없으면 건드리지 않는다

    tail = waveform[-tail_samples:]
    reference = waveform[:-tail_samples]

    tail_rms = float(np.sqrt(np.mean(np.square(tail))))
    reference_rms = float(np.sqrt(np.mean(np.square(reference))))

    if tail_rms < _TAIL_BOOST_MIN_RMS or reference_rms <= 0:
        return waveform, None  # 진짜 무음 — 노이즈 증폭 방지

    if tail_rms >= reference_rms * _TAIL_BOOST_TRIGGER_RATIO:
        return waveform, None  # 이미 충분히 크게 생성됨

    gain = min(_TAIL_BOOST_MAX_GAIN, (reference_rms * _TAIL_BOOST_TARGET_RATIO) / tail_rms)

    ramp_samples = min(int(sample_rate * _TAIL_BOOST_RAMP_MS / 1000), tail_samples)
    gain_curve = np.full(tail_samples, gain, dtype=np.float32)
    if ramp_samples > 0:
        gain_curve[:ramp_samples] = np.linspace(1.0, gain, ramp_samples, dtype=np.float32)
    if waveform.ndim > 1:
        gain_curve = gain_curve[:, None]

    boosted = waveform.copy()
    boosted[-tail_samples:] = tail * gain_curve
    np.clip(boosted, -1.0, 1.0, out=boosted)
    return boosted, gain


def tts_synthesize(
    text: str,
    *,
    language: str = "Korean",
    instruct: str = "",
    max_new_tokens: int | None = None,
    seed: int = DEFAULT_SEED,
    session_id: str | None = None,
) -> tuple[np.ndarray, int]:
    """조리 안내 문장 하나 -> (waveform, sample_rate).

    max_new_tokens를 안 넘기면(기본값 None) _dynamic_max_new_tokens(text)로 문장 길이에
    비례해서 자동 계산한다(위 DEFAULT_MAX_NEW_TOKENS 문서의 2026-08-26 재조정 참고) —
    호출부가 특정 값을 강제하고 싶을 때만 명시적으로 넘기면 된다(현재 이 저장소 안에서는
    그런 호출부가 없음, 전부 자동 계산에 맡김).

    호출부(app.py/pipeline.py)가 반환값을 st.audio(waveform, sample_rate=sample_rate)에
    그대로 넘기면 재생된다. 파일로 저장해야 하면 soundfile.write(path, waveform, sample_rate)를
    호출부에서 직접 쓰면 된다(이 함수는 파일 I/O를 하지 않음).

    session_id(2026-09-02 추가) — stt_transcribe()의 같은 이름 파라미터와 같은 이유
    (그쪽 문서 참고) — 순수 로그 태그, 합성 로직과는 무관.
    """

    global _voice_clone_prompt

    if max_new_tokens is None:
        max_new_tokens = _dynamic_max_new_tokens(text)

    torch.manual_seed(seed)

    if torch.cuda.is_available():

        torch.cuda.manual_seed_all(seed)

    model = load_tts_model()

    model_type = getattr(model.model, "tts_model_type", None)

    # 화면 표시/로그/DB용 원문(text)은 그대로 두고, TTS에 넘길 사본에만 발음 보정을 적용.
    tts_text = apply_pronunciation_fixes(text)

    if model_type == "base":

        # custom_voice 화자 임베딩이 없는 체크포인트 — 레퍼런스 음성으로 목소리를 복제해서 생성.
        if _voice_clone_prompt is None:

            _voice_clone_prompt = model.create_voice_clone_prompt(
                ref_audio=VOICE_CLONE_REF_AUDIO,
                ref_text=VOICE_CLONE_REF_TEXT,
            )

        wavs, sample_rate = model.generate_voice_clone(

            text=tts_text,

            language=language,

            voice_clone_prompt=_voice_clone_prompt,

            max_new_tokens=max_new_tokens,
        )

    elif model_type == "custom_voice":

        wavs, sample_rate = model.generate_custom_voice(

            text=tts_text,

            language=language,

            speaker=SPEAKER,

            instruct=instruct,

            max_new_tokens=max_new_tokens,
        )

    else:

        raise ValueError(
            f"tts_synthesize()가 아직 지원하지 않는 tts_model_type={model_type!r} "
            f"({MODEL_ID})"
        )

    # 2026-09-01 — 이 자리에 있던 매 호출마다의 torch.cuda.empty_cache() 제거.
    # orchestration/intent_classifier.py::classify_intent()의 같은 날짜 주석에 이유를
    # 자세히 적어뒀다(요약: "12GB GPU 공유, 여유 500MB 미만"이던 전제가 A40 48GB +
    # gpu_worker_pool 멀티프로세스 구조로 더 이상 유효하지 않음 — 실측: 워커당 여유
    # 약 3~4GB). empty_cache()는 CUDA 동기화를 강제하는 안티패턴이라 매 합성마다 이
    # 비용을 지불할 이유가 없다. 되돌리는 법: OOM/Queue overflow 증상 재현 시 이
    # 커밋을 되돌리거나 아래 두 줄을 복원할 것 — if torch.cuda.is_available():
    # torch.cuda.empty_cache()

    # 2026-08-26 임시 진단 — "끝 음절이 계속 잘린다"는 보고가 위 max_new_tokens를
    # 170부터 여러 번 올려도(지금은 문장 길이 비례 동적 계산으로 바꿨는데도) 계속
    # 재현된다. 고정/동적 상수를 또 찔끔 올리는 대신(같은 문서의 "다음엔 상수를
    # 더 올리기보다 실제 토큰 사용량을 재는 쪽으로 전환할 것" 참고), 매 합성마다
    # 실제 출력 길이와 예산(max_new_tokens)을 로그로 남긴다. duration_s가 budget에서
    # 계산되는 이론적 상한(qwen_tts의 25hz 코덱 기준 max_new_tokens/25초)에 바짝
    # 붙어있으면 진짜로 토큰 예산을 다 써서 잘린 것 — 이 로그로 다음에 잘리는
    # 문장이 나오면 추측 없이 바로 확정할 수 있다. 원인 확인되면 지울 것.
    waveform, tail_boost_gain = _boost_quiet_tail(wavs[0], sample_rate)

    duration_s = len(waveform) / sample_rate
    print(
        f"[TTS_DEBUG] sid={session_id} text_len={len(text)} max_new_tokens={max_new_tokens} "
        f"duration_s={duration_s:.2f} implied_tokens_per_s={max_new_tokens / duration_s:.1f} "
        f"tail_boost_gain={tail_boost_gain} "
        f"text={text[-15:]!r}(끝부분)",
        flush=True,
    )

    return waveform, sample_rate
