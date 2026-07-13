from pathlib import Path

import pytest

from backend.config import Config
from backend.database import Database
from backend.security import validate_external_url


def test_security_configuration_requires_a_nontrivial_jwt_secret(monkeypatch):
    monkeypatch.setattr(Config, "JWT_SECRET_KEY", "short")
    assert Config.is_security_ready() is False
    monkeypatch.setattr(Config, "JWT_SECRET_KEY", "a" * 32)
    assert Config.is_security_ready() is True


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1:8000"])
def test_url_import_rejects_non_public_addresses(url):
    with pytest.raises(Exception):
        validate_external_url(url)


def test_document_path_stays_under_knowledge_directory(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    target = knowledge_dir / Path("../escape.txt").name
    assert target.resolve().is_relative_to(knowledge_dir.resolve())


def test_sessions_are_scoped_to_their_owner(tmp_path):
    db = Database(str(tmp_path / "chatbot.db"))
    alice = db.create_user("alice", "hash")
    bob = db.create_user("bob", "hash")
    alice_session = db.create_session(alice)

    assert [item["id"] for item in db.list_sessions(alice)] == [alice_session]
    assert db.list_sessions(bob) == []
