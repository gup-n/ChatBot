"""知识库数据载入层：文件统一转换为带标准元数据的 Document。"""

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from langchain_core.documents import Document

from ..config import Config

logger = logging.getLogger(__name__)


def _metadata(path: Path, **extra: object) -> dict:
    """Chroma 元数据仅保存标量；复杂 JSON 字段统一序列化为字符串。"""
    normalized = {
        key: value if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False)
        for key, value in extra.items() if value is not None
    }
    return {"source": path.name, "file_type": path.suffix.lower().lstrip("."), **normalized}


def load_text(path: Path) -> list[Document]:
    return [Document(page_content=path.read_text(encoding="utf-8"), metadata=_metadata(path))]


def load_pdf(path: Path) -> list[Document]:
    from pypdf import PdfReader

    documents = []
    for page_number, page in enumerate(PdfReader(str(path)).pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            documents.append(Document(page_content=text.strip(), metadata=_metadata(path, page=page_number)))
    return documents


def load_docx(path: Path) -> list[Document]:
    import docx2txt

    text = docx2txt.process(str(path)) or ""
    return [Document(page_content=text.strip(), metadata=_metadata(path))] if text.strip() else []


def load_json(path: Path) -> list[Document]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    documents = []
    for index, item in enumerate(records):
        if isinstance(item, str):
            documents.append(Document(page_content=item, metadata=_metadata(path, record=index)))
        elif isinstance(item, dict):
            item = item.copy()
            content = str(item.pop("content", item.pop("text", item)))
            documents.append(Document(page_content=content, metadata=_metadata(path, record=index, **item)))
    return documents


def load_csv(path: Path) -> list[Document]:
    documents = []
    with path.open(encoding="utf-8", newline="") as file:
        for index, row in enumerate(csv.DictReader(file)):
            row = dict(row)
            content = row.pop("content", None) or row.pop("text", None)
            content = str(content or " | ".join(f"{key}: {value}" for key, value in row.items() if value))
            if content.strip():
                documents.append(Document(page_content=content, metadata=_metadata(path, record=index, **row)))
    return documents


LOADERS = {".txt": load_text, ".md": load_text, ".pdf": load_pdf, ".docx": load_docx, ".json": load_json, ".csv": load_csv}
SUPPORTED_EXTENSIONS = list(LOADERS)


def load_file(path: Path) -> list[Document]:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"不支持的文件格式: {path.suffix.lower()}")
    return loader(path)


def load_all(data_dir: str | None = None) -> list[Document]:
    directory = Path(data_dir or Config.KNOWLEDGE_DIR)
    if not directory.exists():
        return []
    documents = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.suffix.lower() in LOADERS):
        try:
            loaded = load_file(path)
            source = path.relative_to(directory).as_posix()
            for document in loaded:
                document.metadata["source"] = source
            documents.extend(loaded)
            logger.info("已加载: %s", source)
        except Exception:
            logger.exception("加载失败: %s", path.name)
    return documents


def list_document_info(data_dir: str | None = None) -> list[dict]:
    directory = Path(data_dir or Config.KNOWLEDGE_DIR)
    if not directory.exists():
        return []
    infos = []
    for path in sorted(directory.rglob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in LOADERS:
            stat = path.stat()
            infos.append({"filename": path.relative_to(directory).as_posix(), "size_bytes": stat.st_size, "format": path.suffix.lower().lstrip("."), "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone(timedelta(hours=8))).isoformat(), "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone(timedelta(hours=8))).isoformat()})
    return infos


def read_document(filename: str, data_dir: str | None = None) -> dict:
    directory = Path(data_dir or Config.KNOWLEDGE_DIR)
    path = directory / filename
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("非法文件路径")
    if path.suffix.lower() not in LOADERS:
        raise ValueError(f"不支持的文件格式: {path.suffix.lower()}")
    if path.suffix.lower() in {".txt", ".md", ".json", ".csv"}:
        content = path.read_text(encoding="utf-8")
    else:
        content = "\n\n---\n\n".join(document.page_content for document in load_file(path)) or "(无法提取文本内容)"
    return {"filename": path.name, "content": content, "size_bytes": path.stat().st_size}


def count_files(data_dir: str | None = None) -> int:
    directory = Path(data_dir or Config.KNOWLEDGE_DIR)
    return sum(1 for path in directory.rglob("*") if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in LOADERS) if directory.exists() else 0
