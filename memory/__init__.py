"""
Memory Store —— 长期记忆系统

基于 SQLite，跨平台兼容（Windows / Android / Linux）。
数据库路径通过 KAI_MEMORY_PATH 环境变量配置，默认 F:\\KAI_AGENT\\memory\\kai_memory.db。
"""

import sqlite3
import json
import time
import os
import pathlib


def get_default_db_path() -> str:
    """跨平台默认路径：环境变量 > F 盘 > 项目本地"""
    env = os.environ.get("KAI_MEMORY_PATH")
    if env:
        return str(pathlib.Path(env) / "kai_memory.db")

    candidates = [
        pathlib.Path("F:/KAI_AGENT/memory"),
        pathlib.Path(__file__).resolve().parent.parent / "data" / "memory",
    ]
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".write_test"
            test_file.touch()
            test_file.unlink()
            return str(p / "kai_memory.db")
        except (OSError, PermissionError):
            continue

    # 兜底：项目本地
    fallback = pathlib.Path(__file__).resolve().parent.parent / "data" / "memory"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback / "kai_memory.db")


class MemoryStore:
    """SQLite 持久化记忆存储"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_default_db_path()
        pathlib.Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT    NOT NULL,
                type        TEXT    NOT NULL DEFAULT 'fact',
                content     TEXT    NOT NULL,
                tags        TEXT    DEFAULT '[]',
                created_at  REAL    NOT NULL,
                updated_at  REAL    NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
        self._conn.commit()

    def save(self, key: str, content: str, type: str = "fact", tags: list = None) -> dict:
        """保存或更新记忆。key 相同时覆盖内容。"""
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        existing = self._conn.execute(
            "SELECT id FROM memories WHERE key = ?", (key,)
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE memories SET content = ?, type = ?, tags = ?, updated_at = ? WHERE key = ?",
                (content, type, tags_json, now, key),
            )
        else:
            self._conn.execute(
                "INSERT INTO memories (key, type, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key, type, content, tags_json, now, now),
            )
        self._conn.commit()
        return {"key": key, "type": type, "content": content, "tags": tags or []}

    def get(self, key: str):
        """根据 key 获取单条记忆"""
        row = self._conn.execute(
            "SELECT key, type, content, tags, created_at, updated_at FROM memories WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return {
            "key": row[0],
            "type": row[1],
            "content": row[2],
            "tags": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        }

    def search(self, query: str, type: str = None, limit: int = 10):
        """模糊搜索记忆（匹配 key 和 content）"""
        sql = "SELECT key, type, content, tags, created_at, updated_at FROM memories WHERE (key LIKE ? OR content LIKE ?)"
        params = [f"%{query}%", f"%{query}%"]
        if type:
            sql += " AND type = ?"
            params.append(type)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "key": r[0],
                "type": r[1],
                "content": r[2],
                "tags": json.loads(r[3]),
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def delete(self, key: str) -> bool:
        """删除指定 key 的记忆"""
        cur = self._conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_all(self, type: str = None, limit: int = 50):
        """列出记忆，按更新时间倒序"""
        if type:
            rows = self._conn.execute(
                "SELECT key, type, content, tags, created_at, updated_at FROM memories WHERE type = ? ORDER BY updated_at DESC LIMIT ?",
                (type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT key, type, content, tags, created_at, updated_at FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "key": r[0],
                "type": r[1],
                "content": r[2],
                "tags": json.loads(r[3]),
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def get_relevant_context(self, user_message: str, max_items: int = 5) -> str:
        """从记忆中检索与用户消息相关的内容，返回格式化文本供注入上下文"""
        memories = self.search(user_message, limit=max_items)
        if not memories:
            return ""
        lines = [f"- {m['key']}: {m['content']}" for m in memories]
        return "## 长期记忆\n" + "\n".join(lines)

    def close(self):
        self._conn.close()
