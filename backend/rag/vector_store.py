import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from langchain_chroma import Chroma
from ..config import Config
from ..models.embedding import create_embedding_model

logger = logging.getLogger(__name__)

_vector_store: Chroma | None = None
_lock = threading.Lock()
STALE_FILE = Path(Config.CHROMA_PERSIST_DIR) / ".needs_rebuild"


def get_vector_store() -> Chroma:
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    with _lock:
        if _vector_store is None:
            _vector_store = _init()
    return _vector_store


def search(query: str, top_k: int | None = None) -> list[dict]:
    store = get_vector_store()
    top_k = top_k or Config.RETRIEVAL_TOP_K
    with _lock:
        results = store.similarity_search_with_score(query, k=top_k)
    return [
        {"content": doc.page_content, "source": doc.metadata.get("source", "未知"), "score": round(float(s), 4)}
        for doc, s in results
    ]


def rebuild_vector_store() -> Chroma:
    global _vector_store
    from .documents import load_documents, split_documents

    logger.info("重建向量库...")
    raw_docs = load_documents()
    if not raw_docs:
        logger.warning("知识库为空")
        with _lock:
            _vector_store = Chroma(embedding_function=create_embedding_model(), persist_directory=Config.CHROMA_PERSIST_DIR)
        return _vector_store

    chunks = split_documents(raw_docs)
    logger.info("向量化 %d 个片段...", len(chunks))
    embedding = create_embedding_model()
    with _lock:
        _vector_store = Chroma.from_documents(
            documents=chunks, embedding=embedding, persist_directory=Config.CHROMA_PERSIST_DIR,
            collection_metadata={"hnsw:space": "cosine"},
        )
    if STALE_FILE.exists():
        STALE_FILE.unlink()
    logger.info("向量库构建完成")
    return _vector_store


def _init() -> Chroma:
    persist_dir = Path(Config.CHROMA_PERSIST_DIR)
    if (persist_dir / "chroma.sqlite3").exists():
        logger.info("加载已有向量库: %s", persist_dir)
        return Chroma(embedding_function=create_embedding_model(), persist_directory=str(persist_dir))
    logger.info("向量库不存在，自动构建...")
    return rebuild_vector_store()


def mark_stale() -> None:
    Path(Config.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
    STALE_FILE.touch()
    logger.info("已标记知识库为需要重建")


def get_stats() -> dict:
    from .documents import count_knowledge_files
    doc_count = count_knowledge_files()
    chunk_count = 0
    last_build_time = None
    chroma_sqlite = Path(Config.CHROMA_PERSIST_DIR) / "chroma.sqlite3"
    if chroma_sqlite.exists():
        last_build_time = datetime.fromtimestamp(chroma_sqlite.stat().st_mtime, tz=timezone(timedelta(hours=8))).isoformat()
        try:
            store = get_vector_store()
            chunk_count = store._collection.count()
        except Exception:
            pass
    # 自动检测：知识库目录中是否有文件比 ChromaDB 更新
    if not STALE_FILE.exists() and last_build_time and doc_count > 0:
        knowledge_dir = Path(Config.KNOWLEDGE_DIR)
        if knowledge_dir.exists():
            latest_file_mtime = max(
                (f.stat().st_mtime for f in knowledge_dir.iterdir()
                 if f.is_file() and not f.name.startswith(".")),
                default=0,
            )
            if latest_file_mtime > chroma_sqlite.stat().st_mtime:
                mark_stale()
    return {
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "last_build_time": last_build_time,
        "stale": STALE_FILE.exists(),
        "knowledge_dir": Config.KNOWLEDGE_DIR,
    }


def delete_document_chunks(filename: str) -> int:
    store = get_vector_store()
    try:
        results = store._collection.get(where={"source": filename})
        ids = results.get("ids", [])
        if ids:
            store._collection.delete(ids=ids)
        return len(ids)
    except Exception:
        logger.exception("删除文档块失败: %s", filename)
        return 0
