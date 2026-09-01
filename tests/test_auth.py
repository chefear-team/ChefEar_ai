"""auth.py 테스트 — docs/specs/user_accounts_google_login.md AC-01~03, EC-01."""
import hashlib

import pytest
from fake_supabase import FakeSupabaseClient

from orchestration.auth import (
    SignupError,
    account_id_from_google_sub,
    account_id_from_username,
    clear_session_token,
    create_session_token,
    hash_password,
    login_local,
    login_or_create_google,
    resolve_session_token,
    signup_local,
    verify_password,
)


def _row_by_hash(client, uid: str) -> dict:
    """users.user_id_hash로 직접 행을 찾는다 — FakeTable.rows는 (mock_client.py의
    범용 insert() 로직상) "id"라는 이름의 컬럼이 없으면 무작위 키로 저장하므로,
    user.id로 client.table("users").rows[...]를 바로 인덱싱할 수 없다."""
    return next(r for r in client.table("users").rows.values() if r["user_id_hash"] == uid)


def test_hash_password_roundtrip_and_no_plaintext_leak():
    stored = hash_password("hunter2hunter2")
    assert "hunter2hunter2" not in stored
    assert verify_password("hunter2hunter2", stored)
    assert not verify_password("wrong-password", stored)


def test_ac01_signup_creates_row_with_sha256_id_and_hashed_password():
    client = FakeSupabaseClient()
    user = signup_local("chefuser", "password123", client=client)

    assert user.id == account_id_from_username("chefuser")
    row = _row_by_hash(client, user.id)
    assert row["user_id"] == "chefuser"  # 컬럼명 변경(username -> user_id) 반영
    assert row["auth_provider"] == "local"
    assert row["password_hash"] != "password123"
    assert verify_password("password123", row["password_hash"])


def test_signup_records_last_login_at():
    """2026-09-01 요청 — 가입은 최초 로그인으로 취급해 last_login_at을 채운다."""
    client = FakeSupabaseClient()
    user = signup_local("chefuser", "password123", client=client)

    row = _row_by_hash(client, user.id)
    assert row.get("last_login_at") is not None


def test_ec01_duplicate_username_signup_rejected():
    client = FakeSupabaseClient()
    signup_local("chefuser", "password123", client=client)

    with pytest.raises(SignupError):
        signup_local("chefuser", "another-pass", client=client)


def test_signup_rejects_short_password():
    client = FakeSupabaseClient()
    with pytest.raises(SignupError):
        signup_local("chefuser", "short", client=client)


def test_ac02_login_success_and_failure():
    client = FakeSupabaseClient()
    signup_local("chefuser", "password123", client=client)

    ok = login_local("chefuser", "password123", client=client)
    assert ok is not None
    assert ok.username == "chefuser"

    assert login_local("chefuser", "wrong-password", client=client) is None
    assert login_local("no-such-user", "password123", client=client) is None


def test_login_updates_last_login_at():
    client = FakeSupabaseClient()
    signup_local("chefuser", "password123", client=client)
    user = login_local("chefuser", "password123", client=client)

    row = _row_by_hash(client, user.id)
    assert row.get("last_login_at") is not None


def test_ac03_google_login_inserts_once_then_reuses_row():
    client = FakeSupabaseClient()

    first = login_or_create_google("google-sub-123", "person@example.com", client=client)
    assert first.id == account_id_from_google_sub("google-sub-123")
    assert first.username == "person@example.com"
    assert len(client.table("users").rows) == 1

    second = login_or_create_google("google-sub-123", "person@example.com", client=client)
    assert second.id == first.id
    assert len(client.table("users").rows) == 1  # 추가 insert 없음


def test_account_id_is_deterministic_sha256():
    assert account_id_from_username("chefuser") == hashlib.sha256(b"chefuser").hexdigest()
    assert account_id_from_google_sub("sub-1") == hashlib.sha256(b"sub-1").hexdigest()


def test_session_token_roundtrip_and_logout_invalidation():
    """2026-09-01 요청 — 새로고침해도 로컬 로그인이 안 풀리게 하는 세션 토큰.

    users.user_id_hash(공개적으로 추측 가능한 값)를 그대로 "로그인 유지 토큰"으로
    쓰면 안 되는 이유(EC성 보안 문제)로 별도 무작위 토큰을 발급/검증/무효화한다.
    """
    client = FakeSupabaseClient()
    user = signup_local("chefuser", "password123", client=client)

    token = create_session_token(user.id, client=client)
    assert token != user.id  # 사용자 id를 그대로 재사용하지 않는다(추측 가능값 노출 방지)

    restored = resolve_session_token(token, client=client)
    assert restored is not None
    assert restored.id == user.id

    clear_session_token(user.id, client=client)
    assert resolve_session_token(token, client=client) is None  # 로그아웃 후 재사용 불가


def test_resolve_session_token_rejects_unknown_token():
    client = FakeSupabaseClient()
    signup_local("chefuser", "password123", client=client)

    assert resolve_session_token("not-a-real-token", client=client) is None


def test_session_token_expired_is_rejected():
    client = FakeSupabaseClient()
    user = signup_local("chefuser", "password123", client=client)
    token = create_session_token(user.id, client=client)

    # 발급 직후 DB의 만료시각을 과거로 되돌려 30일 경과 상황을 재현한다.
    row = _row_by_hash(client, user.id)
    row["session_token_expires_at"] = "2000-01-01T00:00:00+00:00"

    assert resolve_session_token(token, client=client) is None
