"""LLM 聊天模型工厂 — 基于注册表，添加新模型只需 register_provider()。"""

import httpx
from langchain_core.language_models import BaseChatModel
from ..config import Config

PROVIDERS: dict[str, callable] = {}

# 每个 provider 的默认 base_url
DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "ollama": "http://localhost:11434",
}


def register_provider(name: str, factory: callable, default_base_url: str = ""):
    """注册一个模型提供商。factory 是无参 callable，返回 BaseChatModel。"""
    PROVIDERS[name] = factory
    if default_base_url:
        DEFAULT_BASE_URLS[name] = default_base_url


def create_chat_model() -> BaseChatModel:
    """根据当前配置创建聊天模型实例。"""
    provider = Config.LLM_PROVIDER
    factory = PROVIDERS.get(provider)
    if factory is None:
        raise ValueError(f"未知的模型提供商: {provider}，可用: {list(PROVIDERS)}")
    return factory()


# ══════════════════════════════════════════════════
#  内置提供商
# ══════════════════════════════════════════════════

def _make_deepseek():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=Config.DEEPSEEK_MODEL,
        api_key=Config.DEEPSEEK_API_KEY,
        base_url=Config.DEEPSEEK_BASE_URL,
        temperature=0.7,
        streaming=True,
    )


def _make_ollama():
    return _OllamaStreamWrapper(
        model=Config.OLLAMA_MODEL,
        base_url=Config.OLLAMA_BASE_URL,
        temperature=0.7,
    )


register_provider("deepseek", _make_deepseek)
register_provider("ollama", _make_ollama)


# ══════════════════════════════════════════════════
#  模型列表拉取
# ══════════════════════════════════════════════════

# 每种 provider 模型列表 API 的适配器
_MODEL_FETCHERS: dict[str, callable] = {}


def _register_fetcher(name: str, fetcher: callable):
    _MODEL_FETCHERS[name] = fetcher


def fetch_models_list(provider: str, api_key: str = "", base_url: str = "") -> list[dict]:
    """拉取指定 provider 的模型列表。返回 [{"id": "model-name"}, ...]。

    对 Ollama 本地部署，不需要 api_key。
    """
    fetcher = _MODEL_FETCHERS.get(provider)
    if fetcher is None:
        raise ValueError(f"不支持拉取模型列表的提供商: {provider}")
    return fetcher(api_key, base_url)


def _fetch_openai_compatible(api_key: str, base_url: str):
    """OpenAI 兼容的 GET /models 接口。"""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=15) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
    models = []
    for item in data.get("data", []):
        mid = item.get("id", "")
        if mid:
            models.append({"id": mid})
    return sorted(models, key=lambda m: m["id"])


def _fetch_ollama_models(_api_key: str, base_url: str):
    """Ollama 本地 GET /api/tags 接口。"""
    url = base_url.rstrip("/") + "/api/tags"
    with httpx.Client(timeout=10) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    models = []
    for item in data.get("models", []):
        mid = item.get("name", "")
        if mid:
            models.append({"id": mid})
    return sorted(models, key=lambda m: m["id"])


_register_fetcher("deepseek", _fetch_openai_compatible)
_register_fetcher("ollama", _fetch_ollama_models)


# ══════════════════════════════════════════════════
#  Ollama HTTP 流式客户端
# ══════════════════════════════════════════════════

class _OllamaStreamWrapper:
    """自定义 Ollama 流式客户端。

    qwen3.5 等 thinking 模型将内容放在 message.thinking 字段而非
    message.content，langchain_ollama 未处理该字段，故直接用 HTTP API。
    """

    def __init__(self, model: str, base_url: str, temperature: float):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

    def stream(self, messages: list):
        from langchain_core.messages import AIMessageChunk
        import httpx, json

        ollama_msgs = []
        for m in messages:
            if hasattr(m, "type"):
                if m.type == "system":
                    ollama_msgs.append({"role": "system", "content": m.content})
                elif m.type == "human":
                    ollama_msgs.append({"role": "user", "content": m.content})
                elif m.type == "ai":
                    ollama_msgs.append({"role": "assistant", "content": m.content})

        body = {
            "model": self.model,
            "messages": ollama_msgs,
            "stream": True,
            "options": {"temperature": self.temperature},
        }

        with httpx.Client(timeout=120) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                for line in r.iter_lines():
                    if line:
                        d = json.loads(line)
                        msg = d.get("message", {})
                        token = msg.get("content", "") or msg.get("thinking", "")
                        yield AIMessageChunk(content=token)
                        if d.get("done"):
                            break
