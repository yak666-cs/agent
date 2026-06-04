"""文件删除 Tool —— 只能删文件，不能删目录"""

import os
import pathlib
from tools.base import BaseTool, ToolMeta, Permission


class FileDeleterTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="file_deleter",
            description="删除指定的文件。只能删文件，不能删目录。确认由系统自动处理。",
            permission=Permission.DESTRUCTIVE,
            requires_confirmation=True,
            timeout_seconds=10.0,
            tags=["file", "delete"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要删除的文件路径，支持绝对路径和相对路径"
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str) -> str:
        full_path = pathlib.Path(path)
        if not full_path.is_absolute():
            # 尝试相对于项目目录
            project = pathlib.Path(__file__).resolve().parent.parent.parent
            candidate = project / path
            if candidate.exists():
                full_path = candidate

        if not full_path.exists():
            return f"(错误) 文件不存在: {full_path}"

        if full_path.is_dir():
            return f"(错误) '{full_path}' 是目录，拒绝删除"

        try:
            os.remove(str(full_path))
            return f"删除成功: {full_path}"
        except PermissionError:
            return f"(错误) 没有权限删除: {full_path}"
        except Exception as e:
            return f"(错误) {e}"
