from tools.base import BaseTool, ToolMeta, Permission
from tools.path_util import resolve_path


class ReadFileTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="read_file",
            description="读取指定文件的内容。支持按行号范围读取。路径支持相对路径和绝对路径。",
            permission=Permission.READ_ONLY,
            requires_confirmation=False,
            timeout_seconds=10.0,
            cache_ttl=10.0,
            tags=["file", "read"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，支持相对路径（如 skills/builtin/bash.py）和绝对路径"
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（从 1 开始）"
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（包含）"
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, start_line: int = 1, end_line: int = None) -> str:
        full_path = resolve_path(path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total = len(lines)
            start = max(1, start_line) - 1
            end = min(total, end_line) if end_line else total
            selected = lines[start:end]

            header = f"(文件: {path}, 共 {total} 行, 显示 {start+1}-{end})\n"
            return header + "".join(selected)

        except FileNotFoundError:
            return f"(错误) 文件不存在: {path}"
        except PermissionError:
            return f"(错误) 没有权限读取: {full_path}"
        except IsADirectoryError:
            return f"(错误) 路径是目录而非文件: {path}"
        except Exception as e:
            return f"(错误) {e}"
