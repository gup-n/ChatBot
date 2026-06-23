"""管理员路由 — 配置 / 用户管理 / 知识库 / 预热。"""

import logging
import threading
import traceback
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
import httpx
from ..schemas import ConfigUpdate, UserCreate, DocumentCreate, FetchUrlRequest, FetchModelsRequest
from ..config import Config
from ..database import Database
from ..auth import hash_password, create_token
from ..main import get_db, app
from .auth import get_current_user
from ..audit import record_audit

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "需要管理员权限")
    return user


# ── 配置 ────────────────────────────────────────

@router.get("/config")
def get_config(user: dict = Depends(_require_admin)):
    return {
        "provider": Config.LLM_PROVIDER,
        "settings": Config.LLM_SETTINGS.get(Config.LLM_PROVIDER, {}),
        "is_ready": Config.is_ready(),
        "all_settings": Config.LLM_SETTINGS,  # 所有 provider 的配置（切换时恢复）
    }


@router.put("/config")
def update_config(body: ConfigUpdate, request: Request, user: dict = Depends(_require_admin)):
    Config.save_settings(provider=body.provider, settings=body.settings)
    record_audit(request, user, "update_config", "config", "",
                 f"切换到 {body.provider}, 模型: {body.settings.get('model', '?')}")
    return {"status": "ok", "provider": Config.LLM_PROVIDER}


@router.post("/models")
def fetch_models(body: FetchModelsRequest, user: dict = Depends(_require_admin)):
    """根据 provider + api_key 从 API 拉取可用模型列表。"""
    from ..models.llm import fetch_models_list, DEFAULT_BASE_URLS, PROVIDERS

    if body.provider not in PROVIDERS:
        known = list(PROVIDERS.keys())
        raise HTTPException(400, f"未知的提供商: {body.provider}，可用: {known}")

    base_url = body.base_url or DEFAULT_BASE_URLS.get(body.provider, "")

    try:
        models = fetch_models_list(body.provider, api_key=body.api_key, base_url=base_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("拉取模型列表失败: %s", e)
        raise HTTPException(502, f"拉取模型列表失败: {e}. 请检查 API Key 和地址是否正确。")

    return {"models": models, "count": len(models)}


# ── 用户管理 ────────────────────────────────────

@router.get("/users")
def list_users(user: dict = Depends(_require_admin)):
    db = get_db()
    return db.list_users()


@router.post("/users")
def create_user(body: UserCreate, request: Request, user: dict = Depends(_require_admin)):
    db = get_db()
    if db.get_user_by_username(body.username):
        raise HTTPException(400, "用户名已存在")
    if len(body.password) < 3:
        raise HTTPException(400, "密码至少3位")
    uid = db.create_user(body.username, hash_password(body.password))
    record_audit(request, user, "create_user", "user", str(uid),
                 f"管理员 {user['username']} 创建了用户: {body.username}")
    return {"id": uid, "username": body.username}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, user: dict = Depends(_require_admin)):
    if user_id == user["id"]:
        raise HTTPException(400, "不能删除自己")
    db = get_db()
    target = db.get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    # 先删除该用户的所有会话（FK REFERENCES）
    with db._conn() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.delete_user(user_id)
    record_audit(request, user, "delete_user", "user", str(user_id),
                 f"管理员 {user['username']} 删除了用户: {target['username']}")
    return {"status": "ok"}


# ── 预热 ────────────────────────────────────────

@router.post("/warmup")
def warmup(request: Request, user: dict = Depends(_require_admin)):
    if not Config.is_ready():
        raise HTTPException(400, "请先配置 API Key")
    from ..main import start_warmup
    start_warmup()
    record_audit(request, user, "warmup", "system", "", "启动知识库预热")
    return {"status": "ok", "message": "预热已启动，请通过 GET /status 查看进度"}


@router.get("/status")
def status():
    return {
        "warmed_up": app.state.warmed_up,
        "warming_up": app.state.warming_up,
        "warmup_error": app.state.warmup_error,
        "config_ready": Config.is_ready(),
    }


# ── 知识库管理 ──────────────────────────────────

@router.get("/documents/stats")
def document_stats(user: dict = Depends(_require_admin)):
    from ..rag.vector_store import get_stats
    return get_stats()


@router.get("/documents")
def list_documents(user: dict = Depends(_require_admin)):
    from ..rag.documents import get_document_info
    return get_document_info()


@router.get("/documents/{filename}")
def preview_document(filename: str, user: dict = Depends(_require_admin)):
    from ..rag.documents import read_document_content
    try:
        return read_document_content(filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/documents/upload")
async def upload_document(request: Request, file: UploadFile = File(...), user: dict = Depends(_require_admin)):
    from ..rag.documents import SUPPORTED_EXTENSIONS, load_single_document
    from ..rag.vector_store import mark_stale

    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {suffix}。支持: {', '.join(SUPPORTED_EXTENSIONS)}")

    safe_name = Path(file.filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "无效的文件名")

    dest = Path(Config.KNOWLEDGE_DIR) / safe_name
    if dest.exists():
        raise HTTPException(409, f"文件已存在: {safe_name}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")

    dest.write_bytes(content)

    try:
        load_single_document(dest)
    except Exception as e:
        dest.unlink()
        raise HTTPException(400, f"文件解析失败: {e}")

    mark_stale()
    logger.info("文档上传成功: %s (%d bytes)", safe_name, len(content))
    record_audit(request, user, "upload_doc", "document", safe_name,
                 f"上传文档: {safe_name} ({len(content)} bytes)")
    return {"status": "ok", "filename": safe_name, "size_bytes": len(content)}


@router.post("/documents/create")
def create_document(body: DocumentCreate, request: Request, user: dict = Depends(_require_admin)):
    from ..rag.vector_store import mark_stale

    safe_name = Path(body.filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "无效的文件名")
    if not safe_name.endswith(".txt"):
        raise HTTPException(400, "文件名必须以 .txt 结尾")
    if not body.content.strip():
        raise HTTPException(400, "内容不能为空")

    dest = Path(Config.KNOWLEDGE_DIR) / safe_name
    if dest.exists():
        raise HTTPException(409, f"文件已存在: {safe_name}")

    dest.write_text(body.content, encoding="utf-8")
    mark_stale()
    logger.info("文档创建成功: %s", safe_name)
    record_audit(request, user, "create_doc", "document", safe_name,
                 f"手动编写文档: {safe_name}")
    return {"status": "ok", "filename": safe_name, "size_bytes": dest.stat().st_size}


@router.post("/documents/fetch-url")
async def fetch_url(request: Request, body: FetchUrlRequest, user: dict = Depends(_require_admin)):
    from ..rag.vector_store import mark_stale
    from urllib.parse import urlparse

    if body.filename:
        safe_name = Path(body.filename).name
        if not safe_name.endswith(".txt"):
            safe_name = safe_name + ".txt"
    else:
        parsed = urlparse(body.url)
        path_part = parsed.path.rstrip("/").split("/")[-1] if parsed.path else ""
        safe_name = (path_part or "url_fetch") + ".txt"

    if not safe_name or safe_name.startswith("."):
        safe_name = "url_fetch.txt"

    dest = Path(Config.KNOWLEDGE_DIR) / safe_name
    base = safe_name.rsplit(".", 1)[0]
    counter = 1
    while dest.exists():
        safe_name = f"{base}_{counter}.txt"
        dest = Path(Config.KNOWLEDGE_DIR) / safe_name
        counter += 1

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(body.url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"URL 请求失败: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(400, f"URL 请求失败: {e}")

    content = resp.text
    if not content.strip():
        raise HTTPException(400, "URL 返回内容为空")

    dest.write_text(content, encoding="utf-8")
    mark_stale()
    logger.info("URL 内容已保存: %s (%d bytes) <- %s", safe_name, len(content), body.url)
    record_audit(request, user, "fetch_url", "document", safe_name,
                 f"联网获取: {body.url} -> {safe_name}")
    return {"status": "ok", "filename": safe_name, "size_bytes": dest.stat().st_size, "url": body.url}


@router.delete("/documents/{filename}")
def delete_document(filename: str, request: Request, user: dict = Depends(_require_admin)):
    from ..rag.vector_store import mark_stale, delete_document_chunks

    safe_name = Path(filename).name
    fp = Path(Config.KNOWLEDGE_DIR) / safe_name

    if not fp.exists():
        raise HTTPException(404, "文件不存在")
    if not fp.resolve().is_relative_to(Path(Config.KNOWLEDGE_DIR).resolve()):
        raise HTTPException(400, "非法文件路径")

    try:
        deleted_chunks = delete_document_chunks(safe_name)
    except Exception:
        deleted_chunks = 0

    fp.unlink()
    mark_stale()
    logger.info("文档已删除: %s (%d chunks)", safe_name, deleted_chunks)
    record_audit(request, user, "delete_doc", "document", safe_name,
                 f"删除文档: {safe_name} ({deleted_chunks} chunks)")
    return {"status": "ok", "filename": safe_name, "deleted_chunks": deleted_chunks}


@router.post("/rebuild")
def rebuild(request: Request, user: dict = Depends(_require_admin)):
    if not Config.is_ready():
        raise HTTPException(400, "请先配置 API Key")

    if app.state.warming_up:
        raise HTTPException(409, "正在重建中，请稍后再试")

    app.state.warming_up = True
    app.state.warmup_error = None
    record_audit(request, user, "rebuild", "system", "", "开始重建向量索引")

    def _do_rebuild():
        try:
            from ..rag.vector_store import rebuild_vector_store
            store = rebuild_vector_store()
            chunk_count = store._collection.count()
            app.state.warmed_up = True
            app.state.warmup_error = None
            logger.info("知识库重建完成: %d chunks", chunk_count)
        except Exception as e:
            logger.exception("知识库重建失败")
            app.state.warmup_error = str(e)
        finally:
            app.state.warming_up = False

    thread = threading.Thread(target=_do_rebuild, daemon=True)
    thread.start()
    return {"status": "ok", "message": "重建已启动，请通过 GET /api/admin/status 查看进度"}


# ── 审计日志 ────────────────────────────────────────

@router.get("/audit-logs")
def list_audit_logs(user_id: int | None = None, action: str = "",
                    resource: str = "", limit: int = 100, offset: int = 0,
                    user: dict = Depends(_require_admin)):
    db = get_db()
    logs = db.list_audit_logs(user_id=user_id, action=action, resource=resource,
                              limit=limit, offset=offset)
    total = db.count_audit_logs(user_id=user_id, action=action, resource=resource)
    return {"logs": logs, "total": total, "limit": limit, "offset": offset}


@router.get("/audit-logs/actions")
def list_audit_actions(user: dict = Depends(_require_admin)):
    """返回所有出现过的 audit action 类型，供前端筛选。"""
    db = get_db()
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT action FROM audit_logs ORDER BY action"
        ).fetchall()
    return {"actions": [r["action"] for r in rows]}
