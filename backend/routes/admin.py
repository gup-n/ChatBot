"""管理员路由 — 配置 / 用户管理 / 知识库 / 预热。"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
import httpx
from ..schemas import ChunkingConfigUpdate, ConfigUpdate, RetrievalConfigUpdate, UserCreate, DocumentCreate, FetchUrlRequest, FetchModelsRequest
from ..config import Config
from ..auth import hash_password
from ..main import get_db, app
from .auth import get_current_user
from ..audit import record_audit
from ..security import validate_external_url

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
        "llm": {
            "provider": Config.LLM_PROVIDER,
            "settings": Config.LLM_SETTINGS.get(Config.LLM_PROVIDER, {}),
            "all_settings": Config.LLM_SETTINGS,
            "is_ready": Config.is_ready(),
        },
        "embedding": {
            "provider": Config.EMBEDDING_PROVIDER,
            "settings": Config.EMBEDDING_SETTINGS.get(Config.EMBEDDING_PROVIDER, {}),
            "all_settings": Config.EMBEDDING_SETTINGS,
        },
        "chunking": {
            "chunk_size": Config.CHUNK_SIZE,
            "chunk_overlap": Config.CHUNK_OVERLAP,
            "chunk_separators": Config.CHUNK_SEPARATORS,
        },
        "retrieval": {
            "mode": Config.RETRIEVAL_MODE,
            "top_k": Config.RETRIEVAL_TOP_K,
            "score_threshold": Config.RETRIEVAL_SCORE_THRESHOLD,
        },
    }


@router.put("/config")
def update_config(body: ConfigUpdate, request: Request, user: dict = Depends(_require_admin)):
    from ..models.llm import PROVIDERS
    embedding_providers = {"huggingface", "openai_compatible", "ollama"}
    allowed = PROVIDERS if body.kind == "llm" else embedding_providers
    if body.provider not in allowed:
        raise HTTPException(400, f"未知的提供商: {body.provider}")
    if not body.settings.get("model"):
        raise HTTPException(400, "必须填写模型名称")
    if body.provider == "openai_compatible" and not body.settings.get("api_key"):
        raise HTTPException(400, "OpenAI 兼容接口必须填写 API Key")
    if body.provider in {"openai_compatible", "ollama"} and not body.settings.get("base_url"):
        raise HTTPException(400, "必须填写 API 地址")
    if body.kind == "llm":
        Config.save_llm_settings(provider=body.provider, settings=body.settings)
    else:
        Config.save_embedding_settings(provider=body.provider, settings=body.settings)
        from ..rag.vector_store import mark_stale
        mark_stale()
    record_audit(request, user, "update_config", "config", "",
                 f"更新 {body.kind}: {body.provider}, 模型: {body.settings.get('model', '?')}")
    return {"status": "ok", "kind": body.kind, "provider": body.provider}


@router.put("/chunking")
def update_chunking(
    body: ChunkingConfigUpdate, request: Request, user: dict = Depends(_require_admin)
):
    try:
        Config.save_chunking_settings(
            chunk_size=body.chunk_size,
            chunk_overlap=body.chunk_overlap,
            chunk_separators=body.chunk_separators,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    from ..rag.vector_store import mark_stale
    mark_stale()
    record_audit(
        request, user, "update_chunking", "config", "",
        f"更新切片策略: size={body.chunk_size}, overlap={body.chunk_overlap}",
    )
    return {"status": "ok", "message": "切片策略已保存，请全量重建向量索引"}


@router.put("/retrieval")
def update_retrieval(
    body: RetrievalConfigUpdate, request: Request, user: dict = Depends(_require_admin)
):
    try:
        Config.save_retrieval_settings(body.mode, body.top_k, body.score_threshold)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    record_audit(
        request, user, "update_retrieval", "config", "",
        f"更新检索策略: mode={body.mode}, top_k={body.top_k}, threshold={body.score_threshold}",
    )
    return {"status": "ok", "message": "检索策略已保存并立即生效"}


@router.post("/models")
def fetch_models(body: FetchModelsRequest, user: dict = Depends(_require_admin)):
    """根据 provider + api_key 从 API 拉取可用模型列表。"""
    from ..models.llm import fetch_models_list, DEFAULT_BASE_URLS, PROVIDERS

    if body.provider not in PROVIDERS or (body.kind == "embedding" and body.provider == "huggingface"):
        raise HTTPException(400, f"该提供商不支持自动拉取模型列表，请手动填写模型名称。")

    base_url = body.base_url or DEFAULT_BASE_URLS.get(body.provider, "")

    try:
        models = fetch_models_list(body.provider, api_key=body.api_key, base_url=base_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.ConnectError:
        raise HTTPException(502, f"无法连接到 {body.provider} 服务 ({base_url})。请确认服务已启动且地址正确。")
    except Exception as e:
        logger.exception("拉取模型列表失败: %s", e)
        hint = "" if body.provider == "ollama" else "请检查 API Key 和地址是否正确。"
        raise HTTPException(502, f"拉取模型列表失败: {e}. {hint}")

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
        "rebuild_status": getattr(app.state, "rebuild_status", "idle"),
        "rebuild_started_at": getattr(app.state, "rebuild_started_at", None),
        "rebuild_finished_at": getattr(app.state, "rebuild_finished_at", None),
        "rebuild_chunk_count": getattr(app.state, "rebuild_chunk_count", None),
        "config_ready": Config.is_ready(),
    }


# ── 知识库管理 ──────────────────────────────────

@router.get("/documents/stats")
def document_stats(user: dict = Depends(_require_admin)):
    from ..rag.vector_store import get_stats
    return get_stats()


@router.get("/documents")
def list_documents(user: dict = Depends(_require_admin)):
    from ..rag.loaders import list_document_info
    return list_document_info()


@router.get("/documents/{filename}")
def preview_document(filename: str, user: dict = Depends(_require_admin)):
    from ..rag.loaders import read_document
    try:
        return read_document(filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/documents/upload")
async def upload_documents(request: Request, files: list[UploadFile] = File(...), user: dict = Depends(_require_admin)):
    """批量上传知识库文件；前端文件夹选择会以多个文件提交到此接口。"""
    from ..rag.loaders import SUPPORTED_EXTENSIONS

    if not files:
        raise HTTPException(400, "请至少选择一个文件")
    if len(files) > Config.MAX_UPLOAD_FILES:
        raise HTTPException(413, f"一次最多上传 {Config.MAX_UPLOAD_FILES} 个文件")

    staged: list[tuple[str, bytes]] = []
    total_bytes = 0
    seen_names: set[str] = set()
    for upload in files:
        if not upload.filename:
            raise HTTPException(400, "文件名不能为空")
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"不支持的文件格式: {suffix}。支持: {', '.join(SUPPORTED_EXTENSIONS)}")
        safe_name = Path(upload.filename).name
        if not safe_name or safe_name.startswith("."):
            raise HTTPException(400, "无效的文件名")
        if safe_name in seen_names or (Path(Config.KNOWLEDGE_DIR) / safe_name).exists():
            raise HTTPException(409, f"文件已存在或本批次重名: {safe_name}")
        content = await upload.read()
        if not content:
            raise HTTPException(400, f"文件为空: {safe_name}")
        if len(content) > Config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"文件超过大小限制: {safe_name}")
        total_bytes += len(content)
        if total_bytes > Config.MAX_UPLOAD_TOTAL_BYTES:
            raise HTTPException(413, f"本次上传总大小超过限制（{Config.MAX_UPLOAD_TOTAL_BYTES} bytes）")
        seen_names.add(safe_name)
        staged.append((safe_name, content))

    written: list[Path] = []
    try:
        for safe_name, content in staged:
            destination = Path(Config.KNOWLEDGE_DIR) / safe_name
            destination.write_bytes(content)
            written.append(destination)

        from ..rag.ingestion import index_files
        from ..rag.vector_store import is_stale
        indexed = None if is_stale() else index_files(written)
    except Exception as exc:
        from ..rag.vector_store import delete_document_chunks
        for destination in written:
            delete_document_chunks(destination.name)
            destination.unlink(missing_ok=True)
        raise HTTPException(400, f"文件解析失败: {exc}")

    names = [path.name for path in written]
    chunk_count = indexed.chunk_count if indexed else 0
    logger.info("文档批量上传: %d files, %d incremental chunks", len(names), chunk_count)
    record_audit(request, user, "upload_doc", "document", ",".join(names),
                 f"批量上传 {len(names)} 个文档，共 {total_bytes} bytes")
    return {"status": "ok", "count": len(names), "filenames": names, "total_bytes": total_bytes,
            "chunk_count": chunk_count, "indexed": indexed is not None, "rebuild_required": indexed is None}


@router.post("/documents/create")
def create_document(body: DocumentCreate, request: Request, user: dict = Depends(_require_admin)):
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
    try:
        from ..rag.ingestion import index_files
        from ..rag.vector_store import is_stale
        indexed = None if is_stale() else index_files([dest])
    except Exception as exc:
        from ..rag.vector_store import delete_document_chunks
        delete_document_chunks(safe_name)
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"文档入库失败: {exc}")
    logger.info("文档创建成功: %s", safe_name)
    record_audit(request, user, "create_doc", "document", safe_name,
                 f"手动编写文档: {safe_name}")
    return {"status": "ok", "filename": safe_name, "size_bytes": dest.stat().st_size,
            "chunk_count": indexed.chunk_count if indexed else 0, "indexed": indexed is not None,
            "rebuild_required": indexed is None}


@router.post("/documents/fetch-url")
async def fetch_url(request: Request, body: FetchUrlRequest, user: dict = Depends(_require_admin)):
    validate_external_url(body.url)

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
        async with httpx.AsyncClient(timeout=httpx.Timeout(Config.URL_FETCH_TIMEOUT_SECONDS, connect=Config.URL_FETCH_CONNECT_TIMEOUT_SECONDS), follow_redirects=False) as client:
            url = body.url
            for _ in range(4):
                validate_external_url(url)
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise HTTPException(400, "URL 重定向缺少目标地址")
                        url = str(resp.url.join(location))
                        continue
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "").lower()
                    if content_type and not any(kind in content_type for kind in ("text/", "application/json", "application/xml", "application/javascript")):
                        raise HTTPException(400, f"不支持的 URL 内容类型: {content_type}")
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in resp.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > Config.MAX_FETCH_BYTES:
                            raise HTTPException(413, f"URL 内容超过大小限制（{Config.MAX_FETCH_BYTES} bytes）")
                        chunks.append(chunk)
                    content = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
                    break
            else:
                raise HTTPException(400, "URL 重定向次数超过限制")
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"URL 请求失败: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(400, f"URL 请求失败: {e}")

    if not content.strip():
        raise HTTPException(400, "URL 返回内容为空")

    dest.write_text(content, encoding="utf-8")
    try:
        from ..rag.ingestion import index_files
        from ..rag.vector_store import is_stale
        indexed = None if is_stale() else index_files([dest])
    except Exception as exc:
        from ..rag.vector_store import delete_document_chunks
        delete_document_chunks(safe_name)
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"URL 内容入库失败: {exc}")
    logger.info("URL 内容已保存: %s (%d bytes) <- %s", safe_name, len(content), body.url)
    record_audit(request, user, "fetch_url", "document", safe_name,
                 f"联网获取: {body.url} -> {safe_name}")
    return {"status": "ok", "filename": safe_name, "size_bytes": dest.stat().st_size, "url": body.url,
            "chunk_count": indexed.chunk_count if indexed else 0, "indexed": indexed is not None,
            "rebuild_required": indexed is None}


@router.delete("/documents/{filename}")
def delete_document(filename: str, request: Request, user: dict = Depends(_require_admin)):
    from ..rag.vector_store import delete_document_chunks

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
    app.state.rebuild_status = "running"
    app.state.rebuild_started_at = datetime.now(timezone.utc).isoformat()
    app.state.rebuild_finished_at = None
    app.state.rebuild_chunk_count = None
    record_audit(request, user, "rebuild", "system", "", "开始重建向量索引")

    def _do_rebuild():
        try:
            from ..rag.vector_store import rebuild_vector_store
            store = rebuild_vector_store()
            chunk_count = store._collection.count()
            app.state.warmed_up = True
            app.state.warmup_error = None
            app.state.rebuild_status = "succeeded"
            app.state.rebuild_chunk_count = chunk_count
            logger.info("知识库重建完成: %d chunks", chunk_count)
        except Exception as e:
            logger.exception("知识库重建失败")
            app.state.warmup_error = str(e)
            app.state.rebuild_status = "failed"
        finally:
            app.state.warming_up = False
            app.state.rebuild_finished_at = datetime.now(timezone.utc).isoformat()

    thread = threading.Thread(target=_do_rebuild, daemon=True)
    thread.start()
    return {"status": "ok", "message": "重建已启动，请通过 GET /api/admin/status 查看进度"}


# ── 审计日志 ────────────────────────────────────────

@router.get("/audit-logs")
def list_audit_logs(user_id: int | None = None, action: str = "",
                    resource: str = "", limit: int = 100, offset: int = 0,
                    user: dict = Depends(_require_admin)):
    limit = min(max(limit, 1), Config.AUDIT_LOG_MAX_PAGE_SIZE)
    offset = max(offset, 0)
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
