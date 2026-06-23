"""用户聊天系统 — 独立 Streamlit 应用（端口 8502）。

启动: streamlit run frontend/user/app.py --server.port 8502

功能: 用户注册 → 登录 → 对话（会话隔离，无管理员功能）
"""

import sys, os, logging, traceback
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 加载 .env（读取 STREAMLIT_API_URL 等环境变量）
from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("user")

import streamlit as st
import httpx, json, time

# API 地址：本地用 127.0.0.1:8000，公网隧道用环境变量 STREAMLIT_API_URL
API = os.environ.get("STREAMLIT_API_URL", "http://127.0.0.1:8000/api")
_client = httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=30)

st.set_page_config(page_title="网安学院问答机器人", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="expanded")

# ── State ──
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "token" not in st.session_state:
    st.session_state["token"] = ""
if "user" not in st.session_state:
    st.session_state["user"] = {}
if "session_id" not in st.session_state:
    st.session_state["session_id"] = None
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "page" not in st.session_state:
    st.session_state["page"] = "login"


def main():
    try:
        _route()
    except Exception:
        st.error(f"页面异常\n```\n{traceback.format_exc()[-1000:]}\n```")


def _route():
    if st.session_state["authenticated"]:
        _render_chat()
    elif st.session_state["page"] == "register":
        _render_register()
    else:
        _render_login()


# ═══════════════════════════════════════════════════════
# 登录
# ═══════════════════════════════════════════════════════

def _render_login():
    st.title("🛡️ 网安学院智能问答机器人")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.subheader("用户登录")
        u = st.text_input("用户名", key="login_u")
        p = st.text_input("密码", type="password", key="login_p")

        c4, c5 = st.columns(2)
        with c4:
            if st.button("登录", type="primary", use_container_width=True):
                if not u or not p:
                    st.error("请输入用户名和密码")
                    return
                try:
                    r = _client.post(f"{API}/auth/login", json={"username": u, "password": p})
                    if r.status_code != 200:
                        st.error("用户名或密码错误")
                        return
                    d = r.json()
                    if d.get("is_admin"):
                        st.error("请使用普通用户账号登录")
                        return
                    st.session_state["token"] = d["access_token"]
                    st.session_state["user"] = {"id": d["user_id"], "username": d["username"]}
                    st.session_state["authenticated"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"连接失败: {e}")
        with c5:
            if st.button("注册新账号", use_container_width=True):
                st.session_state["page"] = "register"
                st.rerun()


# ═══════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════

def _render_register():
    st.title("🛡️ 注册新账号")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        u = st.text_input("用户名", key="reg_u")
        p1 = st.text_input("密码（至少3位）", type="password", key="reg_p1")
        p2 = st.text_input("确认密码", type="password", key="reg_p2")

        c4, c5 = st.columns(2)
        with c4:
            if st.button("注册", type="primary", use_container_width=True):
                if not u or not p1:
                    st.error("请填写用户名和密码")
                elif len(u) < 2:
                    st.error("用户名至少2个字符")
                elif len(p1) < 3:
                    st.error("密码至少3个字符")
                elif p1 != p2:
                    st.error("两次密码不一致")
                else:
                    try:
                        r = _client.post(f"{API}/auth/register", json={"username": u, "password": p1})
                        if r.status_code != 200:
                            try:
                                st.error(r.json().get("detail", "注册失败"))
                            except Exception:
                                st.error(f"注册失败 ({r.status_code})")
                            return
                        d = r.json()
                        st.success(f"注册成功！请登录")
                        st.session_state["token"] = d["access_token"]
                        st.session_state["user"] = {"id": d["id"], "username": d["username"]}
                        st.session_state["authenticated"] = True
                        st.session_state["page"] = "login"
                        st.rerun()
                    except Exception as e:
                        st.error(f"连接失败: {e}")
        with c5:
            if st.button("返回登录", use_container_width=True):
                st.session_state["page"] = "login"
                st.rerun()


# ═══════════════════════════════════════════════════════
# 聊天
# ═══════════════════════════════════════════════════════

def _render_chat():
    _render_sidebar()
    _chat_main()


def _render_sidebar():
    t = st.session_state["token"]
    u = st.session_state["user"]
    h = {"Authorization": f"Bearer {t}"}

    with st.sidebar:
        st.markdown(f"👤 **{u.get('username', '')}**")
        st.divider()

        if st.button("➕ 新建会话", use_container_width=True):
            r = _client.post(f"{API}/chat/sessions", headers=h)
            st.session_state["session_id"] = r.json()["id"]
            st.session_state["messages"] = []
            st.rerun()

        try:
            sessions = _client.get(f"{API}/chat/sessions", headers=h).json()
        except Exception:
            sessions = []

        current = st.session_state.get("session_id")
        for s in sessions:
            sid = s["id"]
            active = sid == current
            c1, c2 = st.columns([5, 1])
            with c1:
                lbl = ("▸ " if active else "  ") + s.get("title", "未命名")
                if st.button(lbl, key=f"s_{sid}", use_container_width=True,
                             type="primary" if active else "secondary"):
                    st.session_state["session_id"] = sid
                    st.rerun()
            with c2:
                if st.button("🗑", key=f"d_{sid}"):
                    _client.delete(f"{API}/chat/sessions/{sid}", headers=h)
                    if active:
                        st.session_state["session_id"] = None
                        st.session_state["messages"] = []
                    st.rerun()

        st.divider()
        with st.expander("🔒 修改密码"):
            old_pw = st.text_input("原密码", type="password", key="cp_old")
            new_pw = st.text_input("新密码", type="password", key="cp_new")
            if st.button("确认修改", use_container_width=True):
                if not old_pw or not new_pw:
                    st.error("请填写原密码和新密码")
                elif len(new_pw) < 3:
                    st.error("新密码至少3个字符")
                else:
                    try:
                        r = _client.post(f"{API}/auth/change-password", headers=h, json={
                            "old_password": old_pw, "new_password": new_pw
                        })
                        if r.status_code == 200:
                            st.success("密码修改成功")
                        else:
                            st.error(r.json().get("detail", "修改失败"))
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        if st.button("🚪 退出登录", use_container_width=True):
            st.session_state.clear()
            st.session_state["page"] = "login"
            st.rerun()


def _chat_main():
    """统一的聊天主函数：无 session 时引导创建，有 session 时渲染历史 + 处理输入。"""
    t = st.session_state["token"]
    h = {"Authorization": f"Bearer {t}"}
    sid = st.session_state.get("session_id")

    # 拉取当前会话消息
    msgs = []
    if sid:
        try:
            msgs = _client.get(f"{API}/chat/sessions/{sid}/messages", headers=h).json()
        except Exception:
            msgs = []
    st.session_state["messages"] = msgs

    # 标题
    if sid is None:
        st.title("🛡️ 网安学院智能问答机器人")
        st.caption("新建会话或直接在下方提问")
    else:
        st.title(msgs[0]["content"][:30] if msgs else "新对话")

    # 渲染历史消息
    for m in msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # 输入框
    p = st.chat_input("请输入您的问题...")
    if not p:
        return

    # 首次提问时自动创建会话
    if sid is None:
        r = _client.post(f"{API}/chat/sessions", headers=h)
        sid = r.json()["id"]
        st.session_state["session_id"] = sid

    # 立即显示用户消息
    with st.chat_message("user"):
        st.markdown(p)

    # 流式获取 LLM 回复
    with st.chat_message("assistant"):
        sp = st.empty()
        full = ""
        try:
            with _client.stream("POST", f"{API}/chat/send", headers=h,
                                json={"message": p, "session_id": sid}, timeout=120) as r:
                if r.status_code != 200:
                    sp.error(f"请求失败 ({r.status_code})")
                else:
                    for line in r.iter_lines():
                        if line.startswith("data: "):
                            d = json.loads(line[6:])
                            if d.get("done"):
                                break
                            full += d.get("token", "")
                            sp.markdown(full + "▌")
                    sp.markdown(full or "抱歉，未能生成回复。")
        except Exception as e:
            sp.error(f"调用失败: {e}")

    # 流式结束后刷新一次，让消息从 DB 加载到正常历史中
    st.rerun()


if __name__ == "__main__":
    main()
