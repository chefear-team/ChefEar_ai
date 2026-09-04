"""Streamlit 서버를 띄우기 전에, 같은 프로세스 안에서 GPU 워커 풀 워밍업을
백그라운드 스레드로 먼저 시작해두는 진입점 래퍼.

배경(2026-09-04) — src/app.py::_start_model_warmup()은 Streamlit이 세션을
시작해야만(=브라우저가 실제로 접속해야만) main()이 실행되면서 같이 실행되는
코드다. Pod만 Start하고 아무도 접속 안 하면 컨테이너가 아무리 오래 떠있어도
모델을 안 받는다는 걸 실측 확인했다(부팅 후 20초+ 지나도 [gpu_worker_pool]
로그 0건). "자기 자신에게 curl 요청 보내기"도 시도해봤지만 그것도 안 됐다
(Streamlit의 실제 스크립트 실행은 브라우저 쪽 JS가 여는 WebSocket 세션이 있어야만
일어나는 것으로 보임 — 두 번의 실측으로 확인, Streamlit이 공식 문서화한 내용은
아님, 1.5 원칙).

해결책 — gpu_worker_pool.warm_pool()은 Streamlit/세션 상태(`st.*`)를 전혀 안
건드리는 순수 코드라서, Streamlit이 뜨기 *전에* 이 프로세스 안에서 먼저
백그라운드 스레드로 불러도 안전하다. gpu_worker_pool._pool은 프로세스 전역
싱글턴(이중 확인 락, get_pool() 문서 참고)이라서, 나중에 실제로 누가 접속해서
app.py::main()이 _start_model_warmup()을 호출해도(그 안에서 warm_pool()이
다시 불려도) 이미 만들어진(또는 만들어지는 중인) 같은 풀을 그대로 재사용한다
— 중복 로딩이나 GPU 메모리 낭비 없음. 별도 파이썬 프로세스로 미리 띄워보는
방법은(더 먼저 시도했던 방향) 안 된다 — 그 프로세스가 끝나면 거기서 만든
워커들도 같이 죽어서, 나중에 Streamlit 프로세스가 쓸 수 없다(별개 프로세스라
`_pool` 전역변수를 못 공유함). 그래서 반드시 "Streamlit을 실행하는 바로 그
프로세스" 안에서, Streamlit 자신을 실행하기 직전에 이 스레드를 띄워야 한다
— 이 파일이 그 역할을 한다. entrypoint.sh가 `python -m streamlit run
src/app.py` 대신 이 스크립트를 실행한다.

`if __name__ == "__main__":` 가드가 중요하다 — warm_pool()이 내부적으로
ProcessPoolExecutor(mp_context=spawn)로 워커 3개를 띄우는데, spawn 방식은
안전하게도 자식 프로세스에서 이 가드 밖의 코드만 재실행하고 가드 안쪽은
건너뛴다(멀티프로세싱 표준 관례) — 가드 없이 짜면 자식 프로세스마다 워밍업
스레드와 Streamlit 서버를 또 띄우려는 무한 재귀 위험이 있다.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = str(_PROJECT_ROOT / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


def _warm_up_in_background() -> None:
    try:
        from orchestration.gpu_worker_pool import warm_pool

        print("[prewarm] Streamlit 뜨기 전, 같은 프로세스에서 GPU 워커 풀 워밍업 시작", flush=True)
        warm_pool()
        print("[prewarm] GPU 워커 풀 워밍업 완료", flush=True)
    except Exception as exc:  # noqa: BLE001 — 워밍업 실패해도 Streamlit 자체는 떠야 한다(EC-05와 같은 정신)
        print(f"[prewarm] GPU 워커 풀 워밍업 실패(무시하고 계속): {exc!r}", flush=True)


def _main() -> None:
    threading.Thread(target=_warm_up_in_background, daemon=True).start()

    # ---- Streamlit 서버 시작(이 프로세스가 그대로 서버가 된다) ----
    # `python -m streamlit run src/app.py`와 완전히 같은 경로다(streamlit의
    # 콘솔 스크립트 진입점 자체가 이 main()을 부르는 얇은 래퍼라서) — 여기서는
    # 그 호출 직전에 위 워밍업 스레드만 하나 끼워 넣은 것뿐이다.
    import streamlit.web.cli as stcli

    sys.argv = ["streamlit", "run", str(_PROJECT_ROOT / "src" / "app.py")]
    sys.exit(stcli.main())


if __name__ == "__main__":
    _main()
