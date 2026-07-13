"""知识库数据切分层：Document 统一转换为可入库的 Chunk。"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

def split_documents(documents: list[Document], chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[Document]:
    """按中文自然边界切分，并给每个片段补充 chunk_index 元数据。"""
    from ..config import Config

    size = chunk_size if chunk_size is not None else Config.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else Config.CHUNK_OVERLAP
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("CHUNK_SIZE 必须大于 0，且 CHUNK_OVERLAP 必须不小于 0 并小于 CHUNK_SIZE")
    splitter = RecursiveCharacterTextSplitter(separators=Config.CHUNK_SEPARATORS, chunk_size=size, chunk_overlap=overlap, length_function=len)
    chunks = splitter.split_documents(documents)
    for index, chunk in enumerate(chunks):
        chunk.metadata = {**chunk.metadata, "chunk_index": index}
    return chunks
