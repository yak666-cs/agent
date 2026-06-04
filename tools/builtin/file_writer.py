from tools.base import BaseTool, ToolMeta, Permission
from tools.path_util import resolve_path


class WriteFileTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="write_file",
            description="将内容写入指定文件。文件不存在则创建，存在则覆盖。",
            permission=Permission.READ_WRITE,
            requires_confirmation=True,
            timeout_seconds=15.0,
            tags=["file", "write"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str) -> str:
        full_path = resolve_path(path)
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"写入成功: {full_path} ({len(content)} 字符)"
        except PermissionError:
            return f"(错误) 没有权限写入: {full_path}"
        except Exception as e:
            return f"(错误) {e}"
