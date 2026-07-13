from backend.rag.loaders import load_all, load_file
from backend.rag.ingestion import index_files
from backend.rag.splitter import split_documents
from backend.config import Config


def test_loader_and_splitter_use_standard_metadata(tmp_path):
    source = tmp_path / "knowledge.txt"
    source.write_text("第一段内容。\n\n第二段内容。", encoding="utf-8")

    documents = load_file(source)
    chunks = split_documents(documents, chunk_size=8, chunk_overlap=1)

    assert documents[0].metadata == {"source": "knowledge.txt", "file_type": "txt"}
    assert chunks
    assert all("chunk_index" in chunk.metadata for chunk in chunks)


def test_load_all_recursively_preserves_relative_source(tmp_path, monkeypatch):
    nested = tmp_path / "college" / "teachers"
    nested.mkdir(parents=True)
    (nested / "info.txt").write_text("教师信息", encoding="utf-8")
    monkeypatch.setattr("backend.rag.loaders.Config.KNOWLEDGE_DIR", str(tmp_path))

    documents = load_all()

    assert len(documents) == 1
    assert documents[0].metadata["source"] == "college/teachers/info.txt"


def test_splitter_uses_environment_strategy(monkeypatch):
    monkeypatch.setattr(Config, "CHUNK_SIZE", 8)
    monkeypatch.setattr(Config, "CHUNK_OVERLAP", 1)
    monkeypatch.setattr(Config, "CHUNK_SEPARATORS", ["。", ""])
    from langchain_core.documents import Document

    chunks = split_documents([Document(page_content="甲乙丙丁。戊己庚辛。", metadata={})])
    assert chunks
    assert all("chunk_index" in chunk.metadata for chunk in chunks)


def test_index_files_upserts_only_new_file_chunks(tmp_path, monkeypatch):
    source = tmp_path / "new.txt"
    source.write_text("这是增量入库的文本内容。", encoding="utf-8")
    captured = []
    monkeypatch.setattr(Config, "KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.setattr("backend.rag.vector_store.upsert_documents", lambda chunks: captured.extend(chunks))

    result = index_files([source])

    assert result.document_count == 1
    assert result.chunk_count == len(captured)
    assert captured
    assert {chunk.metadata["source"] for chunk in captured} == {"new.txt"}
