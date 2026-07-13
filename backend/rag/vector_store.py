import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from langchain_chroma import Chroma
from langchain_core.documents import Document
from ..config import Config
from ..models.embedding import create_embedding_model

logger = logging.getLogger(__name__)

_vector_store: Chroma | None = None
_lock = threading.RLock()
STALE_FILE = Path(Config.CHROMA_PERSIST_DIR) / ".needs_rebuild"


def get_vector_store() -> Chroma:
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    with _lock:
        if _vector_store is None:
            _vector_store = _init()
    return _vector_store


def similarity_search(query: str, top_k: int) -> list[tuple[Document, float]]:
    """存储层只返回 Chroma 的原始 Document 与距离，不承担结果格式化。"""
    store = get_vector_store()
    with _lock:
        return store.similarity_search_with_score(query, k=top_k)


def rebuild_vector_store() -> Chroma:
    """兼容入口；数据载入和切分由 ingestion 层统一编排。"""
    from .ingestion import rebuild_knowledge_base
    rebuild_knowledge_base()
    return get_vector_store()


def replace_documents(chunks: list[Document]) -> Chroma:
    """替换 Chroma 中的完整 chunk 集合，存储层不解析原始文件。"""
    global _vector_store

    logger.info("重建向量库...")
    embedding = create_embedding_model()
    if not chunks:
        logger.warning("知识库为空")
        with _lock:
            _delete_existing_collection(embedding)
            _vector_store = Chroma(embedding_function=embedding, persist_directory=Config.CHROMA_PERSIST_DIR)
        return _vector_store

    logger.info("向量化 %d 个片段...", len(chunks))
    with _lock:
        # 固定 collection 在重建前删除，避免旧块累积为重复检索结果。
        _delete_existing_collection(embedding)
        _vector_store = Chroma.from_documents(
            documents=chunks, embedding=embedding, persist_directory=Config.CHROMA_PERSIST_DIR,
            collection_metadata={"hnsw:space": "cosine"},
        )
    if STALE_FILE.exists():
        STALE_FILE.unlink()
    from .retrieval import invalidate_lexical_cache
    invalidate_lexical_cache()
    logger.info("向量库构建完成")
    return _vector_store


def upsert_documents(chunks: list[Document]) -> Chroma:
    """按来源替换增量文档的向量块，无需全量重建索引。"""
    if not chunks:
        raise ValueError("没有可写入向量库的文本块")

    sources = {str(chunk.metadata.get("source", "")) for chunk in chunks}
    if not all(sources):
        raise ValueError("向量块缺少 source 元数据")

    with _lock:
        store = get_vector_store()
        for source in sources:
            _delete_source_chunks(store, source)
        store.add_documents(chunks)
    logger.info("增量向量入库完成: sources=%d, chunks=%d", len(sources), len(chunks))
    from .retrieval import invalidate_lexical_cache
    invalidate_lexical_cache()
    return store


def _delete_existing_collection(embedding) -> None:
    """删除上一次构建的 collection；不存在时可安全忽略。"""
    try:
        old_store = _vector_store or Chroma(
            embedding_function=embedding,
            persist_directory=Config.CHROMA_PERSIST_DIR,
        )
        old_store.delete_collection()
    except Exception:
        logger.debug("旧向量 collection 不存在或无法删除", exc_info=True)


def _init() -> Chroma:
    persist_dir = Path(Config.CHROMA_PERSIST_DIR)
    if (persist_dir / "chroma.sqlite3").exists():
        logger.info("加载已有向量库: %s", persist_dir)
        return Chroma(embedding_function=create_embedding_model(), persist_directory=str(persist_dir))
    logger.info("向量库不存在，自动构建...")
    from .ingestion import rebuild_knowledge_base
    rebuild_knowledge_base()
    assert _vector_store is not None
    return _vector_store


def mark_stale() -> None:
    Path(Config.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
    STALE_FILE.touch()
    logger.info("已标记知识库为需要重建")


def is_stale() -> bool:
    """Embedding 或切片策略变更后，禁止混用新旧向量。"""
    return STALE_FILE.exists()


def get_stats() -> dict:
    from .loaders import count_files
    doc_count = count_files()
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
        deleted = _delete_source_chunks(store, filename)
        from .retrieval import invalidate_lexical_cache
        invalidate_lexical_cache()
        return deleted
    except Exception:
        logger.exception("删除文档块失败: %s", filename)
        return 0


def _delete_source_chunks(store: Chroma, source: str) -> int:
    """删除一个 source 的所有块；供删除与增量更新共用。"""
    results = store._collection.get(where={"source": source})
    ids = results.get("ids", [])
    if ids:
        store._collection.delete(ids=ids)
    return len(ids)
