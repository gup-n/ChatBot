"""JWT 认证 — 密码哈希 + Token 签发/验证。"""

from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from jose import JWTError, jwt
from .database import Database
from .config import Config


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


# ── JWT ──────────────────────────────────────────
ALGORITHM = "HS256"


def create_token(user_id: int, username: str, is_admin: bool = False) -> str:
    if not Config.is_security_ready():
        raise RuntimeError("JWT_SECRET_KEY 未配置或长度不足 32 个字符")
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.JWT_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    if not Config.is_security_ready():
        return None
    try:
        return jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── 管理员种子 ───────────────────────────────────

def seed_admin(db: Database) -> None:
    if db.get_user_by_username(Config.INITIAL_ADMIN_USERNAME):
        return
    if not Config.INITIAL_ADMIN_PASSWORD or Config.INITIAL_ADMIN_PASSWORD.lower().startswith("replace-"):
        return
    db.create_user(
        Config.INITIAL_ADMIN_USERNAME,
        hash_password(Config.INITIAL_ADMIN_PASSWORD),
        is_admin=1,
    )
