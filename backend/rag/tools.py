"""Agent 工具 — search_knowledge_base。"""

from langchain_core.tools import tool


@tool
def search_knowledge_base(query: str) -> str:
    """检索网安学院知识库。"""
    from .vector_store import search
    hits = search(query)
    if not hits:
        return "（知识库中未找到相关内容）"
    return "\n".join(f"[来源: {h['source']} | 相关度: {h['score']:.4f}]\n{h['content']}\n" for h in hits)
