"""
Auth 模块 —— 用户注册 / 登录 / Token 认证

纯标准库实现：
- 密码哈希：hashlib.pbkdf2_hmac（SHA-256, 600K 迭代, 32B salt）
- Token：secrets.token_hex(32)
- 存储：SQLite（与 conversation_store 共用目录）
"""

import hashlib
import os
import secrets
import sqlite3
import time
import pathlib
from typing import Optional

from fastapi import Request


def _get_db_dir() -> pathlib.Path:
    from memory import MemoryStore
    mem = MemoryStore()
    return pathlib.Path(mem.db_path).parent


AUTH_DB_PATH = str(_get_db_dir() / "auth.db")


def hash_password(password: str) -> str:
    """生成密码哈希：salt(32B hex) + ':' + hash(hex)"""
    salt = os.urandom(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return salt.hex() + ":" + h.hex()


def verify_password(password: str, stored: str) -> bool:
    """验证密码与存储的哈希是否匹配"""
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
        return h.hex() == hash_hex
    except (ValueError, TypeError):
        return False


def generate_token() -> str:
    return secrets.token_hex(32)


class AuthStore:
    """用户认证存储"""

    def __init__(self, db_path: str = AUTH_DB_PATH):
        self.db_path = db_path
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                token       TEXT,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
        """)

    def register(self, username: str, password: str) -> dict:
        """注册新用户，成功时自动生成 token"""
        if len(password) < 4:
            return {"ok": False, "error": "密码至少 4 个字符"}
        password_hash = hash_password(password)
        token = generate_token()
        now = time.time()
        try:
            self._conn.execute(
                "INSERT INTO users (username, password_hash, token, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, token, now),
            )
            self._conn.commit()
            return {"ok": True, "token": token, "username": username}
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "用户名已存在"}

    def login(self, username: str, password: str) -> dict:
        """登录验证，成功时更新 token"""
        row = self._conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "用户名或密码错误"}
        user_id, password_hash = row
        if not verify_password(password, password_hash):
            return {"ok": False, "error": "用户名或密码错误"}
        token = generate_token()
        self._conn.execute(
            "UPDATE users SET token = ? WHERE id = ?", (token, user_id),
        )
        self._conn.commit()
        return {"ok": True, "token": token, "username": username}

    def get_user_by_token(self, token: str) -> Optional[dict]:
        """通过 token 查询用户"""
        if not token:
            return None
        row = self._conn.execute(
            "SELECT id, username, created_at FROM users WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "username": row[1], "created_at": row[2]}

    def logout(self, token: str):
        """清除用户的 token"""
        self._conn.execute(
            "UPDATE users SET token = NULL WHERE token = ?", (token,),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()


# 全局单例
_auth_store: Optional[AuthStore] = None


def get_auth_store() -> AuthStore:
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore()
    return _auth_store


async def get_current_user(request: Request) -> Optional[dict]:
    """FastAPI 依赖注入 —— 从 Authorization 头提取用户信息"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):].strip()
    if not token:
        return None
    return get_auth_store().get_user_by_token(token)
