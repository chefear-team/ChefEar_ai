"""ChefEar 일반 사용자 회원가입/로그인 (docs/specs/user_accounts_google_login.md)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from orchestration.db import get_client

# OWASP 권장 PBKDF2-HMAC-SHA256 최소 반복횟수(2023 기준). 매 로그인마다 이만큼
# 재계산하므로, 늘릴수록 브루트포스는 느려지지만 로그인 자체도 느려진다 — 이
# 값은 그 절충점의 최소선.
_PBKDF2_ITERATIONS = 260_000

_SESSION_TOKEN_TTL_DAYS = 30


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
        id=row["user_id_hash"],
        username=row["user_id"],
        auth_provider=row.get("auth_provider") or "local",
        email=row.get("email"),
    )


def _find_by_id(uid: str, client) -> dict | None:
    rows = client.table("users").select("*").eq("user_id_hash", uid).execute().data
    return rows[0] if rows else None


def _touch_last_login(uid: str, client) -> None:
    """로그인/회원가입(=최초 로그인) 성공마다 last_login_at을 지금 시각으로 갱신한다."""
    client.table("users").update({"last_login_at": datetime.now(timezone.utc).isoformat()}).eq(
        "user_id_hash", uid
    ).execute()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def create_session_token(uid: str, client=None) -> str:
    """로컬 로그인이 브라우저 새로고침에도 안 풀리게 할 무작위 세션 토큰을 발급한다
    (ui/session.py::restore_local_session() 참고).

    users.user_id_hash(=sha256(username), 공개적으로 추측 가능한 값)를 그대로 "로그인
    유지 토큰"으로 쓰면 남의 아이디만 알아도(비밀번호 모르는 채) 그 사람으로 로그인해버릴
    수 있다 — 그래서 매번 별도의 무작위 토큰을 새로 만든다. 토큰 원본은 이 함수 호출자
    (브라우저 주소창에 실을 곳)에만 보이고, DB에는 비밀번호와 같은 이유로 해시만
    저장한다(DB가 유출돼도 토큰 원본을 복원할 수 없게).
    """
    client = client or get_client()
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=_SESSION_TOKEN_TTL_DAYS)).isoformat()
    client.table("users").update(
        {"session_token_hash": _hash_token(token), "session_token_expires_at": expires_at}
    ).eq("user_id_hash", uid).execute()
    return token


def resolve_session_token(token: str, client=None) -> User | None:
    """create_session_token()이 발급한 토큰으로 계정을 되찾는다. 만료됐거나 없는
    토큰이면 None(로그아웃 이후 재사용 등 방어 — clear_session_token()이 로그아웃
    시 해시를 지워서 그 이후엔 어차피 매치가 안 된다)."""
    client = client or get_client()
    rows = client.table("users").select("*").eq("session_token_hash", _hash_token(token)).execute().data
    if not rows:
        return None
    row = rows[0]
    expires_at = row.get("session_token_expires_at")
    if not expires_at or _parse_iso(expires_at) < datetime.now(timezone.utc):
        return None
    return _row_to_user(row)


def clear_session_token(uid: str, client=None) -> None:
    """로그아웃 시 세션 유지 토큰을 무효화한다 — 안 지우면 로그아웃 후에도 그
    토큰(주소창에 남아있을 수 있음)으로 다시 로그인돼버린다."""
    client = client or get_client()
    client.table("users").update({"session_token_hash": None, "session_token_expires_at": None}).eq(
        "user_id_hash", uid
    ).execute()


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
                    "user_id_hash": uid,
                    "user_id": username,
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
    _touch_last_login(uid, client)  # 가입 = 최초 로그인으로 취급
    return _row_to_user(row)


def login_local(username: str, password: str, client=None) -> User | None:
    client = client or get_client()
    uid = account_id_from_username((username or "").strip())
    row = _find_by_id(uid, client)
    if row is None or not verify_password(password, row.get("password_hash")):
        return None
    _touch_last_login(uid, client)
    return _row_to_user(row)


def login_or_create_google(sub: str, email: str, client=None) -> User:
    """AC-03: 이미 있으면 그대로 조회만(insert 없음), 없으면 이번 한 번만 insert.

    조회-후-insert 사이 동시 요청 경합에 대비해 insert 실패(PK unique 충돌) 시
    다시 조회해 기존 행을 돌려준다 — 중복행 생성 대신 멱등하게 기존 계정으로 수렴.
    (users.user_id_hash가 PK라 DB가 중복을 막아준다.)
    """
    client = client or get_client()
    uid = account_id_from_google_sub(sub)
    row = _find_by_id(uid, client)
    if row is not None:
        _touch_last_login(uid, client)
        return _row_to_user(row)

    try:
        row = (
            client.table("users")
            .insert(
                {
                    "user_id_hash": uid,
                    "user_id": email,
                    "email": email,
                    "auth_provider": "google",
                    "google_sub": sub,
                    "password_hash": None,
                }
            )
            .execute()
            .data[0]
        )
    except Exception:  # noqa: BLE001 — 동시 insert 경합 시 unique/PK 충돌 → 기존 행으로 폴백
        row = _find_by_id(uid, client)
        if row is None:
            raise
    _touch_last_login(uid, client)
    return _row_to_user(row)
