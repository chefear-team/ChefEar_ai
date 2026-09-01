"""ChefEar 일반 사용자 회원가입/로그인 (docs/specs/user_accounts_google_login.md).

2026-08-27에 한 번 완전히 삭제됐던 계정 시스템(docs/specs/remove_user_accounts.md)을
새 스킴으로 재작성한다. 예전과 가장 다른 점: 계정 식별자(`users.id`)가 무작위 UUID가
아니라 결정론적(deterministic) SHA256 해시값이다 — 로컬 가입은 `sha256(username)`,
구글 로그인은 `sha256(google_sub)`. 그래서 "이 계정이 이미 있는지" 확인이 곧
"이 id로 조회했을 때 행이 있는지"와 같아진다(구글 로그인의 "있으면 패스, 없으면
insert" 요구사항이 이 성질 덕분에 별도 조건문 없이 자연스럽게 성립).

비밀번호 자체는 SHA256 단독이 아니라 salt+PBKDF2-HMAC-SHA256으로 저장한다 — 순수
SHA256은 솔트가 없으면 레인보우 테이블 공격에 취약하다. 이 포맷 문자열
("salt(hex):hash(hex)")은 예전 삭제된 auth.py와 동일해서, 나중에 그 시절 데이터가
남아있어도(지금은 없음, EC-08) 검증 로직을 그대로 재사용할 수 있다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from orchestration.db import get_client

# OWASP 권장 PBKDF2-HMAC-SHA256 최소 반복횟수(2023 기준). 매 로그인마다 이만큼
# 재계산하므로, 늘릴수록 브루트포스는 느려지지만 로그인 자체도 느려진다 — 이
# 값은 그 절충점의 최소선.
_PBKDF2_ITERATIONS = 260_000


@dataclass
class User:
    id: str
    username: str
    auth_provider: str
    email: str | None = None


class SignupError(Exception):
    """회원가입 실패 사유. 메시지를 그대로 화면에 보여줘도 안전한 문구만 담는다."""


def _account_id(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def account_id_from_username(username: str) -> str:
    return _account_id(username)


def account_id_from_google_sub(sub: str) -> str:
    return _account_id(sub)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        salt_hex, digest_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def _row_to_user(row: dict) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        auth_provider=row.get("auth_provider") or "local",
        email=row.get("email"),
    )


def _find_by_id(uid: str, client) -> dict | None:
    rows = client.table("users").select("*").eq("id", uid).execute().data
    return rows[0] if rows else None


def signup_local(username: str, password: str, client=None) -> User:
    """EC-01/EC-03/EC-04(화면이 이미 확인란 일치는 검사) — 아이디 중복/비밀번호
    길이만 여기서 확인한다. EC-08: 예전 테스트 계정(구 UUID id)이 같은 username을
    이미 쓰고 있으면 sha256 기반 중복 체크로는 못 잡고 DB의 `username unique`
    제약이 insert 시점에 잡아준다 — 그 경우도 SignupError로 통일해 화면에 보여준다.
    """
    username = (username or "").strip()
    if not username:
        raise SignupError("아이디를 입력해주세요.")
    if len(password or "") < 8:
        raise SignupError("비밀번호는 8자 이상이어야 해요.")

    client = client or get_client()
    uid = account_id_from_username(username)
    if _find_by_id(uid, client) is not None:
        raise SignupError("이미 가입된 아이디예요.")

    try:
        row = (
            client.table("users")
            .insert(
                {
                    "id": uid,
                    "username": username,
                    "password_hash": hash_password(password),
                    "auth_provider": "local",
                    "email": None,
                }
            )
            .execute()
            .data[0]
        )
    except Exception as exc:  # noqa: BLE001 — EC-08: DB unique 제약 위반을 안전한 문구로 변환
        raise SignupError("이미 가입된 아이디예요.") from exc
    return _row_to_user(row)


def login_local(username: str, password: str, client=None) -> User | None:
    client = client or get_client()
    uid = account_id_from_username((username or "").strip())
    row = _find_by_id(uid, client)
    if row is None or not verify_password(password, row.get("password_hash")):
        return None
    return _row_to_user(row)


def login_or_create_google(sub: str, email: str, client=None) -> User:
    """AC-03: 이미 있으면 그대로 조회만(insert 없음), 없으면 이번 한 번만 insert."""
    client = client or get_client()
    uid = account_id_from_google_sub(sub)
    row = _find_by_id(uid, client)
    if row is not None:
        return _row_to_user(row)

    row = (
        client.table("users")
        .insert(
            {
                "id": uid,
                "username": email,
                "email": email,
                "auth_provider": "google",
                "google_sub": sub,
                "password_hash": None,
            }
        )
        .execute()
        .data[0]
    )
    return _row_to_user(row)
