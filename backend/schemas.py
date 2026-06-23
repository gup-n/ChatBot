"""Pydantic 请求/响应模型。"""

from pydantic import BaseModel


# ── 认证 ────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    user_id: int
    username: str
    is_admin: bool


class UserCreate(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    user_id: int


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: str


# ── 配置 ────────────────────────────
class ConfigUpdate(BaseModel):
    provider: str = "deepseek"
    settings: dict = {}

class ConfigResponse(BaseModel):
    provider: str
    settings: dict
    is_ready: bool


class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""


# ── 聊天 ────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sources: list[dict] | None
    created_at: str


# ── 状态 ────────────────────────────
class StatusResponse(BaseModel):
    warmed_up: bool
    config_ready: bool


# ── 知识库文档 ──────────────────────
class DocumentInfo(BaseModel):
    filename: str
    size_bytes: int
    format: str
    modified_at: str
    created_at: str


class DocumentCreate(BaseModel):
    filename: str
    content: str


class FetchUrlRequest(BaseModel):
    url: str
    filename: str | None = None


class AuditLogQuery(BaseModel):
    user_id: int | None = None
    action: str = ""
    resource: str = ""
    limit: int = 100
    offset: int = 0


class AuditLogResponse(BaseModel):
    id: int
    user_id: int | None
    username: str
    action: str
    resource: str
    resource_id: str
    detail: str
    ip_address: str
    success: bool
    created_at: str


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
    limit: int
    offset: int


class DocumentStats(BaseModel):
    doc_count: int
    chunk_count: int
    last_build_time: str | None = None
    stale: bool
    knowledge_dir: str


class RebuildResponse(BaseModel):
    status: str
    message: str
    doc_count: int | None = None
    chunk_count: int | None = None
