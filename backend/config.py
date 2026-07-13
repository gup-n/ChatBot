"""配置管理 — 模型配置与运行策略统一从 .env 读取。"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Config:
    """集中管理所有配置项，带默认值。"""

    @classmethod
    def _load(cls) -> None:
        if ENV_FILE.exists():
            load_dotenv(ENV_FILE, override=True)

        # ── 模型设置 ──
        # LLM_SETTINGS / EMBEDDING_SETTINGS 是唯一模型来源；由管理端写入。
        cls.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai_compatible")

        raw = os.getenv("LLM_SETTINGS", "")
        try:
            cls.LLM_SETTINGS = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            cls.LLM_SETTINGS = {}
        if not isinstance(cls.LLM_SETTINGS, dict):
            cls.LLM_SETTINGS = {}

        # ── Embedding 提供商设置（与 LLM 独立保存） ──
        raw_embedding = os.getenv("EMBEDDING_SETTINGS", "")
        try:
            cls.EMBEDDING_SETTINGS = json.loads(raw_embedding) if raw_embedding else {}
        except json.JSONDecodeError:
            cls.EMBEDDING_SETTINGS = {}
        cls.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")
        if not isinstance(cls.EMBEDDING_SETTINGS, dict):
            cls.EMBEDDING_SETTINGS = {}

        # ── 其他配置 ──
        cls.HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
        cls.CHROMA_PERSIST_DIR = os.getenv(
            "CHROMA_PERSIST_DIR", str(PROJECT_ROOT / "data" / "chroma_db")
        )
        cls.SQLITE_DB_PATH = os.getenv(
            "SQLITE_DB_PATH", str(PROJECT_ROOT / "data" / "chatbot.db")
        )
        cls.KNOWLEDGE_DIR = os.getenv(
            "KNOWLEDGE_DIR", str(PROJECT_ROOT / "data" / "raw")
        )
        cls.RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "6"))
        cls.RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").lower()
        cls.RETRIEVAL_SCORE_THRESHOLD = float(
            os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.3")
        )
        cls.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))
        cls.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
        cls.CHUNK_SEPARATORS = cls._json_list(
            os.getenv("CHUNK_SEPARATORS", '["\\n\\n", "\\n", "。", "，", " ", ""]'),
            default=["\n\n", "\n", "。", "，", " ", ""],
        )
        cls.MAX_CHAT_MESSAGE_CHARS = int(os.getenv("MAX_CHAT_MESSAGE_CHARS", "4000"))
        cls.MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        cls.MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "50"))
        cls.MAX_UPLOAD_TOTAL_BYTES = int(os.getenv("MAX_UPLOAD_TOTAL_BYTES", str(100 * 1024 * 1024)))
        cls.MAX_FETCH_BYTES = int(os.getenv("MAX_FETCH_BYTES", str(5 * 1024 * 1024)))
        cls.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        cls.INITIAL_ADMIN_USERNAME = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
        cls.INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "")
        cls.CORS_ALLOW_ORIGINS = [
            item.strip() for item in os.getenv(
                "CORS_ALLOW_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501,http://localhost:8502,http://127.0.0.1:8502"
            ).split(",") if item.strip()
        ]
        cls.MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "50"))
        cls.LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        cls.LLM_STREAM_TIMEOUT_SECONDS = float(os.getenv("LLM_STREAM_TIMEOUT_SECONDS", "300"))
        cls.OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        cls.OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        cls.EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120"))
        cls.MODEL_LIST_TIMEOUT_SECONDS = float(os.getenv("MODEL_LIST_TIMEOUT_SECONDS", "15"))
        cls.URL_FETCH_TIMEOUT_SECONDS = float(os.getenv("URL_FETCH_TIMEOUT_SECONDS", "20"))
        cls.URL_FETCH_CONNECT_TIMEOUT_SECONDS = float(os.getenv("URL_FETCH_CONNECT_TIMEOUT_SECONDS", "5"))
        cls.HTTP_CLIENT_TIMEOUT_SECONDS = float(os.getenv("HTTP_CLIENT_TIMEOUT_SECONDS", "300"))
        cls.JWT_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_TOKEN_EXPIRE_HOURS", "24"))
        cls.AUDIT_LOG_MAX_PAGE_SIZE = int(os.getenv("AUDIT_LOG_MAX_PAGE_SIZE", "200"))
        cls.KB_OVERVIEW = os.getenv(
            "KB_OVERVIEW",
            "本知识库涵盖：宁波工程学院网安学院的招生简章、课程体系、师资介绍、学院概况、实验室信息、学科建设等相关内容。",
        )
        cls.BLOCK_MESSAGE = (
            "⚠️ 抱歉，您的问题包含不适宜的内容。请遵守网络安全规范，重新提问。"
        )
        cls.UNKNOWN_MESSAGE = (
            "📚 抱歉，我目前的知识库暂时无法回答您的问题。"
            "我的知识范围包括：网安学院的招生、课程、师资、实验室等相关信息。"
            "请尝试换一个相关问题。"
        )

    @classmethod
    def is_ready(cls) -> bool:
        settings = cls.LLM_SETTINGS.get(cls.LLM_PROVIDER, {})
        if cls.LLM_PROVIDER == "openai_compatible":
            return bool(settings.get("api_key") and settings.get("model"))
        if cls.LLM_PROVIDER == "ollama":
            return bool(settings.get("model") and settings.get("base_url"))
        return False

    @classmethod
    def is_security_ready(cls) -> bool:
        """认证密钥必须由部署环境提供，禁止回退到源码中的固定值。"""
        return (
            len(cls.JWT_SECRET_KEY) >= 32
            and not cls.JWT_SECRET_KEY.lower().startswith(("replace-", "change-me"))
        )

    @staticmethod
    def _json_list(raw: str, default: list[str]) -> list[str]:
        """解析 JSON 数组配置；无效值回退到安全默认值。"""
        try:
            value = json.loads(raw)
            if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
                return value
        except json.JSONDecodeError:
            pass
        return default

    @classmethod
    def reload(cls) -> None:
        cls._load()

    @classmethod
    def save_llm_settings(cls, provider: str, settings: dict) -> None:
        cls.LLM_SETTINGS[provider] = settings
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "LLM_PROVIDER", provider, quote_mode="never")
        set_key(
            str(ENV_FILE),
            "LLM_SETTINGS",
            json.dumps(cls.LLM_SETTINGS, ensure_ascii=False),
            quote_mode="never",
        )
        cls.reload()

    @classmethod
    def save_embedding_settings(cls, provider: str, settings: dict) -> None:
        cls.EMBEDDING_SETTINGS[provider] = settings
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "EMBEDDING_PROVIDER", provider, quote_mode="never")
        set_key(
            str(ENV_FILE), "EMBEDDING_SETTINGS",
            json.dumps(cls.EMBEDDING_SETTINGS, ensure_ascii=False), quote_mode="never",
        )
        cls.reload()

    @classmethod
    def save_chunking_settings(
        cls, chunk_size: int, chunk_overlap: int, chunk_separators: list[str]
    ) -> None:
        """保存切片策略；调用方应随后重建索引。"""
        cls.validate_chunking_settings(chunk_size, chunk_overlap, chunk_separators)
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "CHUNK_SIZE", str(chunk_size), quote_mode="never")
        set_key(str(ENV_FILE), "CHUNK_OVERLAP", str(chunk_overlap), quote_mode="never")
        set_key(
            str(ENV_FILE), "CHUNK_SEPARATORS",
            json.dumps(chunk_separators, ensure_ascii=False), quote_mode="never",
        )
        cls.reload()

    @classmethod
    def save_retrieval_settings(cls, mode: str, top_k: int, score_threshold: float) -> None:
        """保存检索策略；运行时立即读取，不影响已有向量数据。"""
        cls.validate_retrieval_settings(mode, top_k, score_threshold)
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "RETRIEVAL_MODE", mode, quote_mode="never")
        set_key(str(ENV_FILE), "RETRIEVAL_TOP_K", str(top_k), quote_mode="never")
        set_key(str(ENV_FILE), "RETRIEVAL_SCORE_THRESHOLD", str(score_threshold), quote_mode="never")
        cls.reload()

    @staticmethod
    def validate_chunking_settings(
        chunk_size: int, chunk_overlap: int, chunk_separators: list[str]
    ) -> None:
        if chunk_size < 64 or chunk_size > 8192:
            raise ValueError("切块大小必须在 64 到 8192 之间")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("切块重叠必须不小于 0 且小于切块大小")
        if not chunk_separators or any(not isinstance(item, str) for item in chunk_separators):
            raise ValueError("切分符必须是至少包含一个字符串的列表")

    @staticmethod
    def validate_retrieval_settings(mode: str, top_k: int, score_threshold: float) -> None:
        if mode not in {"hybrid", "vector"}:
            raise ValueError("检索模式仅支持 hybrid 或 vector")
        if not 1 <= top_k <= 20:
            raise ValueError("Top-K 必须在 1 到 20 之间")
        if not 0 <= score_threshold <= 2:
            raise ValueError("向量距离阈值必须在 0 到 2 之间")

    @classmethod
    def ensure_dirs(cls) -> None:
        for p in [cls.CHROMA_PERSIST_DIR, cls.KNOWLEDGE_DIR]:
            Path(p).mkdir(parents=True, exist_ok=True)
        Path(cls.SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


Config._load()
