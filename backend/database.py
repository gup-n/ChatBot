"""SQLite 数据库 — 会话、消息、用户的持久化存储。"""

import sqlite3
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '新会话',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
            """)
            # 迁移：给已有的 sessions 加 user_id（新表已包含则跳过）
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER REFERENCES users(id)")
            except sqlite3.OperationalError:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    sources TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON sessions(user_id, updated_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    resource_id TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    ip_address TEXT DEFAULT '',
                    success INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_user
                ON audit_logs(user_id, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_action
                ON audit_logs(action, created_at)
            """)

    # ── 用户 CRUD ─────────────────────────────────

    def create_user(self, username: str, password_hash: str, is_admin: int = 0) -> int:
        now = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, is_admin, now),
            )
        return cursor.lastrowid

    def get_user(self, user_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def delete_user(self, user_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def update_password(self, user_id: int, password_hash: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    # ── 会话 CRUD ─────────────────────────────────

    def create_session(self, user_id: int, title: str = "新会话") -> str:
        sid = str(uuid.uuid4())
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, user_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, title, user_id, now, now),
            )
        return sid

    def list_sessions(self, user_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at "
                "FROM sessions WHERE is_active = 1 AND user_id = ? "
                "ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def rename_session(self, session_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                         (title[:30], _now(), session_id))

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET is_active = 0, updated_at = ? WHERE id = ?",
                         (_now(), session_id))

    # ── 消息 CRUD ─────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str,
                    sources: list[dict] | None = None) -> int:
        now = _now()
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (session_id, role, content, sources, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, sources_json, now),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return cursor.lastrowid

    def get_messages(self, session_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, session_id, role, content, sources, created_at "
                "FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, session_id, role, content, sources, created_at "
                "FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def export_session(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")
        session["messages"] = self.get_messages(session_id)
        return session

    # ── 审计日志 ─────────────────────────────────

    def add_audit_log(self, user_id: int | None, username: str, action: str,
                      resource: str, resource_id: str = "", detail: str = "",
                      ip_address: str = "", success: bool = True) -> int:
        now = _now()
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO audit_logs (user_id, username, action, resource, resource_id, detail, ip_address, success, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, action, resource, resource_id, detail, ip_address, 1 if success else 0, now),
            )
        return cursor.lastrowid

    def list_audit_logs(self, user_id: int | None = None, action: str = "",
                        resource: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
        with self._conn() as conn:
            query = "SELECT * FROM audit_logs WHERE 1=1"
            params: list = []
            if user_id is not None:
                query += " AND user_id = ?"
                params.append(user_id)
            if action:
                query += " AND action = ?"
                params.append(action)
            if resource:
                query += " AND resource = ?"
                params.append(resource)
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def count_audit_logs(self, user_id: int | None = None, action: str = "",
                         resource: str = "") -> int:
        with self._conn() as conn:
            query = "SELECT COUNT(*) as cnt FROM audit_logs WHERE 1=1"
            params: list = []
            if user_id is not None:
                query += " AND user_id = ?"
                params.append(user_id)
            if action:
                query += " AND action = ?"
                params.append(action)
            if resource:
                query += " AND resource = ?"
                params.append(resource)
            row = conn.execute(query, params).fetchone()
        return row["cnt"] if row else 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
