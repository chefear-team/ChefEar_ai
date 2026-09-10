"""테스트 전용 supabase-py 대역(가짜 객체, 흔히 "테스트 더블(test double)"이라고 부름)."""
from orchestration.mock_client import (  # noqa: F401 (테스트 파일들이 이 이름으로 import함)
    FakeQuery,
    FakeResult,
    FakeSupabaseClient,
    FakeTable,
)
