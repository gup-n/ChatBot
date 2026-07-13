**一、环境要求**

| **依赖项** | **版本要求**            |
| ---------- | ----------------------- |
| Python     | ≥ 3.12                  |
| 包管理器   | uv（推荐）或 pip        |
| 操作系统   | Windows / macOS / Linux |

 

**二、安装步骤**

**2.1** **安装依赖**

 进入项目目录
 cd ChatBot
 安装 uv（如未安装）
 pip install uv
 安装项目依赖
 uv sync

**2.2** **配置环境变量**

 复制配置模板
 cp .env.example .env
 编辑 .env，填入 DeepSeek API Key
 如使用 Ollama，将 LLM_PROVIDER 改为 ollama

**.env** **关键配置项：**

| **配置项** | **说明** | **示例值** |
| --- | --- | --- |
| `LLM_PROVIDER` / `LLM_SETTINGS` | 当前 LLM 的服务商与 JSON 设置 | `openai_compatible` |
| `EMBEDDING_PROVIDER` / `EMBEDDING_SETTINGS` | 当前嵌入模型的服务商与 JSON 设置 | `huggingface` |
| `JWT_SECRET_KEY` | 至少 32 位的随机 JWT 密钥 | 随机字符串 |
| `INITIAL_ADMIN_PASSWORD` | 首次启动时创建管理员的强密码 | 自定义强密码 |

LLM 与 Embedding 可在管理员控制台分别配置：LLM 支持 OpenAI 兼容接口和 Ollama；Embedding 支持 HuggingFace、本地 Ollama 与 OpenAI 兼容 Embedding 接口。修改 Embedding 后需要重建向量索引。详细字段和每个文件的职责见 [项目文件说明](docs/项目文件说明.md)。

使用 Ollama 作为 Embedding 时，请选择专用嵌入模型（推荐 `nomic-embed-text`），并先执行 `ollama pull nomic-embed-text`；不要把 `qwen`、`deepseek` 等聊天模型用于 `/api/embed`。

如果 Ollama 日志出现 `n_outputs_max` 或 `GGML_ASSERT`，请先重启并升级 Ollama。系统会逐条提交 Embedding 请求以避开部分 Ollama/llama-server 的批量输出问题；官方 `/api/embed` 接口支持单条文本作为 `input`。[Ollama Embed API](https://docs.ollama.com/api/embed)

文本切片策略由 `.env` 控制：`CHUNK_SIZE` 为片段长度、`CHUNK_OVERLAP` 为相邻片段重叠长度、`CHUNK_SEPARATORS` 为 JSON 分隔符数组。修改任一项后，请重建向量索引。检索默认使用 `RETRIEVAL_MODE=hybrid`，融合向量语义检索与 BM25 关键词检索；如需仅使用向量检索可设为 `vector`。

模型推理和服务参数也可在 `.env` 调优：`LLM_TEMPERATURE`、`OLLAMA_NUM_CTX`、`OLLAMA_KEEP_ALIVE`、`LLM_STREAM_TIMEOUT_SECONDS`、`EMBEDDING_TIMEOUT_SECONDS`、`URL_FETCH_TIMEOUT_SECONDS`、`JWT_TOKEN_EXPIRE_HOURS`。本地 `run.py` 的主机和端口由 `APP_HOST`、`API_PORT`、`ADMIN_PORT`、`USER_PORT` 控制；修改端口时，也应相应更新 `STREAMLIT_API_URL`。

**2.3** **准备知识库文档**

将学院相关文档放入 data/raw/ 目录，支持格式：.txt、.md、.pdf、.docx、.json、.csv。

**三、启动系统**

python run.py        一键启动全部服务
 python run.py --backend   仅启动后端 API

启动后访问：

| **服务**      | **地址**                   | **默认账号**      |
| ------------- | -------------------------- | ----------------- |
| 后端 API 文档 | http://localhost:8000/docs | —                 |
| 管理员控制台  | http://localhost:8501      | `.env` 中配置的初始管理员 |
| 用户聊天系统  | http://localhost:8502      | 自行注册          |

按 Ctrl+C 停止所有服务。

**四、使用指南**

**4.1** **管理员控制台（端口 8501）**

**登录**：使用 `.env` 中的 `INITIAL_ADMIN_USERNAME` 和 `INITIAL_ADMIN_PASSWORD` 登录。首次启动时才会创建该管理员；请使用强密码。

**模型配置**：选择提供商（DeepSeek 或 Ollama）→ 填写 API Key 和地址 → 点击"拉取模型列表"选择模型 → "保存配置"。

**用户管理**：查看用户列表，可添加新用户、删除普通用户、重置普通用户密码为 123456。

**知识库管理**：

- 上传文件：可选择多个文件或文件夹；系统会递归导入其中的 txt/md/pdf/docx/json/csv 文件。默认单次最多 50 个文件、总计 100 MB、单文件 10 MB，可在 `.env` 调整。
- 从 URL 获取：输入网页地址自动抓取
- 手动编写：直接输入文件名和内容
- 上传、URL 获取和手动编写会自动切片并增量入库，立即可检索；仅在修改 Embedding 模型、切片策略，或需要修复索引时点击“全量重建向量索引”。

**启动服务**：首次使用需点击"启动服务"，等待预热完成后用户端即可正常问答。

**审计日志**：查看所有用户的操作记录，支持按类型和分页筛选。

**4.2** **用户聊天系统（端口 8502****）**

**注册**：首次使用点击"注册新账号"，填写用户名（≥2 位）和密码（≥3 位）。

**登录**：输入注册的用户名和密码登录。

**开始对话**：

- 点击左侧"➕ 新建会话"
- 在底部输入框输入问题，如"网安学院有哪些专业？"
- 助手回答逐字流式显示
- 可在已有会话中继续追问

**管理会话**：左侧会话列表可切换会话，点击 🗑 删除不需要的会话。

**修改密码**：左侧边栏底部"🔒 修改密码"区域。

**五、常见问题**

**Q****：启动后提示"****未配置 API Key"****？** A：管理员登录控制台 → 模型配置 → 填写 DeepSeek API Key → 保存。

**Q****：用户端提问回答不准确？** A：检查 data/raw/ 中是否已放入相关文档，并在管理员端知识库管理 Tab 点击"重建向量索引"。

**Q****：想使用本地 Ollama** **模型？** A：确保 Ollama 已安装并运行 → .env 中设置 LLM_PROVIDER=ollama → 控制台切换为 Ollama 并配置模型名。

**Q****：端口被占用？** A：关闭占用进程，或修改 run.py 中的 --port 参数。

**六、RAG 评估**

项目提供 [54 题基线题集](evaluation/questions.json) 与离线评估脚本，分别统计检索召回率和回答关键事实覆盖率。题集每题包含标准答案、关键事实和期望来源；新增或修改知识库后应由业务人员复核这些标注。

```bash
# 不调用 LLM，只评估标准来源是否出现在 Top-K 检索结果中
uv run python scripts/evaluate_rag.py --retrieval-only

# 评估检索与当前 LLM 的回答，报告输出到 reports/evaluation/
uv run python scripts/evaluate_rag.py
```

报告包含 `report.json`（便于 CI/数据分析）和 `report.md`（便于人工复核）。建议把题集扩充到 50–100 题，并按专业介绍、教务、奖助学金、考试、校园服务等分类持续维护。

**七、Docker 部署**

如果你已经安装了 `Docker Desktop + WSL`，可以直接用 `docker compose` 部署。

**1. 准备配置**

1. 复制 `.env.example` 为 `.env`
2. 填好至少 32 字符的随机 `JWT_SECRET_KEY` 与初始管理员密码；模型可随后在管理员控制台配置
3. 把知识库文件放到 `data/raw/`
4. 若容器要访问宿主机 Ollama，将 LLM 或 Embedding 的 `base_url` 配置为 `http://host.docker.internal:11434`，不要使用容器内的 `127.0.0.1:11434`

**2. 启动**

```bash
docker compose up --build
```

后台运行使用：

```bash
docker compose up --build -d
docker compose logs -f backend
```

**3. 访问**

- 后端文档: http://localhost:8000/docs
- 管理员控制台: http://localhost:8501
- 用户聊天系统: http://localhost:8502

**4. 默认账号**

- 管理员: `.env` 的 `INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD`

**5. 数据持久化**

- `data/` 会映射到容器内，保留数据库和向量库
- `.env` 会被容器读取并写回，管理员在界面里保存配置后会直接落到本机 `.env`
- 后端健康检查通过后，管理员端和用户端才会启动；服务异常会按 `unless-stopped` 自动重启
