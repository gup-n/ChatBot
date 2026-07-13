"""Pydantic 请求/响应模型。"""

from pydantic import BaseModel, Field


# ── 认证 ────────────────────────────
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=3, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    user_id: int
    username: str
    is_admin: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=3, max_length=256)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=3, max_length=256)
    new_password: str = Field(min_length=3, max_length=256)


class ResetPasswordRequest(BaseModel):
    user_id: int


# ── 配置 ────────────────────────────
class ConfigUpdate(BaseModel):
    kind: str = Field(default="llm", pattern="^(llm|embedding)$")
    provider: str = Field(default="openai_compatible", min_length=1, max_length=32)
    settings: dict = Field(default_factory=dict)

class ChunkingConfigUpdate(BaseModel):
    chunk_size: int = Field(ge=64, le=8192)
    chunk_overlap: int = Field(ge=0, le=4096)
    chunk_separators: list[str] = Field(min_length=1, max_length=20)


class RetrievalConfigUpdate(BaseModel):
    mode: str = Field(pattern="^(hybrid|vector)$")
    top_k: int = Field(ge=1, le=20)
    score_threshold: float = Field(ge=0, le=2)


class FetchModelsRequest(BaseModel):
    kind: str = Field(default="llm", pattern="^(llm|embedding)$")
    provider: str = Field(min_length=1, max_length=32)
    api_key: str = Field(default="", max_length=512)
    base_url: str = Field(default="", max_length=2048)


# ── 聊天 ────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(min_length=1, max_length=64)


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=1_000_000)


class FetchUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    filename: str | None = Field(default=None, max_length=255)
