"""认证路由 — 登录 / 注册 / 改密 / 重置密码。"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..schemas import LoginRequest, TokenResponse, UserCreate, ChangePasswordRequest, ResetPasswordRequest
from ..auth import verify_password, hash_password, create_token, decode_token
from ..main import get_db
from ..audit import record_audit

router = APIRouter()
security = HTTPBearer(auto_error=False)

DEFAULT_RESET_PASSWORD = "123456"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(401, "未提供认证令牌")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "令牌无效或已过期")
    db = get_db()
    user = db.get_user(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "用户不存在")
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


def get_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "需要管理员权限")
    return user


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request):
    db = get_db()
    user = db.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        record_audit(request, None, "login", "auth", "",
                     f"登录失败: 用户名={req.username}", success=False)
        raise HTTPException(401, "用户名或密码错误")
    record_audit(request, {"id": user["id"], "username": user["username"]},
                 "login", "auth", "", f"登录成功: {user['username']}")
    token = create_token(user["id"], user["username"], bool(user["is_admin"]))
    return TokenResponse(access_token=token, user_id=user["id"], username=user["username"], is_admin=bool(user["is_admin"]))


@router.post("/register")
def register(req: UserCreate, request: Request):
    """用户自助注册（仅能注册普通用户）。"""
    db = get_db()
    if db.get_user_by_username(req.username):
        raise HTTPException(400, "用户名已存在")
    if len(req.username) < 2:
        raise HTTPException(400, "用户名至少2个字符")
    if len(req.password) < 3:
        raise HTTPException(400, "密码至少3个字符")
    uid = db.create_user(req.username, hash_password(req.password), is_admin=0)
    record_audit(request, {"id": uid, "username": req.username},
                 "register", "user", str(uid), f"用户注册: {req.username}")
    token = create_token(uid, req.username, False)
    return {"id": uid, "username": req.username, "access_token": token}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request, user: dict = Depends(get_current_user)):
    """用户自行修改密码。"""
    db = get_db()
    u = db.get_user(user["id"])
    if not u or not verify_password(req.old_password, u["password_hash"]):
        record_audit(request, user, "change_password", "user", str(user["id"]),
                     "密码修改失败: 原密码错误", success=False)
        raise HTTPException(400, "原密码错误")
    if len(req.new_password) < 3:
        raise HTTPException(400, "新密码至少3个字符")
    db.update_password(user["id"], hash_password(req.new_password))
    record_audit(request, user, "change_password", "user", str(user["id"]), "密码修改成功")
    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, admin: dict = Depends(get_admin)):
    """管理员重置用户密码为 123456。"""
    db = get_db()
    target = db.get_user(req.user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target["is_admin"]:
        raise HTTPException(400, "不能重置管理员密码")
    db.update_password(req.user_id, hash_password(DEFAULT_RESET_PASSWORD))
    record_audit(request, admin, "reset_password", "user", str(req.user_id),
                 f"管理员 {admin['username']} 重置了 {target['username']} 的密码")
    return {"status": "ok", "message": f"密码已重置为 {DEFAULT_RESET_PASSWORD}"}
