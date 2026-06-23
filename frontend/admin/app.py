"""管理员控制台 — 独立 Streamlit 应用（端口 8501）。

启动: streamlit run frontend/admin/app.py --server.port 8501

功能: 管理员登录 → 模型配置 → 用户管理 → 知识库管理 → 启动服务
启动服务后，用户在 8502 端口访问聊天系统。
"""

import sys, os, logging, traceback
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("admin")

import streamlit as st
import httpx

# API 地址：本地用 127.0.0.1:8000，公网隧道用环境变量 STREAMLIT_API_URL
API = os.environ.get("STREAMLIT_API_URL", "http://127.0.0.1:8000/api")
_client = httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=300)

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


def _get_audit_actions(headers: dict) -> list[str]:
    """从后端获取所有已出现的操作类型。"""
    try:
        return _client.get(f"{API}/admin/audit-logs/actions", headers=headers).json().get("actions", [])
    except Exception:
        return []

# ── State ──
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False
if "token" not in st.session_state:
    st.session_state["token"] = ""


def main():
    try:
        _route()
    except Exception:
        st.error(f"页面异常\n```\n{traceback.format_exc()[-1000:]}\n```")


def _route():
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
                st.rerun()
            except Exception as e:
                st.error(f"连接后端失败: {e}")


# ═══ 设置页 ═══
def _render_setup():
    token = st.session_state["token"]
    h = {"Authorization": f"Bearer {token}"}

    st.title("⚙️ 管理员控制台")
    st.caption("配置模型、管理用户、管理知识库、启动服务")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔧 模型配置", "👥 用户管理", "📚 知识库管理", "🚀 启动服务", "📋 审计日志"])

    # ── Tab 1: 模型配置 ──
    with tab1:
        # 当前配置
        try:
            r = _client.get(f"{API}/admin/config", headers=h)
            cfg = r.json()
        except Exception:
            cfg = {"provider": "deepseek", "settings": {}, "is_ready": False, "all_settings": {}}

        all_settings = cfg.get("all_settings", {})
        current_provider = cfg.get("provider", "deepseek")

        # 提供商元数据：定义每个 provider 的字段
        PROVIDER_META = {
            "deepseek": {
                "label": "DeepSeek",
                "default_base_url": "https://api.deepseek.com",
                "fields": [
                    {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "sk-..."},
                    {"key": "base_url", "label": "API 地址", "type": "text", "placeholder": "https://api.deepseek.com"},
                ],
            },
            "ollama": {
                "label": "Ollama (本地)",
                "default_base_url": "http://localhost:11434",
                "fields": [
                    {"key": "base_url", "label": "服务地址", "type": "text", "placeholder": "http://localhost:11434"},
                ],
            },
        }

        prov_names = list(PROVIDER_META.keys())
        current_idx = prov_names.index(current_provider) if current_provider in prov_names else 0
        prov = st.selectbox("模型提供商", prov_names, index=current_idx,
                            format_func=lambda p: PROVIDER_META[p]["label"])

        # 加载当前选中 provider 的已保存设置
        saved = all_settings.get(prov, {})
        meta = PROVIDER_META[prov]

        # ── 供应商特有字段 ──
        field_values = {}
        for field in meta["fields"]:
            key = field["key"]
            default = saved.get(key, field.get("default", ""))
            if field["type"] == "password":
                field_values[key] = st.text_input(field["label"], type="password",
                                                  value=default, placeholder=field["placeholder"])
            else:
                field_values[key] = st.text_input(field["label"], value=default,
                                                  placeholder=field["placeholder"])

        # ── 模型选择区域 ──
        api_key = field_values.get("api_key", "")
        base_url = field_values.get("base_url", "") or meta.get("default_base_url", "")

        # 初始化当前选中的模型到 session state
        model_key = f"selected_model_{prov}"
        if model_key not in st.session_state:
            st.session_state[model_key] = saved.get("model", "")

        c1, c2 = st.columns([3, 1])
        with c1:
            current_model = st.session_state[model_key]
            model_name = st.text_input(
                "模型名称",
                value=current_model,
                placeholder="如: deepseek-chat 或 qwen2.5:7b",
                key=f"model_input_{prov}",
            )
            # 显示已拉取的模型列表供参考
            model_list = st.session_state.get(f"model_list_{prov}", [])
            if model_list:
                model_ids = [m["id"] for m in model_list]
                st.caption(f"已拉取 {len(model_list)} 个模型: {' | '.join(model_ids[:8])}{'...' if len(model_ids) > 8 else ''}")
            # 更新选中的模型
            if model_name:
                st.session_state[model_key] = model_name

        with c2:
            st.write("")  # 对齐
            if st.button("🔍 拉取模型列表", key=f"fetch_{prov}"):
                if prov == "ollama" or (prov != "ollama" and api_key):
                    with st.spinner("正在拉取..."):
                        try:
                            body = {"provider": prov, "api_key": api_key, "base_url": base_url}
                            r = _client.post(f"{API}/admin/models", headers=h, json=body)
                            if r.status_code == 200:
                                data = r.json()
                                models = data.get("models", [])
                                st.session_state[f"model_list_{prov}"] = models
                                if models and st.session_state[model_key] not in [m["id"] for m in models]:
                                    st.session_state[model_key] = models[0]["id"]
                                st.success(f"找到 {len(models)} 个模型")
                                st.rerun()
                            else:
                                try:
                                    st.error(r.json().get("detail", "拉取失败"))
                                except Exception:
                                    st.error(f"拉取失败: {r.text}")
                        except Exception as e:
                            st.error(f"请求失败: {e}")
                else:
                    st.error("请先填写 API Key")

        st.caption(f"已保存的 {meta['label']} 模型: **{saved.get('model', '未设置')}**")

        # ── 保存 ──
        if st.button("💾 保存配置", type="primary"):
            settings = {k: v for k, v in field_values.items() if v}
            settings["model"] = st.session_state[model_key]
            if prov == "deepseek" and not settings.get("api_key"):
                st.error("DeepSeek 需要填写 API Key")
            elif not settings.get("model"):
                st.error("请选择或输入模型名称")
            else:
                try:
                    r = _client.put(f"{API}/admin/config", headers=h, json={
                        "provider": prov, "settings": settings,
                    })
                    if r.status_code == 200:
                        st.success(f"已切换到 {meta['label']} — 模型: {settings['model']}")
                        st.rerun()
                    else:
                        st.error(f"保存失败: {r.text}")
                except Exception as e:
                    st.error(str(e))

        st.caption(f"当前激活: **{PROVIDER_META.get(current_provider, {}).get('label', current_provider)}**"
                   f" — 模型: **{cfg.get('settings', {}).get('model', '?')}**"
                   f" | 状态: {'✅ 已配置' if cfg.get('is_ready') else '❌ 未配置'}")
        st.caption("切换提供商 → 填配置 → 拉取模型列表选择模型 → 保存配置即可生效。")

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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("文档数量", stats.get("doc_count", 0))
        c2.metric("向量块数", stats.get("chunk_count", 0))
        lt = stats.get("last_build_time")
        c3.metric("最后构建", lt[:19] if lt else "从未")
        if stats.get("stale"):
            c4.warning("⚠️ 需要重建索引")
        else:
            c4.success("✅ 索引已同步")

        if stats.get("stale") or stats.get("chunk_count", 0) == 0:
            if st.button("🔄 重建向量索引", type="primary"):
                r = _client.post(f"{API}/admin/rebuild", headers=h)
                if r.status_code == 200:
                    st.success("重建已启动，请稍后刷新查看")
                else:
                    try:
                        st.error(r.json().get("detail", "重建失败"))
                    except Exception:
                        st.error(f"重建失败: {r.text}")

        st.divider()
        st.subheader("➕ 添加文档")

        up_method = st.radio("添加方式", ["📁 上传文件", "🔗 从URL获取", "✏️ 手动编写"], horizontal=True)

        if up_method == "📁 上传文件":
            up_file = st.file_uploader("选择文件", type=["txt", "md", "pdf", "docx", "json", "csv"])
            if up_file and st.button("上传", key="btn_upload"):
                files = {"file": (up_file.name, up_file.getvalue(), up_file.type or "application/octet-stream")}
                r = _client.post(f"{API}/admin/documents/upload", headers={"Authorization": h["Authorization"]}, files=files)
                if r.status_code == 200:
                    st.success(f"✅ {up_file.name} 上传成功")
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
                    st.success(f"✅ 已保存为 {data['filename']}")
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
