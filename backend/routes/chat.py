"""聊天路由 — 会话 / 消息 / SSE 流式回答。"""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from ..schemas import ChatRequest
from ..database import Database
from ..config import Config
from ..main import get_db
from ..rag.graph import graph
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 会话 ────────────────────────────────────────

@router.get("/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    db = get_db()
    return db.list_sessions(user["id"])


@router.post("/sessions")
def create_session(user: dict = Depends(get_current_user)):
    db = get_db()
    sid = db.create_session(user["id"])
    return {"id": sid, "title": "新会话"}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    sess = db.get_session(session_id)
    if not sess or sess.get("user_id") != user["id"]:
        raise HTTPException(404, "会话不存在")
    db.delete_session(session_id)
    return {"status": "ok"}


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    sess = db.get_session(session_id)
    if not sess or sess.get("user_id") != user["id"]:
        raise HTTPException(404, "会话不存在")
    return db.get_messages(session_id)


# ── 流式回答 ────────────────────────────────────

@router.post("/send")
def chat_send(req: ChatRequest, user: dict = Depends(get_current_user)):
    db = get_db()

    # 验证会话归属
    sess = db.get_session(req.session_id)
    if not sess or sess.get("user_id") != user["id"]:
        raise HTTPException(404, "会话不存在")

    if len(req.message) > Config.MAX_CHAT_MESSAGE_CHARS:
        raise HTTPException(413, f"消息超过长度限制（{Config.MAX_CHAT_MESSAGE_CHARS} 个字符）")

    # 保存用户消息
    db.add_message(req.session_id, "user", req.message)

    # 加载最近消息
    rows = db.get_recent_messages(req.session_id, limit=Config.MAX_CONTEXT_MESSAGES)
    from langchain_core.messages import HumanMessage, AIMessage
    lc_msgs = []
    for r in rows:
        if r["role"] == "user":
            lc_msgs.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            lc_msgs.append(AIMessage(content=r["content"]))

    inp = {
        "messages": lc_msgs,
        "session_id": req.session_id,
        "pending_clarification": False,
        "retrieval_context": None,
        "next_action": "agent",
        "tool_results": None,
    }

    # 运行 Graph。检索/Embedding 服务异常必须转换为 SSE 提示，不能让 ASGI 请求崩溃。
    try:
        final_state = graph.invoke(inp)
    except Exception as exc:
        logger.exception("RAG 检索失败")
        message = "📚 知识库检索暂时不可用。请检查 Embedding 服务、模型名称和向量索引后重试。"
        db.add_message(req.session_id, "assistant", message)

        def _retrieval_error_stream():
            yield f"data: {json.dumps({'token': message}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'full_text': message}, ensure_ascii=False)}\n\n"

        return StreamingResponse(_retrieval_error_stream(), media_type="text/event-stream")
    action = final_state.get("next_action", "agent")
    tool_results = final_state.get("tool_results")

    if action == "block":
        db.add_message(req.session_id, "assistant", Config.BLOCK_MESSAGE)
        def _block_stream():
            yield f"data: {json.dumps({'token': Config.BLOCK_MESSAGE})}\n\n"
            yield f"data: {json.dumps({'done': True, 'full_text': Config.BLOCK_MESSAGE})}\n\n"
        return StreamingResponse(_block_stream(), media_type="text/event-stream")

    # 构造最终 prompt
    from langchain_core.messages import SystemMessage
    from ..models.llm import create_chat_model

    llm = create_chat_model()

    system_content = (
        "你是宁波工程学院网安学院的智能问答助手。\n\n"
        "规则：\n"
        "1. 如果用户问题指代不清或过于模糊，请礼貌追问\n"
        "2. 用户如果只是打招呼/闲聊/感谢，简单友好回复即可\n"
        "3. 如果问题涉及学院具体信息，优先基于提供的检索结果回答；若检索结果不足以回答，诚实告知\n"
        "4. 回答简洁清晰，使用中文；引用信息时直接写来源文件名（如「招生简章.txt」），禁止使用【1†L1-L4】等数字标注\n\n"
        f"你的知识范围：{Config.KB_OVERVIEW}"
    )

    final_msgs = [SystemMessage(content=system_content)]
    for m in lc_msgs[:-1]:
        final_msgs.append(m)
    if tool_results:
        final_msgs.append(SystemMessage(content=f"知识库检索结果（供参考）：\n\n{tool_results}"))
    final_msgs.append(HumanMessage(content=req.message))

    # 自动标题
    _auto_title(db, req.session_id)

    def _event_stream():
        full_text = ""
        error_msg = ""
        try:
            for chunk in llm.stream(final_msgs):
                if chunk.content:
                    full_text += chunk.content
                    yield f"data: {json.dumps({'token': chunk.content}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("LLM stream error")
            error_msg = f"[错误: {e}]"
            yield f"data: {json.dumps({'token': error_msg}, ensure_ascii=False)}\n\n"
        # 保存完整回答（异常时保存错误信息，避免前端 rerun 后显示空白）
        save_text = error_msg if (not full_text and error_msg) else full_text
        try:
            if save_text.strip():
                db.add_message(req.session_id, "assistant", save_text)
        except Exception:
            pass
        yield f"data: {json.dumps({'done': True, 'full_text': save_text}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


def _auto_title(db: Database, sid: str) -> None:
    msgs = db.get_messages(sid)
    users = [m for m in msgs if m["role"] == "user"]
    if len(users) == 1:
        db.rename_session(sid, users[0]["content"][:30])
