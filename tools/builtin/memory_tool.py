"""
Memory Tool —— 长期记忆读写

LLM 可通过此工具主动记忆/回忆信息，实现跨会话的长期记忆。
"""

from tools.base import BaseTool, ToolMeta, Permission
from memory import MemoryStore

_store = None


def _get_store():
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


class MemoryTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="memory",
            description="长期记忆：保存(save)重要信息、回忆(recall)历史记忆、搜索(search)相关记忆、列出(list)所有记忆、删除(forget)记忆。跨会话持久化，存在 F 盘。",
            permission=Permission.READ_WRITE,
            requires_confirmation=False,
            timeout_seconds=5.0,
            tags=["memory", "persist"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "recall", "search", "list", "forget"],
                    "description": "save=保存, recall=按 key 获取, search=模糊搜索, list=全部列出, forget=删除",
                },
                "key": {
                    "type": "string",
                    "description": "记忆的键名，如 'user_name'、'project_path'。save/recall/forget 时必填",
                },
                "content": {
                    "type": "string",
                    "description": "记忆内容。save 时必填",
                },
                "type": {
                    "type": "string",
                    "description": "记忆类型：fact（事实）、pref（偏好）、note（笔记）、project（项目信息）",
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词。search 时必填",
                },
                "tags": {
                    "type": "string",
                    "description": "标签，逗号分隔，如 'python,project'",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, key: str = "", content: str = "",
                      type: str = "fact", query: str = "", tags: str = "") -> str:
        store = _get_store()

        if action == "save":
            if not key:
                return "(错误) save 需要提供 key"
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            store.save(key, content, type, tag_list)
            return f"(已保存) {key} = {content}"

        elif action == "recall":
            if not key:
                return "(错误) recall 需要提供 key"
            mem = store.get(key)
            if mem:
                return f"[{mem['type']}] {mem['key']}: {mem['content']}"
            return f"(未找到) 没有 key 为 '{key}' 的记忆"

        elif action == "search":
            if not query:
                return "(错误) search 需要提供 query"
            results = store.search(query, type=type if type != "fact" else None)
            if not results:
                return "(未找到) 没有匹配的记忆"
            lines = [f"- [{m['type']}] {m['key']}: {m['content']}" for m in results]
            return "相关记忆：\n" + "\n".join(lines)

        elif action == "list":
            results = store.list_all(type=type if type != "fact" else None, limit=30)
            if not results:
                return "(空) 暂无记忆"
            lines = [f"- [{m['type']}] {m['key']}: {m['content'][:80]}" for m in results]
            return f"共 {len(results)} 条记忆：\n" + "\n".join(lines)

        elif action == "forget":
            if not key:
                return "(错误) forget 需要提供 key"
            ok = store.delete(key)
            return f"(已删除) 记忆 '{key}'" if ok else f"(未找到) 没有 key 为 '{key}' 的记忆"

        return f"(错误) 未知 action: {action}"
