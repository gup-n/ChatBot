"""配置管理 — 从 .env 读取所有配置项。

LLM 提供商配置统一存储在 LLM_SETTINGS JSON 中，添加新模型无需修改此类。
"""

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

        # ── LLM 提供商设置 ──
        cls.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")

        raw = os.getenv("LLM_SETTINGS", "")
        try:
            cls.LLM_SETTINGS = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            cls.LLM_SETTINGS = {}

        # 兼容旧格式：从扁平 env var 迁移
        if not cls.LLM_SETTINGS:
            cls.LLM_SETTINGS = {
                "deepseek": {
                    "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
                    "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                },
                "ollama": {
                    "model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                    "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                },
            }

        # ── 便捷访问属性 ──
        cls.DEEPSEEK_API_KEY = cls._ps("deepseek", "api_key", "")
        cls.DEEPSEEK_MODEL = cls._ps("deepseek", "model", "deepseek-chat")
        cls.DEEPSEEK_BASE_URL = cls._ps("deepseek", "base_url", "https://api.deepseek.com")
        cls.OLLAMA_MODEL = cls._ps("ollama", "model", "qwen2.5:7b")
        cls.OLLAMA_BASE_URL = cls._ps("ollama", "base_url", "http://localhost:11434")

        # ── 其他配置 ──
        cls.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")
        cls.HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
        cls.HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
        cls.CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(PROJECT_ROOT / "data" / "chroma_db"))
        cls.SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", str(PROJECT_ROOT / "data" / "chatbot.db"))
        cls.KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", str(PROJECT_ROOT / "data" / "raw"))
        cls.RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "6"))
        cls.RETRIEVAL_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.3"))
        cls.MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "50"))
        cls.MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "5"))
        cls.KB_OVERVIEW = os.getenv(
            "KB_OVERVIEW",
            "本知识库涵盖：宁波工程学院网安学院的招生简章、课程体系、师资介绍、学院概况、实验室信息、学科建设等相关内容。",
        )
        cls.BLOCK_MESSAGE = "⚠️ 抱歉，您的问题包含不适宜的内容。请遵守网络安全规范，重新提问。"
        cls.UNKNOWN_MESSAGE = (
            "📚 抱歉，我目前的知识库暂时无法回答您的问题。"
            "我的知识范围包括：网安学院的招生、课程、师资、实验室等相关信息。"
            "请尝试换一个相关问题。"
        )

    @classmethod
    def _ps(cls, provider: str, key: str, default: str = "") -> str:
        """从 LLM_SETTINGS 中读取指定 provider 的配置项。"""
        return cls.LLM_SETTINGS.get(provider, {}).get(key, default)

    @classmethod
    def is_ready(cls) -> bool:
        if cls.LLM_PROVIDER == "deepseek":
            return bool(cls.DEEPSEEK_API_KEY)
        if cls.LLM_PROVIDER == "ollama":
            return True
        # 未知 provider：检查是否有 api_key 配置
        settings = cls.LLM_SETTINGS.get(cls.LLM_PROVIDER, {})
        return bool(settings.get("api_key")) or cls._ps(cls.LLM_PROVIDER, "model") != ""

    @classmethod
    def reload(cls) -> None:
        cls._load()

    @classmethod
    def save_settings(cls, provider: str, settings: dict) -> None:
        """保存指定 provider 的设置，然后切换到该 provider。

        settings 是任意 key-value dict，如 {"api_key": "sk-...", "model": "gpt-4"}。
        """
        cls.LLM_SETTINGS[provider] = settings
        ENV_FILE.touch(exist_ok=True)

        # 写 LLM_PROVIDER
        set_key(str(ENV_FILE), "LLM_PROVIDER", provider, quote_mode="never")

        # 写 LLM_SETTINGS JSON
        set_key(str(ENV_FILE), "LLM_SETTINGS", json.dumps(cls.LLM_SETTINGS, ensure_ascii=False), quote_mode="never")

        # 兼容：同时写扁平 key（旧代码读取用）
        if provider == "deepseek":
            if "api_key" in settings:
                set_key(str(ENV_FILE), "DEEPSEEK_API_KEY", settings["api_key"], quote_mode="never")
            if "model" in settings:
                set_key(str(ENV_FILE), "DEEPSEEK_MODEL", settings["model"], quote_mode="never")
            if "base_url" in settings:
                set_key(str(ENV_FILE), "DEEPSEEK_BASE_URL", settings["base_url"], quote_mode="never")
        elif provider == "ollama":
            if "model" in settings:
                set_key(str(ENV_FILE), "OLLAMA_MODEL", settings["model"], quote_mode="never")
            if "base_url" in settings:
                set_key(str(ENV_FILE), "OLLAMA_BASE_URL", settings["base_url"], quote_mode="never")

        cls.reload()

    @classmethod
    def ensure_dirs(cls) -> None:
        for p in [cls.CHROMA_PERSIST_DIR, cls.KNOWLEDGE_DIR]:
            Path(p).mkdir(parents=True, exist_ok=True)
        Path(cls.SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


Config._load()
