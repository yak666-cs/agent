import asyncio
from tools.base import BaseTool, ToolMeta, Permission


class BashTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="bash",
            description="在电脑终端中执行命令并返回输出。适用于：查看进程(tasklist)、查看磁盘(wmic)、查看端口(netstat)、查看文件(dir/type)等系统操作。",
            permission=Permission.SHELL,
            requires_confirmation=True,
            timeout_seconds=60.0,
            tags=["system", "shell"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令。Windows 用户用 dir 而非 ls、type 而非 cat。"
                },
                "working_dir": {
                    "type": "string",
                    "description": "可选。命令执行的工作目录。"
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str = ".") -> str:
        dangerous = ["rm -rf /", "mkfs.", "dd if=", "> /dev/sda", "format ", "del /f /s"]
        for pattern in dangerous:
            if pattern in command.lower():
                return f"[拒绝执行] 命令包含危险模式: '{pattern}'"

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=55.0)
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
            output = output.strip() or f"(命令执行成功，无输出，退出码: {process.returncode})"
            return output
        except asyncio.TimeoutError:
            return "(命令执行超时，已终止)"
        except FileNotFoundError:
            return f"(错误) 命令未找到，请检查 '{command.split()[0] if command else ''}' 是否已安装"
        except Exception as e:
            return f"(错误) {e}"
