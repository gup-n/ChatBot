"""文档加载器 — 支持 txt/pdf/docx/json/csv。"""

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ..config import Config

logger = logging.getLogger(__name__)

_CHINESE_SEPARATORS = ["\n\n", "\n", "。", "，", " ", ""]


def load_documents(data_dir: str | None = None) -> list[Document]:
    data_dir = Path(data_dir or Config.KNOWLEDGE_DIR)
    if not data_dir.exists():
        return []
    docs: list[Document] = []
    files = sorted(f for f in data_dir.iterdir() if f.is_file() and f.suffix.lower() in _LOADERS)
    for fp in files:
        try:
            docs.extend(_LOADERS[fp.suffix.lower()](fp))
            logger.info("已加载: %s", fp.name)
        except Exception:
            logger.exception("加载失败: %s", fp.name)
    return docs


def split_documents(docs: list[Document], chunk_size: int = 512, chunk_overlap: int = 50) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        separators=_CHINESE_SEPARATORS, chunk_size=chunk_size,
        chunk_overlap=chunk_overlap, length_function=len,
    )
    return splitter.split_documents(docs)


def _load_txt(p: Path) -> list[Document]:
    return [Document(page_content=p.read_text(encoding="utf-8"), metadata={"source": p.name})]

def _load_pdf(p: Path) -> list[Document]:
    from pypdf import PdfReader
    reader = PdfReader(str(p))
    return [Document(page_content=page.extract_text().strip(), metadata={"source": p.name, "page": i})
            for i, page in enumerate(reader.pages, 1) if page.extract_text() and page.extract_text().strip()]

def _load_docx(p: Path) -> list[Document]:
    import docx2txt
    text = docx2txt.process(str(p))
    return [Document(page_content=text.strip(), metadata={"source": p.name})] if text and text.strip() else []

def _load_json(p: Path) -> list[Document]:
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    docs = []
    for item in (data if isinstance(data, list) else []):
        if isinstance(item, str):
            docs.append(Document(page_content=item, metadata={"source": p.name}))
        elif isinstance(item, dict):
            content = item.pop("content", item.pop("text", str(item)))
            docs.append(Document(page_content=content, metadata={"source": p.name, **item}))
    return docs

def _load_csv(p: Path) -> list[Document]:
    docs = []
    with open(p, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            content = row.pop("content", None) or row.pop("text", None) or " | ".join(f"{k}: {v}" for k, v in row.items() if v)
            docs.append(Document(page_content=content, metadata={"source": p.name, **row}))
    return docs

_LOADERS = {".txt": _load_txt, ".md": _load_txt, ".pdf": _load_pdf, ".docx": _load_docx, ".json": _load_json, ".csv": _load_csv}
SUPPORTED_EXTENSIONS = list(_LOADERS.keys())


def load_single_document(filepath: Path) -> list[Document]:
    suffix = filepath.suffix.lower()
    if suffix not in _LOADERS:
        raise ValueError(f"不支持的文件格式: {suffix}")
    return _LOADERS[suffix](filepath)


def get_document_info(data_dir: str | None = None) -> list[dict]:
    data_dir = Path(data_dir or Config.KNOWLEDGE_DIR)
    if not data_dir.exists():
        return []
    infos = []
    items = sorted(data_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    for fp in items:
        if not fp.is_file() or fp.name.startswith("."):
            continue
        if fp.suffix.lower() not in _LOADERS:
            continue
        st = fp.stat()
        infos.append({
            "filename": fp.name,
            "size_bytes": st.st_size,
            "format": fp.suffix.lower().lstrip("."),
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone(timedelta(hours=8))).isoformat(),
            "created_at": datetime.fromtimestamp(st.st_ctime, tz=timezone(timedelta(hours=8))).isoformat(),
        })
    return infos


def read_document_content(filename: str, data_dir: str | None = None) -> dict:
    data_dir = Path(data_dir or Config.KNOWLEDGE_DIR)
    fp = data_dir / filename
    if not fp.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not fp.resolve().is_relative_to(data_dir.resolve()):
        raise ValueError("非法文件路径")
    suffix = fp.suffix.lower()
    if suffix not in _LOADERS:
        raise ValueError(f"不支持的文件格式: {suffix}")
    # 纯文本格式直接读取，二进制格式用 loader 提取文本
    if suffix in (".txt", ".md", ".json", ".csv"):
        content = fp.read_text(encoding="utf-8")
    else:
        docs = _LOADERS[suffix](fp)
        content = "\n\n---\n\n".join(d.page_content for d in docs) if docs else "(无法提取文本内容)"
    return {"filename": fp.name, "content": content, "size_bytes": fp.stat().st_size}


def count_knowledge_files(data_dir: str | None = None) -> int:
    """快速统计知识库文件数（不解析内容）。"""
    data_dir = Path(data_dir or Config.KNOWLEDGE_DIR)
    if not data_dir.exists():
        return 0
    return sum(1 for f in data_dir.iterdir()
               if f.is_file() and not f.name.startswith(".")
               and f.suffix.lower() in _LOADERS)
