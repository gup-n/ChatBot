"""审计日志记录 — 记录用户操作到 audit_logs 表。"""

from fastapi import Request


def record_audit(request: Request | None, user: dict | None, action: str,
                 resource: str, resource_id: str = "", detail: str = "",
                 success: bool = True):
    """记录一条审计日志。由各端点主动调用。"""
    from .main import get_db
    try:
        db = get_db()
        db.add_audit_log(
            user_id=user["id"] if user else None,
            username=user["username"] if user else "anonymous",
            action=action,
            resource=resource,
            resource_id=resource_id,
            detail=detail,
            ip_address=_client_ip(request) if request else "",
            success=success,
        )
    except Exception:
        pass  # 审计记录失败不影响主流程


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""
