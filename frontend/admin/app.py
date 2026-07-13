"""管理员控制台 — 独立 Streamlit 应用（端口 8501）。

启动: streamlit run frontend/admin/app.py --server.port 8501

功能: 管理员登录 → 模型配置 → 用户管理 → 知识库管理 → 启动服务
启动服务后，用户在 8502 端口访问聊天系统。
"""

import sys, os, json, logging, traceback, secrets, threading, time
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, ".env"))
from backend.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("admin")

import streamlit as st
import httpx

# API 地址：本地用 127.0.0.1:8000，公网隧道用环境变量 STREAMLIT_API_URL
API = os.environ.get("STREAMLIT_API_URL", "http://127.0.0.1:8000/api")
HTTP_CLIENT_TIMEOUT_SECONDS = Config.HTTP_CLIENT_TIMEOUT_SECONDS
_client = httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=HTTP_CLIENT_TIMEOUT_SECONDS)

# Streamlit 浏览器刷新会创建新 session；只保存随机恢复标识，绝不把 JWT 放进 URL。
@st.cache_resource
def _admin_resume_store() -> tuple[dict[str, tuple[str, float]], threading.Lock]:
    return {}, threading.Lock()


def _remove_resume_id() -> None:
    if "admin_session" in st.query_params:
        del st.query_params["admin_session"]

st.set_page_config(page_title="管理员控制台", page_icon="⚙️", layout="wide")

ACTION_LABELS = {
    "login": "用户登录",
    "register": "用户注册",
    "change_password": "修改密码",
    "reset_password": "重置密码",
    "create_user": "创建用户",
    "delete_user": "删除用户",
    "update_config": "修改配置",
    "upload_doc": "上传文档",
    "create_doc": "编写文档",
    "fetch_url": "联网获取",
    "delete_doc": "删除文档",
    "rebuild": "重建索引",
    "warmup": "启动预热",
}

PROVIDER_META = {
    "openai_compatible": {
        "label": "OpenAI 兼容接口（DeepSeek / OpenAI / 本地网关等）",
        "base_url": "https://api.openai.com/v1",
        "needs_key": True,
        "fetchable": True,
    },
    "ollama": {
        "label": "Ollama（本地）",
        "base_url": "http://localhost:11434",
        "needs_key": False,
        "fetchable": True,
    },
    "huggingface": {
        "label": "HuggingFace / Sentence Transformers（本地）",
        "needs_key": False,
        "fetchable": False,
    },
}


def _get_audit_actions(headers: dict) -> list[str]:
    """从后端获取所有已出现的操作类型。"""
    try:
        return _client.get(f"{API}/admin/audit-logs/actions", headers=headers).json().get("actions", [])
    except Exception:
        return []


def _render_model_editor(kind: str, title: str, config: dict, headers: dict) -> None:
    """渲染 LLM 或 Embedding 的统一配置编辑器。"""
    allowed = ["openai_compatible", "ollama"]
    if kind == "embedding":
        allowed.append("huggingface")
    active = config.get("provider", allowed[0])
    all_settings = config.get("all_settings", {})
    provider = st.selectbox(
        f"{title}提供商", allowed,
        index=allowed.index(active) if active in allowed else 0,
        format_func=lambda item: PROVIDER_META[item]["label"], key=f"{kind}_provider",
    )
    meta = PROVIDER_META[provider]
    saved = all_settings.get(provider, {})
    settings: dict[str, str] = {}
    if meta["needs_key"]:
        settings["api_key"] = st.text_input(
            "API Key", value=saved.get("api_key", ""), type="password", key=f"{kind}_{provider}_key"
        )
    if "base_url" in meta:
        settings["base_url"] = st.text_input(
            "服务地址", value=saved.get("base_url", meta["base_url"]), key=f"{kind}_{provider}_url"
        )
    model = st.text_input(
        "模型名称", value=saved.get("model", ""),
        placeholder="例如 gpt-4o-mini、deepseek-chat、qwen2.5:7b 或 nomic-embed-text",
        key=f"{kind}_{provider}_model",
    )
    settings["model"] = model
    if kind == "embedding" and provider == "ollama":
        st.info("请使用专用嵌入模型，例如 `nomic-embed-text`；首次使用需执行 `ollama pull nomic-embed-text`。聊天模型不能替代 Embedding 模型。")

    if meta["fetchable"] and st.button("🔍 拉取模型列表", key=f"{kind}_{provider}_fetch"):
        if meta["needs_key"] and not settings.get("api_key"):
            st.error("请先填写 API Key")
        else:
            try:
                response = _client.post(
                    f"{API}/admin/models", headers=headers,
                    json={"kind": kind, "provider": provider, **settings},
                )
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    st.session_state[f"{kind}_{provider}_models"] = [item["id"] for item in models]
                    st.success(f"找到 {len(models)} 个模型；可复制名称到上方输入框。")
                else:
                    st.error(response.json().get("detail", "拉取失败"))
            except Exception as exc:
                st.error(f"拉取失败: {exc}")
    models = st.session_state.get(f"{kind}_{provider}_models", [])
    if models:
        st.caption("可用模型：" + " | ".join(models[:12]))

    if st.button(f"💾 保存{title}配置", type="primary", key=f"{kind}_{provider}_save"):
        try:
            response = _client.put(
                f"{API}/admin/config", headers=headers,
                json={"kind": kind, "provider": provider, "settings": settings},
            )
            if response.status_code == 200:
                suffix = "请重建向量索引后生效。" if kind == "embedding" else "已立即生效。"
                st.success(f"{title}配置已保存，{suffix}")
                st.rerun()
            else:
                st.error(response.json().get("detail", "保存失败"))
        except Exception as exc:
            st.error(f"保存失败: {exc}")

# ── State ──
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False
if "token" not in st.session_state:
    st.session_state["token"] = ""


def _restore_admin_session() -> None:
    """从短期随机恢复标识恢复登录；后端仍会校验 JWT 是否有效。"""
    if st.session_state["admin_logged_in"]:
        return
    resume_id = st.query_params.get("admin_session")
    if not resume_id:
        return
    sessions, lock = _admin_resume_store()
    with lock:
        record = sessions.get(str(resume_id))
    if not record or record[1] <= time.time():
        _remove_resume_id()
        return
    token = record[0]
    try:
        response = _client.get(f"{API}/admin/config", headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 200:
            st.session_state["token"] = token
            st.session_state["admin_logged_in"] = True
            return
    except httpx.HTTPError:
        pass
    with lock:
        sessions.pop(str(resume_id), None)
    _remove_resume_id()


def _persist_admin_session(token: str) -> None:
    """写入 URL 中的随机句柄；过期时间与 JWT 配置保持一致。"""
    resume_id = secrets.token_urlsafe(32)
    expires_at = time.time() + Config.JWT_TOKEN_EXPIRE_HOURS * 3600
    sessions, lock = _admin_resume_store()
    with lock:
        sessions[resume_id] = (token, expires_at)
    st.query_params["admin_session"] = resume_id


def _clear_admin_session() -> None:
    resume_id = st.query_params.get("admin_session")
    if resume_id:
        sessions, lock = _admin_resume_store()
        with lock:
            sessions.pop(str(resume_id), None)
    _remove_resume_id()
    st.session_state["token"] = ""
    st.session_state["admin_logged_in"] = False


def main():
    try:
        _route()
    except Exception:
        st.error(f"页面异常\n```\n{traceback.format_exc()[-1000:]}\n```")


def _route():
    _restore_admin_session()
    if st.session_state["admin_logged_in"]:
        _render_setup()
    else:
        _render_login()


# ═══ 登录 ═══
def _render_login():
    st.title("🛡️ 网安学院问答机器人 — 管理员控制台")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.subheader("管理员登录")
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")

        if st.button("登录", type="primary", use_container_width=True):
            if not u or not p:
                st.error("请输入用户名和密码")
                return
            try:
                r = _client.post(f"{API}/auth/login", json={"username": u, "password": p})
                if r.status_code != 200:
                    st.error("用户名或密码错误")
                    return
                data = r.json()
                if not data.get("is_admin"):
                    st.error("需要管理员账号")
                    return
                st.session_state["token"] = data["access_token"]
                st.session_state["admin_logged_in"] = True
                _persist_admin_session(data["access_token"])
                st.rerun()
            except Exception as e:
                st.error(f"连接后端失败: {e}")


# ═══ 设置页 ═══
def _render_setup():
    token = st.session_state["token"]
    h = {"Authorization": f"Bearer {token}"}

    st.title("⚙️ 管理员控制台")
    st.caption("配置模型、管理用户、管理知识库、启动服务")
    if st.button("退出登录", key="admin_logout"):
        _clear_admin_session()
        st.rerun()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔧 模型配置", "👥 用户管理", "📚 知识库管理", "🚀 启动服务", "📋 审计日志"])

    # ── Tab 1: 模型配置 ──
    with tab1:
        try:
            r = _client.get(f"{API}/admin/config", headers=h)
            cfg = r.json()
        except Exception:
            cfg = {"llm": {}, "embedding": {}}
        left, right = st.columns(2)
        with left:
            st.subheader("语言模型（LLM）")
            _render_model_editor("llm", "LLM", cfg.get("llm", {}), h)
        with right:
            st.subheader("向量嵌入模型（Embedding）")
            _render_model_editor("embedding", "Embedding", cfg.get("embedding", {}), h)
        st.info("LLM 保存后立即生效；Embedding 保存后必须在“知识库管理”中重建向量索引。")

    # ── Tab 2: 用户管理 ──
    with tab2:
        st.subheader("现有用户")
        try:
            users = _client.get(f"{API}/admin/users", headers=h).json()
        except Exception:
            users = []

        for u in users:
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1: st.write(f"**{u['username']}**")
            with c2: st.caption("管理员" if u.get("is_admin") else "普通用户")
            with c3:
                if not u.get("is_admin"):
                    if st.button("🗑", key=f"du_{u['id']}"):
                        _client.delete(f"{API}/admin/users/{u['id']}", headers=h)
                        st.rerun()
            with c4:
                if not u.get("is_admin"):
                    if st.button("🔑", key=f"rp_{u['id']}", help="重置为123456"):
                        _client.post(f"{API}/auth/reset-password", headers=h, json={"user_id": u['id']})
                        st.success(f"{u['username']} 密码已重置为 123456")
                        st.rerun()

        st.divider()
        st.subheader("添加用户")
        nu = st.text_input("用户名", key="nu")
        np = st.text_input("密码", type="password", key="np")
        if st.button("➕ 添加用户"):
            if not nu or not np: st.error("请输入用户名和密码")
            elif len(np) < 3: st.error("密码至少3位")
            else:
                r = _client.post(f"{API}/admin/users", headers=h, json={"username": nu, "password": np})
                if r.status_code == 200:
                    st.success(f"用户 {nu} 已创建")
                    st.rerun()
                else:
                    try: st.error(r.json().get("detail", "创建失败"))
                    except: st.error("创建失败")

    # ── Tab 3: 知识库管理 ──
    with tab3:
        st.subheader("📊 知识库状态")

        try:
            stats = _client.get(f"{API}/admin/documents/stats", headers=h).json()
        except Exception:
            stats = {"doc_count": 0, "chunk_count": 0, "last_build_time": None, "stale": False}

        try:
            knowledge_config = _client.get(f"{API}/admin/config", headers=h).json()
            chunking = knowledge_config.get("chunking", {})
            retrieval = knowledge_config.get("retrieval", {})
        except Exception:
            chunking = {}
            retrieval = {}

        try:
            rebuild_status = _client.get(f"{API}/admin/status", headers=h).json()
        except Exception:
            rebuild_status = {"warming_up": False, "warmup_error": None, "rebuild_status": "idle"}
        rebuild_phase = rebuild_status.get("rebuild_status") or ("running" if rebuild_status.get("warming_up") else "idle")
        rebuilding = rebuild_phase == "running"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("文档数量", stats.get("doc_count", 0))
        c2.metric("向量块数", stats.get("chunk_count", 0))
        lt = stats.get("last_build_time")
        c3.metric("最后构建", lt[:19] if lt else "从未")
        if stats.get("stale"):
            c4.warning("⚠️ 需要重建索引")
        else:
            c4.success("✅ 索引已同步")

        if rebuilding:
            st.info("⏳ 正在全量重建向量索引。完成前已禁用重建按钮，请勿关闭后端服务；刷新页面可查看最新状态。")
        elif rebuild_phase == "succeeded":
            chunk_count = rebuild_status.get("rebuild_chunk_count")
            suffix = f"共写入 {chunk_count} 个向量块。" if chunk_count is not None else ""
            st.success(f"✅ 最近一次向量索引重建已完成。{suffix}")
        elif rebuild_phase == "failed":
            error = rebuild_status.get("warmup_error")
            st.error(f"向量索引重建失败：{error or '未知错误'}")

        if st.button("🔄 全量重建向量索引", type="secondary", disabled=rebuilding):
            r = _client.post(f"{API}/admin/rebuild", headers=h)
            if r.status_code == 200:
                st.rerun()
            else:
                try:
                    st.error(r.json().get("detail", "重建失败"))
                except Exception:
                    st.error(f"重建失败: {r.text}")

        with st.expander("⚙️ 切片策略", expanded=False):
            st.caption("保存后会标记索引待重建。切分符按从左到右的优先级尝试；`\\n\\n` 表示段落，空字符串表示最终强制切分。")
            chunk_size = st.number_input(
                "切块大小（字符）", min_value=64, max_value=8192,
                value=int(chunking.get("chunk_size", 512)), step=32, key="chunk_size",
            )
            max_overlap = max(int(chunk_size) - 1, 0)
            default_overlap = min(int(chunking.get("chunk_overlap", 50)), max_overlap)
            chunk_overlap = st.number_input(
                "切块重叠（字符）", min_value=0, max_value=max_overlap,
                value=default_overlap, step=10, key="chunk_overlap",
            )
            separators_text = st.text_area(
                "切分符（JSON 字符串数组）",
                value=json.dumps(chunking.get("chunk_separators", ["\n\n", "\n", "。", "，", " ", ""]), ensure_ascii=False),
                help='例如：["\\n\\n", "\\n", "。", "，", " ", ""]', key="chunk_separators",
            )
            if st.button("保存切片策略", key="save_chunking"):
                try:
                    separators = json.loads(separators_text)
                    if not isinstance(separators, list) or not all(isinstance(item, str) for item in separators):
                        raise ValueError("切分符必须是 JSON 字符串数组")
                    response = _client.put(
                        f"{API}/admin/chunking", headers=h,
                        json={"chunk_size": int(chunk_size), "chunk_overlap": int(chunk_overlap), "chunk_separators": separators},
                    )
                    if response.status_code == 200:
                        st.success("切片策略已保存，请点击“全量重建向量索引”。")
                        st.rerun()
                    else:
                        st.error(response.json().get("detail", "保存失败"))
                except (ValueError, json.JSONDecodeError) as exc:
                    st.error(f"切片策略格式错误：{exc}")

        with st.expander("🔎 检索策略", expanded=False):
            st.caption("混合检索同时使用向量语义和关键词 BM25，适合教务、金额、时间、地点等事实问答；仅向量检索适合对照实验。保存后立即生效。")
            retrieval_mode = st.selectbox(
                "检索模式", ["hybrid", "vector"],
                index=0 if retrieval.get("mode", "hybrid") == "hybrid" else 1,
                format_func=lambda value: "混合检索（推荐）" if value == "hybrid" else "仅向量检索",
                key="retrieval_mode",
            )
            retrieval_top_k = st.number_input(
                "返回结果数量（Top-K）", min_value=1, max_value=20,
                value=int(retrieval.get("top_k", 6)), key="retrieval_top_k",
            )
            retrieval_threshold = st.number_input(
                "向量距离阈值", min_value=0.0, max_value=2.0,
                value=float(retrieval.get("score_threshold", 0.3)), step=0.05,
                help="仅影响向量候选；数值越小越严格。混合模式仍会保留关键词召回结果。",
                key="retrieval_threshold",
            )
            if st.button("保存检索策略", key="save_retrieval"):
                response = _client.put(
                    f"{API}/admin/retrieval", headers=h,
                    json={"mode": retrieval_mode, "top_k": int(retrieval_top_k), "score_threshold": float(retrieval_threshold)},
                )
                if response.status_code == 200:
                    st.success("检索策略已保存并立即生效。")
                    st.rerun()
                elif response.status_code == 404:
                    st.error("后端未加载“检索策略”接口。请重启后端服务后重试。")
                else:
                    try:
                        st.error(response.json().get("detail", "保存失败"))
                    except Exception:
                        st.error(f"保存失败: {response.text}")

        st.divider()
        st.subheader("➕ 添加文档")

        up_method = st.radio("添加方式", ["📁 上传文件", "🔗 从URL获取", "✏️ 手动编写"], horizontal=True)

        if up_method == "📁 上传文件":
            upload_mode = st.radio(
                "上传范围", ["文件（可多选）", "文件夹（递归导入）"], horizontal=True,
                help="文件模式可直接多选文件；文件夹模式会读取其中全部受支持文件。",
            )
            is_directory = upload_mode == "文件夹（递归导入）"
            up_files = st.file_uploader(
                "选择文件夹" if is_directory else "选择一个或多个文件",
                type=["txt", "md", "pdf", "docx", "json", "csv"],
                accept_multiple_files="directory" if is_directory else True,
                help="将递归导入其中所有受支持文件。" if is_directory else "按住 Ctrl 或 Shift 可选择多个文件。",
                key="directory_uploader" if is_directory else "file_uploader",
            )
            st.caption("上传后会自动切片并增量入库；单次最多 50 个文件、总计 100 MB、单文件最大 10 MB（均可通过环境变量调整）。")
            if up_files and st.button("上传", key="btn_upload"):
                files = [("files", (item.name, item.getvalue(), item.type or "application/octet-stream")) for item in up_files]
                r = _client.post(f"{API}/admin/documents/upload", headers={"Authorization": h["Authorization"]}, files=files)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("indexed"):
                        st.success(f"✅ 已上传并入库 {data.get('count', len(up_files))} 个文件，共 {data.get('chunk_count', 0)} 个向量块")
                    else:
                        st.warning("文件已保存，但当前索引待重建；请先执行全量重建后再检索。")
                    st.rerun()
                else:
                    try:
                        st.error(r.json().get("detail", "上传失败"))
                    except Exception:
                        st.error(f"上传失败: {r.text}")

        elif up_method == "🔗 从URL获取":
            url = st.text_input("URL 地址", placeholder="https://example.com/doc.txt")
            url_fn = st.text_input("文件名 (可选)", placeholder="留空则自动生成")
            if url and st.button("获取", key="btn_fetch"):
                body = {"url": url}
                if url_fn.strip():
                    body["filename"] = url_fn.strip()
                r = _client.post(f"{API}/admin/documents/fetch-url", headers=h, json=body)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("indexed"):
                        st.success(f"✅ 已保存并入库 {data['filename']}（{data.get('chunk_count', 0)} 个向量块）")
                    else:
                        st.warning(f"已保存 {data['filename']}，但当前索引待重建。")
                    st.rerun()
                else:
                    try:
                        st.error(r.json().get("detail", "获取失败"))
                    except Exception:
                        st.error(f"获取失败: {r.text}")

        elif up_method == "✏️ 手动编写":
            txt_name = st.text_input("文件名", placeholder="my_document.txt", key="txt_name")
            txt_content = st.text_area("内容", height=300, placeholder="在此输入文档内容...", key="txt_content")
            if txt_name and txt_content and st.button("保存", key="btn_create"):
                r = _client.post(f"{API}/admin/documents/create", headers=h, json={
                    "filename": txt_name, "content": txt_content,
                })
                if r.status_code == 200:
                    st.success(f"✅ {txt_name} 已创建")
                    st.rerun()
                else:
                    try:
                        st.error(r.json().get("detail", "创建失败"))
                    except Exception:
                        st.error(f"创建失败: {r.text}")

        st.divider()
        st.subheader("📋 已有文档")

        try:
            docs = _client.get(f"{API}/admin/documents", headers=h).json()
        except Exception:
            docs = []

        if not docs:
            st.info("知识库为空，请添加文档")
        else:
            for doc in docs:
                c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1, 1])
                with c1:
                    st.write(f"**{doc['filename']}**")
                with c2:
                    sz = doc["size_bytes"]
                    if sz < 1024:
                        st.caption(f"{sz} B")
                    elif sz < 1024 * 1024:
                        st.caption(f"{sz / 1024:.1f} KB")
                    else:
                        st.caption(f"{sz / 1024 / 1024:.1f} MB")
                with c3:
                    st.caption(doc["format"].upper())
                with c4:
                    pk = f"preview_{doc['filename']}"
                    if st.button("👁️", key=f"pv_{doc['filename']}", help="预览内容"):
                        st.session_state[pk] = not st.session_state.get(pk, False)
                with c5:
                    if st.button("🗑", key=f"dd_{doc['filename']}", help="删除"):
                        st.session_state[f"confirm_del_{doc['filename']}"] = True

                # 预览展开
                pk = f"preview_{doc['filename']}"
                if st.session_state.get(pk):
                    try:
                        prev = _client.get(f"{API}/admin/documents/{doc['filename']}", headers=h).json()
                        with st.expander(f"预览: {doc['filename']}", expanded=True):
                            st.text_area("内容", prev["content"], height=250, disabled=True, key=f"ta_{doc['filename']}")
                    except Exception as e:
                        st.error(f"加载预览失败: {e}")

                # 删除确认
                ck = f"confirm_del_{doc['filename']}"
                if st.session_state.get(ck):
                    st.warning(f"确认删除 **{doc['filename']}**？此操作不可撤销。")
                    cc1, cc2 = st.columns([1, 3])
                    with cc1:
                        if st.button("✅ 确认", key=f"cy_{doc['filename']}"):
                            r = _client.delete(f"{API}/admin/documents/{doc['filename']}", headers=h)
                            if r.status_code == 200:
                                st.success(f"已删除 {doc['filename']}")
                                st.session_state.pop(ck, None)
                                st.session_state.pop(pk, None)
                                st.rerun()
                            else:
                                st.error(f"删除失败: {r.text}")
                    with cc2:
                        if st.button("❌ 取消", key=f"cn_{doc['filename']}"):
                            st.session_state.pop(ck, None)
                            st.rerun()

    # ── Tab 4: 启动服务 ──
    with tab4:
        st.subheader("服务状态")

        try:
            s = _client.get(f"{API}/admin/status").json()
        except Exception:
            s = {"warmed_up": False, "warming_up": False}

        if s.get("warmed_up"):
            st.success("✅ 知识库已就绪")
            st.info(f"用户聊天系统已在端口 **8502** 运行\n\n访问地址: http://localhost:8502")
            if st.button("🔁 重新预热"):
                _client.post(f"{API}/admin/warmup", headers=h)
                st.rerun()
        elif s.get("warming_up"):
            st.info("⏳ 预热中，请稍后刷新...")
            if st.button("🔄 刷新"):
                st.rerun()
        else:
            st.warning("服务未启动")
            if st.button("🚀 启动服务", type="primary", use_container_width=True):
                r = _client.post(f"{API}/admin/warmup", headers=h)
                if r.status_code == 200:
                    st.success("预热已启动！")
                    st.rerun()
                else:
                    st.error(f"启动失败: {r.text}")

    # ── Tab 5: 审计日志 ──
    with tab5:
        st.subheader("📋 系统审计日志")
        st.caption("记录所有用户操作，包括登录、注册、文档管理、配置修改等。")

        # 筛选器
        c1, c2, c3 = st.columns(3)
        with c1:
            filter_action = st.selectbox("操作类型", [""] + _get_audit_actions(h),
                                         format_func=lambda a: ACTION_LABELS.get(a, a) if a else "全部",
                                         key="audit_action_filter")
        with c2:
            filter_resource = st.selectbox("资源类型", ["", "auth", "user", "document", "config", "system"],
                                           format_func=lambda r: {"": "全部", "auth": "认证", "user": "用户",
                                                                  "document": "文档", "config": "配置", "system": "系统"}.get(r, r),
                                           key="audit_resource_filter")
        with c3:
            page_size = st.selectbox("每页条数", [20, 50, 100], index=0, key="audit_page_size")

        # 分页
        if "audit_offset" not in st.session_state:
            st.session_state["audit_offset"] = 0

        # 查询
        params = {"limit": page_size, "offset": st.session_state["audit_offset"]}
        if filter_action:
            params["action"] = filter_action
        if filter_resource:
            params["resource"] = filter_resource

        try:
            data = _client.get(f"{API}/admin/audit-logs", headers=h, params=params).json()
            logs = data.get("logs", [])
            total = data.get("total", 0)
        except Exception:
            logs, total = [], 0

        # 统计摘要
        st.caption(f"共 **{total}** 条记录，当前显示第 {st.session_state['audit_offset'] + 1} - {st.session_state['audit_offset'] + len(logs)} 条")

        # 分页按钮
        pc1, pc2, pc3 = st.columns([1, 1, 4])
        with pc1:
            if st.button("⬅ 上一页", disabled=st.session_state["audit_offset"] == 0, key="audit_prev"):
                st.session_state["audit_offset"] = max(0, st.session_state["audit_offset"] - page_size)
                st.rerun()
        with pc2:
            if st.button("下一页 ➡", disabled=st.session_state["audit_offset"] + page_size >= total, key="audit_next"):
                st.session_state["audit_offset"] += page_size
                st.rerun()

        # 日志列表
        if not logs:
            st.info("暂无审计日志记录。")
        else:
            for entry in logs:
                icon = "✅" if entry.get("success") else "❌"
                action_label = ACTION_LABELS.get(entry["action"], entry["action"])
                ts = entry["created_at"][:19].replace("T", " ")
                expander_label = f"{icon} **{action_label}** — {entry['username']} — {ts}"
                with st.expander(expander_label):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption(f"操作: {action_label}")
                        st.caption(f"用户: {entry['username']} (ID: {entry['user_id'] or 'N/A'})")
                        st.caption(f"资源: {entry['resource']} / {entry['resource_id'] or 'N/A'}")
                    with c2:
                        st.caption(f"时间: {entry['created_at']}")
                        st.caption(f"IP: {entry['ip_address'] or 'N/A'}")
                        st.caption(f"状态: {'成功' if entry.get('success') else '失败'}")
                    if entry.get("detail"):
                        st.text(entry["detail"])

    st.divider()
    if st.button("🚪 退出登录"):
        st.session_state.clear()
        st.rerun()


if __name__ == "__main__":
    main()
