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
    # 启动时检测：如果 ChromaDB 已持久化，标记为已预热
    chroma_exists = (Path(Config.CHROMA_PERSIST_DIR) / "chroma.sqlite3").exists()
    app.state.warmed_up = chroma_exists
    app.state.warming_up = False
    app.state.warmup_error = None
    if chroma_exists:
        logger.info("检测到已有向量库，跳过预热")
    logger.info("FastAPI 启动完成 (DB: %s)", Config.SQLITE_DB_PATH)
    yield
    logger.info("FastAPI 关闭")


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
