"""GPU 추론 요청을 처리하는 멀티프로세스 워커 풀."""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = str(PROJECT_ROOT / "src")


def _ensure_pythonpath() -> None:
    """워커(spawn된 자식 프로세스)가 orchestration/stt/tts/llm 등을 import할 수 있게
    PYTHONPATH에 src/를 넣는다. 풀을 만들기 전(=아직 자식 프로세스가 없을 때)에
    반드시 먼저 불러야 한다 — 이미 뜬 워커에는 영향 없다."""
    current = os.environ.get("PYTHONPATH", "")
    parts = current.split(os.pathsep) if current else []
    if _SRC_DIR not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([_SRC_DIR, *parts]) if parts else _SRC_DIR
    # 이 모듈 자신이 부모 프로세스에서 이미 import돼서 실행 중이라는 뜻은 sys.path에도
    # src/가 있다는 뜻이지만(app.py가 이미 넣어둠), 혹시 이 모듈을 다른 진입점에서
    # 단독으로 쓸 경우를 대비해 방어적으로 한 번 더 넣는다.
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)


_ensure_pythonpath()


# ============================================================
# 워커 프로세스 초기화 — 워커가 뜨자마자 4개 모델을 전부 자기 GPU 메모리에 로드
# ============================================================

def _init_worker() -> None:
    """워커 프로세스가 처음 뜰 때(ProcessPoolExecutor의 initializer) 딱 한 번 실행된다.

    여기서 4개 모델을 미리 로드해두면, 이후 이 워커로 오는 모든 작업은 모델이 이미
    GPU에 상주한 상태로 처리된다(요청마다 로드하지 않음) — src/app.py의
    _start_model_warmup()과 같은 순서(STT -> TTS -> LLM -> 임베딩 -> 요리명 캐시)로
    맞춰서 워밍업 로그를 비교하기 쉽게 한다. spawn된 자식이라 이 함수 맨 앞에서도
    PYTHONPATH/sys.path를 다시 한번 확인한다(모듈 top-level의 _ensure_pythonpath()가
    이 자식 프로세스에서도 import 시점에 다시 실행되긴 하지만, 방어적으로 명시).
    """
    _ensure_pythonpath()
    worker_id = os.getpid()
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) 모델 로딩 시작...", flush=True)

    from stt.infer import load_ct2_model

    load_ct2_model()
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) STT 로딩 완료", flush=True)

    from tts.infer import load_tts_model

    load_tts_model()
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) TTS 로딩 완료", flush=True)

    from llm.infer import load_llm

    load_llm()
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) LLM 로딩 완료", flush=True)

    from orchestration.intent_classifier import _get_model as _load_embed_model

    _load_embed_model()
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) 임베딩 로딩 완료", flush=True)

    from orchestration.db import get_client
    from orchestration.recipe_search import _all_dish_names

    _all_dish_names(get_client())
    print(f"[gpu_worker_pool] 워커(pid={worker_id}) 요리명 캐시 워밍업 완료 — 준비됨", flush=True)


# ============================================================
# 워커 프로세스 안에서 실제로 실행되는 함수들
# (ProcessPoolExecutor.submit()에 넘길 대상은 pickle로 참조되므로 반드시 모듈
#  top-level 함수여야 한다 — 클로저/람다/메서드는 안 됨)
# ============================================================

def _worker_stt_transcribe(
    audio, *, sample_rate, ingredient_context=None, vad_filter=True, session_id=None
):
    from stt.infer import stt_transcribe

    return stt_transcribe(
        audio,
        sample_rate=sample_rate,
        ingredient_context=ingredient_context,
        vad_filter=vad_filter,
        session_id=session_id,
    )


def _worker_tts_synthesize(text: str, session_id=None):
    from tts.infer import tts_synthesize

    return tts_synthesize(text, session_id=session_id)


def _worker_extract_intent_llm(utterance: str) -> dict:
    from orchestration.entity_extract_llm import extract_intent_llm

    return extract_intent_llm(utterance)


def _worker_handle_utterance(
    session: dict,
    utterance: str,
    *,
    dish_name,
    steps,
    owner_id=None,
    registration_step=None,
    registration_value=None,
) -> dict:
    # client를 안 넘긴다 — orchestration.pipeline.handle_utterance()는 client=None이면
    # 내부에서 `client = client or get_client()`로 알아서 채운다(pipeline.py 확인됨).
    # get_client()는 db.py에서 @lru_cache 프로세스 싱글턴이라, 이 워커 프로세스
    # 안에서는 항상 이 워커 자신의 Supabase 클라이언트를 재사용한다 — 메인 프로세스의
    # client 객체를 프로세스 경계 너머로 pickle해서 넘기지 않는다(그럴 필요도 없고,
    # supabase 클라이언트는 애초에 pickle 가능하다는 보장도 없음).
    # registration_step/value를 안 받으면 워커 경로의 등록 턴은 항상 ValueError로
    # 실패한다 — dispatch가 등록 의도를 워커로 보낼 때 owner_id와 함께 전달한다.
    from orchestration.pipeline import handle_utterance

    return handle_utterance(
        session,
        utterance,
        dish_name=dish_name,
        registration_step=registration_step,
        registration_value=registration_value,
        steps=steps,
        owner_id=owner_id,
    )


# ============================================================
# 풀 싱글턴 — 프로세스(=Streamlit 서버) 전체에서 딱 하나만 존재
# ============================================================

GPU_WORKER_COUNT = int(os.environ.get("GPU_WORKER_COUNT", "3"))

_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def get_pool() -> ProcessPoolExecutor:
    """프로세스 전역에서 딱 하나만 존재하는 워커 풀을 돌려준다(지연 생성 + 이중 확인 락).

    Streamlit은 세션(브라우저 탭)마다 스크립트를 처음부터 다시 실행하지만, 이 함수는
    그때마다 새 풀을 만들지 않는다 — 모듈 레벨 전역 _pool이 이미 있으면 그대로
    재사용한다(app.py::_start_model_warmup()이 세션마다 불려도 실제 모델 로딩은
    1회뿐이던 기존 이중 확인 잠금 패턴과 같은 원칙 — stt/infer.py의 _LOAD_LOCK 등
    참고).
    """
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        _ensure_pythonpath()
        ctx = mp.get_context("spawn")
        _pool = ProcessPoolExecutor(
            max_workers=GPU_WORKER_COUNT,
            mp_context=ctx,
            initializer=_init_worker,
        )
        print(f"[gpu_worker_pool] 풀 생성됨 — 워커 {GPU_WORKER_COUNT}개 기동 시작", flush=True)
        return _pool


def _reset_pool() -> None:
    """풀을 강제로 버린다 — 다음 get_pool() 호출이 새 풀을 만들게 한다."""
    global _pool
    with _pool_lock:
        old_pool, _pool = _pool, None
    if old_pool is not None:
        try:
            old_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001 — 이미 broken인 풀 정리 실패는 무시
            pass


def _submit_with_recovery(fn, /, *args, **kwargs) -> Future:
    """get_pool().submit()이 BrokenProcessPool로 실패하면 풀을 한 번 새로 만들어서
    재시도한다 — submit_stt/submit_tts 등 공개 함수가 전부 이걸 거친다.

    재시도로 만들어진 새 풀은 워커가 모델을 처음부터 다시 로드해야 해서(수십 초~
    1분대) 복구 직후 첫 요청은 느릴 수 있다 — 그래도 컨테이너 재시작(수 분,
    Cloudflare 터널 재연결까지 포함) 없이 서비스가 알아서 회복된다는 게 핵심.
    두 번째 시도까지 실패하면(풀 생성 자체가 안 되는 등 더 심각한 문제) 그대로
    예외를 올려서 호출부(voice_io.py 등)의 기존 try/except가 처리하게 둔다 —
    무한 재시도는 하지 않는다.
    """
    try:
        return get_pool().submit(fn, *args, **kwargs)
    except BrokenProcessPool:
        print("[gpu_worker_pool] 풀이 broken 상태로 확인됨 — 새 풀로 재생성 후 재시도", flush=True)
        _reset_pool()
        return get_pool().submit(fn, *args, **kwargs)


def warm_pool() -> None:
    """풀을 만들고, 모든 워커가 최소 한 번씩 초기화를 마칠 때까지 기다린다.

    app.py의 앱 기동 시점에 (기존 _start_model_warmup()이 하던 것처럼) 한 번 불러서
    미리 데워두는 용도 — 안 불러도 get_pool()이 지연 생성하지만, 그러면 첫 사용자
    요청이 워커 기동(모델 로딩, 수십 초)까지 떠안게 된다.
    """
    pool = get_pool()
    # 워커 수만큼 아무 일도 안 하는 작업을 던져서, 모든 워커가 실제로 뜨고
    # initializer(_init_worker, 모델 로딩)를 끝낼 때까지 기다린다. ProcessPoolExecutor는
    # 작업을 유휴 워커에 분배하므로, 워커 수만큼 동시에 던지면 보통 워커마다 하나씩
    # 골고루 돌아간다(완전히 보장되진 않지만, 어차피 각 워커는 처음 뜰 때 initializer가
    # 무조건 먼저 실행되므로 이 "웜업 작업"들이 어느 워커에 몰리든 상관없다 — 목적은
    # "적어도 GPU_WORKER_COUNT개의 워커가 떴다"는 것 자체를 기다리는 것).
    futures = [pool.submit(_noop) for _ in range(GPU_WORKER_COUNT)]
    for fut in futures:
        fut.result()


def _noop() -> None:
    return None


# ============================================================
# 호출부(voice_io.py/dispatch.py/admin_auth.py)가 쓰는 공개 함수
# ============================================================

def submit_stt(
    audio, *, sample_rate, ingredient_context=None, vad_filter=True, session_id=None
) -> Future:
    return _submit_with_recovery(
        _worker_stt_transcribe,
        audio,
        sample_rate=sample_rate,
        ingredient_context=ingredient_context,
        vad_filter=vad_filter,
        session_id=session_id,
    )


def submit_tts(text: str, session_id: str | None = None) -> Future:
    return _submit_with_recovery(_worker_tts_synthesize, text, session_id=session_id)


def submit_llm_extract(utterance: str) -> Future:
    return _submit_with_recovery(_worker_extract_intent_llm, utterance)


def submit_handle_utterance(
    session: dict,
    utterance: str,
    *,
    dish_name,
    steps,
    owner_id=None,
    registration_step=None,
    registration_value=None,
) -> Future:
    return _submit_with_recovery(
        _worker_handle_utterance,
        session,
        utterance,
        dish_name=dish_name,
        steps=steps,
        owner_id=owner_id,
        registration_step=registration_step,
        registration_value=registration_value,
    )
