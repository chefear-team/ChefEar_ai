"""마이 레시피 로그인용 실제 계정(아이디/비밀번호) 인증 — 2026-08-22 추가.

작업3(identity.py)의 쿠키 익명 UUID와는 별개 개념이다. 쿠키는 "회원가입 없이 같은
브라우저면 내 레시피를 기억"하는 용도로 조리 흐름(자유발화로 새 레시피 등록)에
계속 쓰고, 이 파일은 그 위에 "로그인해서 기기와 무관하게 내 레시피를 관리"하는
진짜 계정을 추가한다 — 두 개념이 공존한다. 로그인 상태면 ui/session.py의
get_owner_id()가 쿠키 UUID 대신 이 계정의 id를 recipes.owner_id로 쓴다.

비밀번호는 원문을 저장하지 않고 PBKDF2-HMAC-SHA256(표준 라이브러리 hashlib, 새
의존성 추가 없음)으로 해시해서 저장한다. bcrypt 같은 전용 라이브러리보다 튜닝
여지는 적지만, 이 프로젝트 규모(학습용 소규모 서비스)에는 충분하고 requirements에
새 패키지를 안 늘려도 된다(llm/infer.py가 transformers 버전을 새로 안 올리는 것과
같은 방향의 선택).
"""
from __future__ import annotations

import hashlib
import os

from orchestration.db import get_client

# NIST SP 800-63B가 권장하는 최소값(10,000) 이상으로, 로그인 한 번에 필요한 계산
# 시간(수십~수백 ms)과 무차별 대입 공격 방어력 사이에서 균형을 잡은 값.
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """"salt(hex):hash(hex)" 형태의 문자열을 만든다.

    salt를 매 비밀번호마다 새로 무작위 생성해서(os.urandom), 같은 비밀번호를 쓰는
    두 계정이라도 저장된 해시 값이 서로 달라지게 한다(레인보우 테이블 방어).
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """저장된 "salt:hash"에서 salt를 꺼내 같은 방식으로 다시 해시해보고 비교한다."""
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return digest.hex() == digest_hex


def create_user(username: str, password: str, client=None) -> dict:
    """새 계정을 만든다.

    아이디가 이미 있으면 ValueError를 던진다 — 화면(screen_login())이 이걸 잡아서
    "이미 사용 중인 아이디예요"로 안내한다. users.username에 이미 unique 제약이
    있어서 DB가 막아주긴 하지만, 그 경우 에러 메시지가 raw SQL 에러라 사용자에게
    보여주기 부적절해서 여기서 먼저 확인하고 사람이 읽을 문구로 바꿔 던진다.
    """
    client = client or get_client()
    username = username.strip()
    if not username or not password:
        raise ValueError("아이디와 비밀번호를 모두 입력해주세요.")
    existing = client.table("users").select("id").eq("username", username).execute().data
    if existing:
        raise ValueError("이미 사용 중인 아이디예요.")
    row = (
        client.table("users")
        .insert({"username": username, "password_hash": hash_password(password)})
        .execute()
        .data[0]
    )
    return {"id": row["id"], "username": row["username"]}


def get_user_by_id(user_id: str, client=None) -> dict | None:
    """계정 id로 {"id","username"}을 찾는다. 새로고침해도 로그인이 풀리지 않게(2026-08-22
    요청) 쿠키에 저장해둔 계정 id로 로그인 상태를 복원할 때 쓴다 — ui/session.py의
    restore_login_from_cookie() 참고."""
    client = client or get_client()
    rows = client.table("users").select("id,username").eq("id", user_id).execute().data
    return rows[0] if rows else None


def authenticate_user(username: str, password: str, client=None) -> dict | None:
    """아이디/비밀번호가 맞으면 {"id","username"}, 틀리면 None."""
    client = client or get_client()
    rows = (
        client.table("users")
        .select("id,username,password_hash")
        .eq("username", username.strip())
        .execute()
        .data
    )
    if not rows:
        return None
    user = rows[0]
    if not verify_password(password, user["password_hash"]):
        return None
    return {"id": user["id"], "username": user["username"]}
