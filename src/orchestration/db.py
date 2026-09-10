"""Supabase 클라이언트를 만드는 공용 헬퍼."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# 이 파일(db.py) 위치 기준으로 프로젝트 루트를 계산한다.
# db.py는 <루트>/src/orchestration/db.py에 있으므로 parents[2]가 <루트>다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env(env_path: Path | None = None) -> None:
    """.env 파일을 읽어서 os.environ에 채워 넣는다.

    보통은 python-dotenv 같은 라이브러리를 쓰지만, 이 프로젝트 requirements에는
    없는 패키지라 새로 추가하지 않고 간단하게 직접 파싱했다. .env 형식은
    "KEY=VALUE" 한 줄씩이고, #으로 시작하는 줄은 주석으로 무시한다.

    os.environ.setdefault()를 쓰는 이유: 이미 셸/시스템에 같은 이름의 환경변수가
    설정돼 있으면 그 값을 존중하고, .env 값으로 덮어쓰지 않기 위해서다.
    """
    env_path = env_path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return  # .env가 아직 없으면 조용히 넘어간다(예: dry-run 모드에서는 필요 없음)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@lru_cache(maxsize=1)
def _mock_client_singleton():
    """가짜 클라이언트를 프로세스당 딱 한 번만 만들어서 재사용한다.

    @lru_cache가 없으면 get_client()를 부를 때마다 매번 새 가짜 클라이언트가
    새로 만들어져서, 예를 들어 save_recipe()로 방금 저장한 가짜 레시피를
    바로 다음 select_standard_recipe() 호출에서 못 찾는 문제가 생긴다(서로
    다른 두 개의 빈 메모리를 보는 셈이 되므로). 캐시로 "이 프로세스가 살아있는
    동안은 항상 같은 가짜 DB"를 보장한다.
    """
    from orchestration.mock_client import build_mock_client

    print(
        "[MOCK MODE] SUPABASE_URL/SUPABASE_KEY가 없어서 가짜 데이터로 동작 중입니다. "
        "실제 DB가 아닙니다 — .env에 자격증명을 채우면 자동으로 진짜 Supabase로 전환됩니다."
    )
    return build_mock_client()


@lru_cache(maxsize=1)
def _real_client_singleton(url: str, key: str):
    """진짜 Supabase 클라이언트를 (url, key) 조합당 딱 한 번만 만들어서 재사용한다
    ( _mock_client_singleton과 똑같은 이유, 아래 get_client의
    예전 동작과 비교 참고).
    """
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    return create_client(
        url,
        key,
        options=SyncClientOptions(postgrest_client_timeout=8, storage_client_timeout=8),
    )


def get_client(allow_mock: bool = True):
    """.env에서 SUPABASE_URL/SUPABASE_KEY를 읽어 실제 Supabase 클라이언트를 만든다."""
    load_env()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if url and key:
        return _real_client_singleton(url, key)

    if not allow_mock:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY가 .env에 없음")

    return _mock_client_singleton()
