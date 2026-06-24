"""FastAPI 应用 — 网安学院问答机器人后端。"""

import logging
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .database import Database
from .auth import seed_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

db: Database | None = None


def get_db() -> Database:
    assert db is not None
    return db


# ── 后台预热 ──────────────────────────────────────

def _do_warmup():
    """在后台线程中加载嵌入模型 + 构建向量库。"""
    try:
        logger.info("后台预热开始...")
        from .rag.vector_store import get_vector_store
        get_vector_store()
        app.state.warmed_up = True
        app.state.warmup_error = None
        logger.info("后台预热完成")
    except Exception as e:
        logger.exception("后台预热失败")
        app.state.warmup_error = str(e)


def start_warmup():
    """启动后台预热线程（非阻塞）。"""
    if app.state.warming_up:
        return  # 已经在预热中
    app.state.warming_up = True
    app.state.warmup_error = None
    t = threading.Thread(target=_do_warmup, daemon=True)
    t.start()


# ── FastAPI ───────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    Config.ensure_dirs()
    db = Database(Config.SQLITE_DB_PATH)
    seed_admin(db)

    # 启动时预加载嵌入模型，避免首次请求长时间阻塞
    logger.info("预加载嵌入模型...")
    try:
        from .models.embedding import create_embedding_model
        embedding = create_embedding_model()
        logger.info("嵌入模型已就绪 (provider: %s)", Config.EMBEDDING_PROVIDER)
    except Exception as e:
        logger.warning("预加载嵌入模型失败（将在首次请求时重试）: %s", e)

    # 如果有已持久化 ChromaDB，直接加载；否则向量库在 _init 中按需构建
    chroma_exists = (Path(Config.CHROMA_PERSIST_DIR) / "chroma.sqlite3").exists()
    app.state.warmed_up = chroma_exists
    app.state.warming_up = False
    app.state.warmup_error = None
    if chroma_exists:
        # 后台加载向量库（不阻塞启动）
        t = threading.Thread(target=_load_existing_store, daemon=True)
        t.start()
        logger.info("检测到已有向量库，后台加载中...")
    else:
        logger.info("向量库不存在，将在 /rebuild 时自动构建")

    logger.info("FastAPI 启动完成 (DB: %s)", Config.SQLITE_DB_PATH)
    yield
    logger.info("FastAPI 关闭")


def _load_existing_store():
    """后台加载已有向量库（首次调用会完成 ChromaDB 初始化）。"""
    try:
        from .rag.vector_store import get_vector_store
        get_vector_store()
        app.state.warmed_up = True
        logger.info("向量库后台加载完成")
    except Exception as e:
        logger.exception("向量库后台加载失败")
        app.state.warmup_error = str(e)


app = FastAPI(title="网安学院问答机器人 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from .routes import admin, chat, auth as auth_routes
app.include_router(auth_routes.router, prefix="/api/auth", tags=["认证"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理"])
app.include_router(chat.router, prefix="/api/chat", tags=["聊天"])


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "warmed_up": app.state.warmed_up,
        "warming_up": app.state.warming_up,
        "warmup_error": app.state.warmup_error,
        "config_ready": Config.is_ready(),
    }
