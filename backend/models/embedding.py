"""嵌入模型工厂 — 优先使用本地缓存。"""

import os
import httpx
from langchain_core.embeddings import Embeddings
from ..config import Config


def create_embedding_model() -> Embeddings:
    provider = Config.EMBEDDING_PROVIDER.lower()
    settings = Config.EMBEDDING_SETTINGS.get(provider, {})
    if provider == "huggingface":
        os.environ.setdefault("HF_ENDPOINT", getattr(Config, "HF_ENDPOINT", "https://hf-mirror.com"))
        from langchain_huggingface import HuggingFaceEmbeddings

        model_name = settings.get("model", "BAAI/bge-large-zh-v1.5")
        model_kwargs = {"device": "cpu"}
        encode_kwargs = {"normalize_embeddings": True, "batch_size": 64}

        local_dir = os.path.expanduser(f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots")

        if os.path.isdir(local_dir):
            snapshots = sorted(os.listdir(local_dir), reverse=True)
            for snap in snapshots:
                snap_path = os.path.join(local_dir, snap)
                conf = os.path.join(snap_path, "config.json")
                if os.path.isfile(conf):
                    return HuggingFaceEmbeddings(
                        model_name=snap_path,
                        model_kwargs=model_kwargs,
                        encode_kwargs=encode_kwargs,
                    )

        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
        )

    elif provider == "openai_compatible":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=settings["model"], api_key=settings["api_key"], base_url=settings["base_url"],
        )
    elif provider == "ollama":
        return OllamaEmbeddings(settings["model"], settings["base_url"])
    else:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")


class OllamaEmbeddings(Embeddings):
    """Ollama 原生 /api/embed 接口适配器。

    逐条生成向量，规避部分 llama-server 在批量输出时触发的 n_outputs_max 断言。
    """

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=Config.EMBEDDING_TIMEOUT_SECONDS) as client:
            return [self._embed_one(client, text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        with httpx.Client(timeout=Config.EMBEDDING_TIMEOUT_SECONDS) as client:
            return self._embed_one(client, text)

    def _embed_one(self, client: httpx.Client, text: str) -> list[float]:
        response = client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": text, "truncate": True},
        )
        if response.is_error:
            detail = response.text[:500]
            raise RuntimeError(
                f"Ollama Embedding 请求失败（HTTP {response.status_code}）: {detail}. "
                "请确认使用专用嵌入模型，并升级或重启 Ollama 服务。"
            )
        embeddings = response.json().get("embeddings", [])
        if not embeddings or not isinstance(embeddings[0], list):
            raise RuntimeError("Ollama Embedding 响应格式无效，未返回向量数据")
        return embeddings[0]
