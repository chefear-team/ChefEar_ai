"""ChefEar 로컬 LLM - 발화에서 요리명을 뽑기 위한 EXAONE 추론."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import torch

from orchestration.db import load_env

load_env()

MODEL_ID = os.environ.get("LLM_MODEL_REPO") or "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"

MODEL_REVISION = os.environ.get("LLM_MODEL_REVISION") or "e949c91dec92095908d34e6b560af77dd0c993f8"

LLM_LOCAL_CACHE_DIR = os.environ.get("LLM_LOCAL_CACHE_DIR")

DEFAULT_MAX_NEW_TOKENS = 128

_model = None
_tokenizer = None

_LOAD_LOCK = threading.Lock()


def load_llm():
    """EXAONE 모델/토크나이저를 최초 1번만 로드하고 이후 호출에서 재사용한다.

    tts/infer.py의 load_tts_model()과 같은 지연 로드 + 전역 캐시 패턴 — 앱이 뜰 때마다
    매번 몇 GB짜리 가중치를 다시 읽지 않게 한다.
    """
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    # _LOAD_LOCK 정의부 주석 참고 — 락을 기다리는 동안 다른 스레드가 이미 로딩을
    # 끝냈을 수 있으니, 락을 잡은 뒤에도 한 번 더 확인한다(이중 확인 잠금).
    with _LOAD_LOCK:
        if _model is not None:
            return _model, _tokenizer

        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError(
                "GPU(CUDA)가 필요합니다 — 배포 방향이 GPU 전용으로 확정됨(docs/decisions.md #2)."
            )
        device_map, dtype = "cuda:0", torch.bfloat16

        model_source = MODEL_ID
        revision = MODEL_REVISION
        if LLM_LOCAL_CACHE_DIR:
            # expanduser() 필수 — STT_LOCAL_CACHE_DIR과 같은 이유(계정마다 다른 로컬 경로를
            # .env에 "~/..."로 적어두고 계정별 $HOME 기준으로 풀리게 한다).
            local_cache = Path(LLM_LOCAL_CACHE_DIR).expanduser()
            if local_cache.exists():
                model_source, revision = str(local_cache), None

        _tokenizer = AutoTokenizer.from_pretrained(model_source, revision=revision, trust_remote_code=True)

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                _model = AutoModelForCausalLM.from_pretrained(
                    model_source,
                    revision=revision,
                    trust_remote_code=True,
                    device_map=device_map,
                    dtype=dtype,
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 — 재시도 대상인지 안 가리고 다 재시도
                last_exc = exc
                suffix = "재시도합니다." if attempt < 3 else "재시도 횟수를 다 씀."
                print(f"[LLM] 모델 로드 실패(시도 {attempt}/3): {exc!r} — {suffix}")
                torch.cuda.empty_cache()

        if last_exc is not None:
            raise last_exc

        print(f"[LLM] 모델 로드 완료: {model_source} (device={device_map})")
        return _model, _tokenizer


def generate_response(prompt: str, *, max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS) -> str:
    """프롬프트 하나를 EXAONE에 넣고, 새로 생성된 부분만(입력 프롬프트 제외) 텍스트로 돌려준다."""
    model, tokenizer = load_llm()

    input_ids = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=False,  # 요리명 추출은 매번 같은 답이 나와야 하는 태스크라 그리디 디코딩
        )

    generated = output_ids[0][input_ids.shape[-1]:]
    result = tokenizer.decode(generated, skip_special_tokens=True).strip()


    return result


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """EXAONE이 JSON을 마크다운 코드펜스(```json ... ```)로 감싸서 답하는 경우가 실측으로
    확인됐다 —
    json.loads 전에 펜스를 벗겨낸다. 코드펜스가 없는 순수 JSON 응답도 그대로 통과시킨다.
    """
    text = text.strip()
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def generate_json(prompt: str, *, max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS) -> dict | None:
    """generate_response()의 결과를 JSON dict로 파싱한다.

    모델 로드/추론 자체가 실패하면(GPU 메모리 부족, 모델 파일 없음 등) 예외를 그대로
    올린다 — 이건 설정 문제라 개발 중엔 바로 보이는 게 낫다. 반면 모델이 응답은 했는데
    JSON 형식을 안 지켰을 때는 예외 없이 None을 돌려준다 — 호출부(entity_extract_llm.py)가
    "요리명 없음"과 똑같이 처리해서 서비스가 죽지 않게 하기 위해서다(EC-03).
    """
    raw_text = generate_response(prompt, max_new_tokens=max_new_tokens)
    try:
        parsed = json.loads(_strip_code_fence(raw_text))
    except json.JSONDecodeError:
        print(f"[LLM] 모델 응답이 JSON 형식이 아님: {raw_text!r}")
        return None
    if not isinstance(parsed, dict):
        print(f"[LLM] 모델 응답이 JSON 객체가 아님(dict 아님): {parsed!r}")
        return None
    return parsed
