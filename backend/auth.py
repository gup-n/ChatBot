"""JWT 认证 — 密码哈希 + Token 签发/验证。"""

from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from jose import JWTError, jwt
from .database import Database


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


# ── JWT ──────────────────────────────────────────
SECRET_KEY = "nbut-cyber-chatbot-secret-key-2025"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_token(user_id: int, username: str, is_admin: bool = False) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── 管理员种子 ───────────────────────────────────

def seed_admin(db: Database) -> None:
    if db.get_user_by_username("admin"):
        return
    db.create_user("admin", hash_password("admin123"), is_admin=1)
