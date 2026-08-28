"""Supabase 클라이언트를 만드는 공용 헬퍼.

이 프로젝트는 SQL 함수(RPC)를 쓰지 않고 supabase-py가 제공하는 필터 API
(.eq(), .ilike() 등)만 사용하기로 했다(문서 8.1, OI-08 — 팀에 SQL 미숙련자가
있어서 "복잡한 SQL 대신 Python에서 조건을 조립하자"는 방향). 그래서 recipe_search.py,
pipeline.py 같은 다른 orchestration 모듈들이 전부 이 파일의 get_client()를 불러서
쓰고, DB 연결 관련 코드는 여기 한 곳에만 모아둔다(중복 방지).

## 강사 체크리스트 4번: 백엔드 골격 + 가짜(mock) 응답

Supabase 프로젝트 자격증명(.env의 SUPABASE_URL/SUPABASE_KEY)이 아직 없어도
오케스트레이션 함수들이 그냥 죽어버리지 않게, get_client()가 자동으로
mock_client.py의 가짜 클라이언트로 대체해준다(아래 get_client() 참고).
자격증명이 준비되는 순간(.env에 값이 채워지는 순간) 코드 수정 없이 자동으로
진짜 Supabase로 전환된다.
"""
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
    (2026-08-26 수정 — _mock_client_singleton()과 똑같은 이유, 아래 get_client()의
    예전 동작과 비교 참고).

    예전엔 get_client()가 매번 create_client(url, key)를 새로 호출해서, 호출할 때마다
    완전히 다른 client 객체를 돌려주고 있었다. 그런데 recipe_search.py::_all_dish_names()/
    _decomposed_name_map()이 "같은 client 객체로 다시 부르면 캐시 히트"라는 전제로
    @lru_cache(client를 캐시 키로 씀)를 걸어둔 상태라(그 문서의 "12~18초 걸려서" 설명
    참고), client 객체가 매번 바뀌면 그 캐시가 매번 무조건 미스나서 사실상 아무 효과가
    없었다 — 실측 리포트("DB에도 없는 메뉴를 말하면 로딩바가 엄청 오래 돈다", extract_dish_name()
    이 dish_name 추출 실패 시 타는 편집거리 폴백 경로에서 매번 6만여 건 전체 페이지네이션
    조회를 처음부터 다시 하고 있었던 것)로 확정됐다. 이 함수로 client 자체를 프로세스당
    하나만 만들어 재사용하면, _all_dish_names()의 캐시가 실제로 히트하게 된다 — 최초
    1회(여전히 12~18초)만 느리고 그 뒤로는 즉시 반환된다.
    """
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    # 2026-08-28 — 타임아웃을 명시한다. 기본값으로는 Supabase가 느리거나 응답이 안 올 때
    # 조회 호출이 무한정 매달려서(예외도 안 나므로 dispatch.py::_compute()의 network_error
    # 폴백도 안 걸린다) "처리 중" 로딩이 영영 안 끝나는 상태가 된다. 8초를 넘기면 예외를
    # 던지게 해서, 그 예외를 _compute()가 잡아 "일시적인 오류" 안내로 폴백하게 한다.
    # (create_client는 SyncClientOptions를 요구한다 — base ClientOptions는 .storage 속성이
    # 없어 AttributeError.)
    return create_client(
        url,
        key,
        options=SyncClientOptions(postgrest_client_timeout=8, storage_client_timeout=8),
    )


def get_client(allow_mock: bool = True):
    """.env에서 SUPABASE_URL/SUPABASE_KEY를 읽어 실제 Supabase 클라이언트를 만든다.

    자격증명이 없을 때:
      - allow_mock=True(기본값): mock_client.py의 가짜 클라이언트를 대신 돌려준다
        (강사 체크리스트 4번 "백엔드 골격 — 가짜 응답 먼저"). recipe_search.py 등
        일반 조회/등록 로직은 이 기본값을 그대로 쓴다.
      - allow_mock=False: 예외를 던진다. load_data.py처럼 "진짜로 대량의 실데이터를
        저장하는" 작업은 가짜 메모리에 조용히 적재해봐야 아무 의미가 없고 오히려
        "적재 성공했다"는 착각만 주므로, 반드시 진짜 DB가 있어야만 실행되게 막는다.

    supabase import를 함수 안에서 하는 이유: 이 함수를 호출하지 않는 코드
    (예: classify_intent()만 쓰는 테스트)에서는 supabase 패키지가 없어도 되게
    하기 위해서다(모듈 최상단에서 import하면 그 모듈을 쓰는 모든 곳이 supabase
    패키지를 강제로 요구하게 된다).
    """
    load_env()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if url and key:
        return _real_client_singleton(url, key)

    if not allow_mock:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY가 .env에 없음")

    return _mock_client_singleton()
