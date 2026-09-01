"""auth.py 테스트 — docs/specs/user_accounts_google_login.md AC-01~03, EC-01."""
import hashlib

import pytest
from fake_supabase import FakeSupabaseClient

from orchestration.auth import (
    SignupError,
    account_id_from_google_sub,
    account_id_from_username,
    hash_password,
    login_local,
    login_or_create_google,
    signup_local,
    verify_password,
)


def test_hash_password_roundtrip_and_no_plaintext_leak():
    stored = hash_password("hunter2hunter2")
    assert "hunter2hunter2" not in stored
    assert verify_password("hunter2hunter2", stored)
    assert not verify_password("wrong-password", stored)


def test_ac01_signup_creates_row_with_sha256_id_and_hashed_password():
    client = FakeSupabaseClient()
    user = signup_local("chefuser", "password123", client=client)

    assert user.id == account_id_from_username("chefuser")
    row = client.table("users").rows[user.id]
    assert row["auth_provider"] == "local"
    assert row["password_hash"] != "password123"
    assert verify_password("password123", row["password_hash"])


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


def test_ac03_google_login_inserts_once_then_reuses_row():
    client = FakeSupabaseClient()

    first = login_or_create_google("google-sub-123", "person@example.com", client=client)
    assert first.id == account_id_from_google_sub("google-sub-123")
    assert len(client.table("users").rows) == 1

    second = login_or_create_google("google-sub-123", "person@example.com", client=client)
    assert second.id == first.id
    assert len(client.table("users").rows) == 1  # 추가 insert 없음


def test_account_id_is_deterministic_sha256():
    assert account_id_from_username("chefuser") == hashlib.sha256(b"chefuser").hexdigest()
    assert account_id_from_google_sub("sub-1") == hashlib.sha256(b"sub-1").hexdigest()
