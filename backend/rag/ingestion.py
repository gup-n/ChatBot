"""知识库入库编排层：载入、切分并交给向量库持久化。"""

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .loaders import load_all, load_file
from .splitter import split_documents

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    document_count: int
    chunk_count: int


def rebuild_knowledge_base() -> IngestionResult:
    """重建完整知识库；向量库实现只负责保存已经切分好的 chunks。"""
    from .vector_store import replace_documents

    documents = load_all()
    chunks = split_documents(documents) if documents else []
    replace_documents(chunks)
    logger.info("知识库入库完成: documents=%d, chunks=%d", len(documents), len(chunks))
    return IngestionResult(document_count=len(documents), chunk_count=len(chunks))


def index_files(paths: list[Path]) -> IngestionResult:
    """增量写入指定文件，不影响其他文档已经建立的向量。"""
    from .vector_store import upsert_documents

    knowledge_dir = Path(Config.KNOWLEDGE_DIR).resolve()
    documents = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(knowledge_dir):
            raise ValueError(f"文件不在知识库目录中: {path}")
        source = resolved.relative_to(knowledge_dir).as_posix()
        loaded = load_file(resolved)
        for document in loaded:
            document.metadata["source"] = source
        documents.extend(loaded)

    chunks = split_documents(documents) if documents else []
    if not chunks:
        raise ValueError("文档中没有可提取并入库的文本内容")
    upsert_documents(chunks)
    logger.info("增量入库完成: files=%d, documents=%d, chunks=%d", len(paths), len(documents), len(chunks))
    return IngestionResult(document_count=len(documents), chunk_count=len(chunks))
