"""
Conversation Store —— 会话历史持久化

与 MemoryStore 共用同一 SQLite 数据库目录。
保存完整的对话记录（消息、工具调用、token 用量），支持跨会话检索。
"""

import sqlite3
import json
import time
import pathlib
from typing import Optional
from memory import MemoryStore


def _get_db_dir() -> pathlib.Path:
    """与 MemoryStore 共用同一目录"""
    mem = MemoryStore()
    return pathlib.Path(mem.db_path).parent


# ── 消息序列化 ──

def msg_to_row(role: str, content: str, tool_data: dict | None = None) -> dict:
    """将 Message 字段转为 DB 行"""
    return {"role": role, "content": content, "tool_data": tool_data}


def row_to_msg(row: dict) -> dict:
    """从 DB 行还原为消息字典"""
    return row


def msgs_to_history(msgs: list[dict]) -> str:
    """生成供 LLM 注入的上下文摘要"""
    relevant = [m for m in msgs if m["role"] in ("user", "assistant") and m["content"]]
    if not relevant:
        return ""
    context = relevant[-20:]
    lines = [f"[{m['role']}] {m['content'][:300]}" for m in context]
    return "## 历史对话\n" + "\n".join(lines)


class ConversationStore:
    """基于 SQLite 的会话历史存储"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(_get_db_dir() / "conversations.db")
        pathlib.Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '新会话',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL DEFAULT '',
                tool_data   TEXT,
                created_at  REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);
        """)

    # ── 会话管理 ──

    def create_session(self, session_id: str, name: str = "新会话") -> dict:
        now = time.time()
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, name, now, now),
        )
        self._conn.commit()
        return {"id": session_id, "name": name}

    def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT s.id, s.name, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as msg_count "
            "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0], "name": r[1],
                "created_at": r[2], "updated_at": r[3],
                "message_count": r[4],
            }
            for r in rows
        ]

    def rename_session(self, session_id: str, name: str) -> bool:
        cur = self._conn.execute(
            "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
            (name, time.time(), session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return True

    # ── 消息管理 ──

    def save_messages(self, session_id: str, messages: list[dict]):
        """批量保存消息"""
        if not messages:
            return
        now = time.time()
        rows = [
            (session_id, m["role"], m.get("content", ""),
             json.dumps(m.get("tool_data"), ensure_ascii=False) if m.get("tool_data") else None,
             now + i * 0.001)
            for i, m in enumerate(messages)
        ]
        self._conn.executemany(
            "INSERT INTO messages (session_id, role, content, tool_data, created_at) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        self._conn.commit()

    def get_messages(self, session_id: str, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, content, tool_data FROM messages "
            "WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [
            {
                "role": r[0],
                "content": r[1],
                "tool_data": json.loads(r[2]) if r[2] else None,
            }
            for r in rows
        ]

    def clear_session_messages(self, session_id: str):
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.commit()

    def replace_session_messages(self, session_id: str, messages: list[dict]):
        """原子替换：在单个事务中删除旧消息并写入新消息。"""
        if not messages:
            return
        now = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        rows = [
            (session_id, m["role"], m.get("content", ""),
             json.dumps(m.get("tool_data"), ensure_ascii=False) if m.get("tool_data") else None,
             now + i * 0.001)
            for i, m in enumerate(messages)
        ]
        self._conn.executemany(
            "INSERT INTO messages (session_id, role, content, tool_data, created_at) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()
