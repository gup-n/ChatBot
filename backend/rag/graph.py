"""LangGraph 图 — 关键词路由 + 向量检索（零 LLM 调用）。"""

import logging
from typing import Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from ..config import Config

logger = logging.getLogger(__name__)

_BLOCK_KW = ["色情", "赌博", "毒品", "暴力恐怖", "颠覆国家", "分裂国家", "邪教", "诈骗", "枪支", "违禁品", "政治敏感", "反动", "推翻", "暴乱"]


def _check_sensitive(text: str) -> bool:
    return any(kw in text.lower() for kw in _BLOCK_KW)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    session_id: str
    pending_clarification: bool
    retrieval_context: str | None
    next_action: str
    tool_results: str | None


def route_node(state: AgentState) -> dict:
    messages = state["messages"]
    session_id = state["session_id"]
    user_input = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            user_input = m.content if hasattr(m, "content") else str(m)
            break
    if _check_sensitive(user_input):
        logger.info("Route: block, session=%s", session_id)
        return {"next_action": "block"}
    logger.info("Route: agent, session=%s", session_id)
    return {"next_action": "agent"}


def block_node(state: AgentState) -> dict:
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content=Config.BLOCK_MESSAGE)]}


def search_node(state: AgentState) -> dict:
    messages = state["messages"]
    user_input = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            user_input = m.content if hasattr(m, "content") else str(m)
            break
    from .vector_store import search
    hits = search(user_input) if user_input else []
    tool_results = "\n\n".join(
        f"[来源: {h['source']} | 相关度: {h['score']:.4f}]\n{h['content']}" for h in hits
    ) if hits else None
    logger.info("Search: %d hits", len(hits))
    return {"tool_results": tool_results}


def decide_next_node(state: AgentState) -> Literal["block", "agent"]:
    return state.get("next_action", "agent")


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)
    workflow.add_node("route", route_node)
    workflow.add_node("block", block_node)
    workflow.add_node("search", search_node)
    workflow.set_entry_point("route")
    workflow.add_conditional_edges("route", decide_next_node, {"block": "block", "agent": "search"})
    workflow.add_edge("block", END)
    workflow.add_edge("search", END)
    return workflow.compile()


graph = build_graph()
