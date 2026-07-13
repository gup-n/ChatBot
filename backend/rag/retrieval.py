"""知识库检索层：融合向量语义检索与 BM25 关键词检索。"""

from langchain_core.documents import Document

from .types import RetrievalHit
from ..config import Config

_lexical_documents: list[Document] | None = None


def _document_key(document: Document) -> tuple[str, int, str]:
    return (
        str(document.metadata.get("source", "")),
        int(document.metadata.get("chunk_index", 0)),
        document.page_content,
    )


def _get_lexical_documents() -> list[Document]:
    global _lexical_documents
    if _lexical_documents is None:
        from .vector_store import get_vector_store

        data = get_vector_store()._collection.get(include=["documents", "metadatas"])
        _lexical_documents = [
            Document(page_content=content, metadata=metadata or {})
            for content, metadata in zip(data.get("documents", []), data.get("metadatas", []))
            if content
        ]
    return _lexical_documents


def invalidate_lexical_cache() -> None:
    """向量库重建或增删文档后清理关键词索引缓存。"""
    global _lexical_documents
    _lexical_documents = None


def retrieve(query: str, top_k: int | None = None) -> list[RetrievalHit]:
    from .vector_store import similarity_search

    result_limit = top_k or Config.RETRIEVAL_TOP_K
    candidate_limit = max(result_limit * 4, 24)
    vector_matches = similarity_search(query, candidate_limit)
    vector_ranks = {
        _document_key(document): (rank, float(distance), document)
        for rank, (document, distance) in enumerate(vector_matches, 1)
        if float(distance) <= Config.RETRIEVAL_SCORE_THRESHOLD
    }
    if Config.RETRIEVAL_MODE == "vector":
        merged = [(document, distance, "vector") for _, distance, document in vector_ranks.values()]
        return _to_hits(merged[:result_limit])

    from .lexical import search as lexical_search

    lexical_matches = lexical_search(_get_lexical_documents(), query, candidate_limit)
    lexical_ranks = {
        _document_key(document): (rank, document)
        for rank, (document, _score) in enumerate(lexical_matches, 1)
    }
    keys = set(vector_ranks) | set(lexical_ranks)
    ranked = []
    for key in keys:
        vector = vector_ranks.get(key)
        lexical = lexical_ranks.get(key)
        # Reciprocal Rank Fusion：不需要把向量距离和 BM25 分数强行归一化。
        fusion_score = (1 / (60 + vector[0]) if vector else 0) + (1 / (60 + lexical[0]) if lexical else 0)
        document = vector[2] if vector else lexical[1]
        distance = vector[1] if vector else 1.0
        method = "hybrid" if vector and lexical else "vector" if vector else "lexical"
        ranked.append((fusion_score, document, distance, method))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return _to_hits([(document, distance, method) for _, document, distance, method in ranked[:result_limit]])


def _to_hits(matches: list[tuple[Document, float, str]]) -> list[RetrievalHit]:
    hits = []
    for document, distance, method in matches:
        metadata = {**document.metadata, "retrieval_method": method}
        hits.append(RetrievalHit(
            content=document.page_content,
            source=document.metadata.get("source", "未知"),
            distance=distance,
            metadata=metadata,
        ))
    return hits


def search(query: str, top_k: int | None = None) -> list[dict]:
    """兼容 API：返回 JSON 可序列化的标准检索结果。"""
    return [hit.to_dict() for hit in retrieve(query, top_k)]
