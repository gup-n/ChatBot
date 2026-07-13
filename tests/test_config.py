"""环境变量到集中配置的映射校验。"""

import backend.config as config_module
from backend.config import Config


def test_runtime_settings_are_loaded_from_environment(monkeypatch):
    """运行策略应从环境变量读取，而不是散落在业务代码中。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("RETRIEVAL_TOP_K", "9")
    monkeypatch.setenv("CHUNK_SIZE", "768")
    monkeypatch.setenv("CHUNK_OVERLAP", "96")
    monkeypatch.setenv("CHUNK_SEPARATORS", '["\\n\\n", "\\n", "。", ""]')
    monkeypatch.setenv("MAX_UPLOAD_FILES", "12")
    monkeypatch.setenv("MAX_CHAT_MESSAGE_CHARS", "2048")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    monkeypatch.setenv("HTTP_CLIENT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://one.test,http://two.test")

    try:
        Config.reload()
        assert Config.RETRIEVAL_TOP_K == 9
        assert Config.CHUNK_SIZE == 768
        assert Config.CHUNK_OVERLAP == 96
        assert Config.CHUNK_SEPARATORS == ["\n\n", "\n", "。", ""]
        assert Config.MAX_UPLOAD_FILES == 12
        assert Config.MAX_CHAT_MESSAGE_CHARS == 2048
        assert Config.LLM_TEMPERATURE == 0.25
        assert Config.OLLAMA_NUM_CTX == 8192
        assert Config.HTTP_CLIENT_TIMEOUT_SECONDS == 45
        assert Config.CORS_ALLOW_ORIGINS == ["http://one.test", "http://two.test"]
    finally:
        monkeypatch.undo()
        Config.reload()


def test_chunking_settings_validation():
    Config.validate_chunking_settings(512, 50, ["\n\n", "\n", "。", ""])

    import pytest

    with pytest.raises(ValueError):
        Config.validate_chunking_settings(512, 512, [""])
    with pytest.raises(ValueError):
        Config.validate_chunking_settings(32, 0, [""])


def test_retrieval_settings_validation():
    Config.validate_retrieval_settings("hybrid", 6, 0.3)

    import pytest

    with pytest.raises(ValueError):
        Config.validate_retrieval_settings("unknown", 6, 0.3)
    with pytest.raises(ValueError):
        Config.validate_retrieval_settings("vector", 21, 0.3)
