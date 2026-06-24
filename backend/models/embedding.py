"""嵌入模型工厂 — 优先使用本地缓存。"""

import os
from langchain_core.embeddings import Embeddings
from ..config import Config


def create_embedding_model() -> Embeddings:
    provider = Config.EMBEDDING_PROVIDER.lower()
    if provider == "huggingface":
        os.environ.setdefault("HF_ENDPOINT", getattr(Config, "HF_ENDPOINT", "https://hf-mirror.com"))
        from langchain_huggingface import HuggingFaceEmbeddings

        model_name = Config.HF_EMBEDDING_MODEL
        local_dir = os.path.expanduser(f"~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/snapshots")

        if os.path.isdir(local_dir):
            snapshots = sorted(os.listdir(local_dir), reverse=True)
            for snap in snapshots:
                snap_path = os.path.join(local_dir, snap)
                conf = os.path.join(snap_path, "config.json")
                if os.path.isfile(conf):
                    return HuggingFaceEmbeddings(
                        model_name=snap_path,
                        model_kwargs={"device": "cpu"},
                        encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
                    )

        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
        )

    elif provider == "deepseek":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model="deepseek-text-embedding",
            api_key=Config.DEEPSEEK_API_KEY,
            base_url=Config.DEEPSEEK_BASE_URL,
        )
    else:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")
