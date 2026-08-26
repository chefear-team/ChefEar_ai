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
_TOKENS_PER_CHAR = 20  # 글자당 예상 생성 토큰 수(잠정치, 위 문서 참고)
_MAX_NEW_TOKENS_CEILING = 1500  # do_sample=True에서 운 나쁘게 못 멈추는 경우의 상한선
# (2026-08-19 실측: 2048 하드 디폴트에서 20배 이상 느려지는 사례가 있었음 — 상한 없이
# 문장 길이만 따라가게 두면 같은 위험이 재현될 수 있어 안전장치로 둔다.)


def _dynamic_max_new_tokens(text: str) -> int:
    """문장 길이에 비례해서 생성 예산을 계산한다 — 위 DEFAULT_MAX_NEW_TOKENS 문서 참고."""
    estimated = len(text) * _TOKENS_PER_CHAR
    return min(_MAX_NEW_TOKENS_CEILING, max(DEFAULT_MAX_NEW_TOKENS, estimated))


# 2026-08-27 추가 — "요"처럼 끝음절이 잘려 들린다는 반복 리포트를 TTS_DEBUG 로그로
# 재분석한 결과, max_new_tokens(예산)는 원인이 아니었다(실사용 17건 전부 예산의
# 20~35%만 쓰고 스스로 멈춤 — duration_s를 qwen_tts 25Hz 코덱 기준으로 역산하면
# 실제 소비량은 글자당 약 4.2토큰뿐, _TOKENS_PER_CHAR=20의 1/5도 안 됨). "끊기는
# 지점이 항상 끝"이라는 패턴(리포트로 재확인)은 화면 rerun이 재생을 끊는 것과도 안
# 맞다(TTS_DEBUG 직후 재연결/rerun 신호를 찾아봤지만 17건 중 0건) — 자동회귀 TTS가
# EOS를 텍스트 끝 도달 기준으로 살짝 이르게 판단해, 마지막 음소의 코덱 프레임이
# 완전히 디코드되기 전에 멈추는 흔한 현상으로 추정된다. HF generate() 표준 파라미터인
# min_new_tokens(적어도 이만큼은 강제로 더 생성)로 EOS를 조금 늦게 허용해서 완화를
# 시도한다 — 실측 평균(4.2/char)보다 약간 높게 잡아, 이미 멈추던 지점보다는 몇 스텝
# 더 나가되 필요 이상으로 강제하진 않는다(너무 높이면 문장이 끝난 뒤 불필요한
# 잡음/침묵이 붙을 위험). **실제 청취 검증 없이 넣은 값이다** — 이 프로젝트 특성상
# 텍스트/로그만으로는 "끝 음절이 살아났는지"를 확인할 수 없으므로, 사람이 직접 듣고
# 확인 전까지는 잠정치로 취급할 것. 오히려 어색해지면 이 하한부터 낮출 것.
_MIN_TOKENS_PER_CHAR = 5


def _dynamic_min_new_tokens(text: str, max_new_tokens: int) -> int:
    """실측 평균(글자당 ~4.2토큰)보다 살짝 높은 하한을 계산한다 — 위 문서 참고.
    max_new_tokens(예산)를 절대 넘지 않도록 방어적으로 clamp한다."""
    estimated = len(text) * _MIN_TOKENS_PER_CHAR
    return min(max_new_tokens, estimated)

# do_sample=True(확률적 샘플링)라 시드 고정 없이는 같은 문장도 호출마다 결과가 달라진다
# (2026-08-19 확인: 그동안 시드 고정이 전혀 없었음). 재현 가능한 테스트/비교를 위해 매
# 합성 직전에 이 시드로 리셋한다(팀원 노트북 test_epoch1_inference2.ipynb와 동일 패턴).
DEFAULT_SEED = 42


def tts_synthesize(
    text: str,
    *,
    language: str = "Korean",
    instruct: str = "",
    max_new_tokens: int | None = None,
    seed: int = DEFAULT_SEED,
) -> tuple[np.ndarray, int]:
    """조리 안내 문장 하나 -> (waveform, sample_rate).

    max_new_tokens를 안 넘기면(기본값 None) _dynamic_max_new_tokens(text)로 문장 길이에
    비례해서 자동 계산한다(위 DEFAULT_MAX_NEW_TOKENS 문서의 2026-08-26 재조정 참고) —
    호출부가 특정 값을 강제하고 싶을 때만 명시적으로 넘기면 된다(현재 이 저장소 안에서는
    그런 호출부가 없음, 전부 자동 계산에 맡김).

    호출부(app.py/pipeline.py)가 반환값을 st.audio(waveform, sample_rate=sample_rate)에
    그대로 넘기면 재생된다. 파일로 저장해야 하면 soundfile.write(path, waveform, sample_rate)를
    호출부에서 직접 쓰면 된다(이 함수는 파일 I/O를 하지 않음).
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

    # 2026-08-27 추가 — 끝음절 조기종료(EOS) 완화 시도, _dynamic_min_new_tokens() 문서 참고.
    min_new_tokens = _dynamic_min_new_tokens(tts_text, max_new_tokens)

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

            min_new_tokens=min_new_tokens,
        )

    elif model_type == "custom_voice":

        wavs, sample_rate = model.generate_custom_voice(

            text=tts_text,

            language=language,

            speaker=SPEAKER,

            instruct=instruct,

            max_new_tokens=max_new_tokens,

            min_new_tokens=min_new_tokens,
        )

    else:

        raise ValueError(
            f"tts_synthesize()가 아직 지원하지 않는 tts_model_type={model_type!r} "
            f"({MODEL_ID})"
        )

    # 2026-08-25 — src/stt/infer.py::stt_transcribe()와 같은 이유(그쪽 주석 참고) — STT/
    # LLM/TTS/임베딩이 12GB GPU를 같이 써서 유휴 상태에도 VRAM 여유가 500MB 미만이다.
    # 가중치는 그대로 두고(재로딩 없음) 이번 합성이 남긴 미사용 캐시만 반환한다.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # 2026-08-26 임시 진단 — "끝 음절이 계속 잘린다"는 보고가 위 max_new_tokens를
    # 170부터 여러 번 올려도(지금은 문장 길이 비례 동적 계산으로 바꿨는데도) 계속
    # 재현된다. 고정/동적 상수를 또 찔끔 올리는 대신(같은 문서의 "다음엔 상수를
    # 더 올리기보다 실제 토큰 사용량을 재는 쪽으로 전환할 것" 참고), 매 합성마다
    # 실제 출력 길이와 예산(max_new_tokens)을 로그로 남긴다. duration_s가 budget에서
    # 계산되는 이론적 상한(qwen_tts의 25hz 코덱 기준 max_new_tokens/25초)에 바짝
    # 붙어있으면 진짜로 토큰 예산을 다 써서 잘린 것 — 이 로그로 다음에 잘리는
    # 문장이 나오면 추측 없이 바로 확정할 수 있다. 원인 확인되면 지울 것.
    duration_s = len(wavs[0]) / sample_rate
    print(
        f"[TTS_DEBUG] text_len={len(text)} max_new_tokens={max_new_tokens} "
        f"duration_s={duration_s:.2f} implied_tokens_per_s={max_new_tokens / duration_s:.1f} "
        f"text={text[-15:]!r}(끝부분)",
        flush=True,
    )

    return wavs[0], sample_rate
