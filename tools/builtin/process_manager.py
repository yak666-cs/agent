"""process_manager Tool —— 查看/管理进程"""

import psutil
import signal
from tools.base import BaseTool, ToolMeta, Permission


class ProcessManagerTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="process_manager",
            description="查看/管理运行中的进程。支持 list（列出进程）、info（查看详情）、kill（终止进程）。",
            permission=Permission.SHELL,
            requires_confirmation=False,
            timeout_seconds=15.0,
            cache_ttl=2.0,
            tags=["system", "process"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型：list（列出进程）、info（查看进程详情）、kill（终止进程）",
                    "enum": ["list", "info", "kill"],
                },
                "pid": {
                    "type": "integer",
                    "description": "进程 PID（info 和 kill 时必填）",
                },
                "name": {
                    "type": "string",
                    "description": "按进程名过滤（仅 list 时可选），支持模糊匹配（如 'python' 会匹配所有含 python 的进程名）",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, pid: int = None, name: str = None) -> str:
        if action == "list":
            return self._list_processes(name)
        elif action == "info":
            if pid is None:
                return "(错误) info 操作需要提供 pid"
            return self._process_info(pid)
        elif action == "kill":
            if pid is None:
                return "(错误) kill 操作需要提供 pid"
            return self._kill_process(pid)
        return f"(错误) 未知操作: {action}"

    def _list_processes(self, name_filter: str = None) -> str:
        rows = []
        count = 0
        for proc in psutil.process_iter(["pid", "cpu_percent", "memory_percent", "status", "name"]):
            try:
                info = proc.info
                pname = info["name"] or ""
                if name_filter and name_filter.lower() not in pname.lower():
                    continue
                cpu = info["cpu_percent"] or 0.0
                mem = info["memory_percent"] or 0.0
                rows.append(f"{info['pid']:>7}  {cpu:>5.1f}  {mem:>5.1f}  {str(info['status']):>8}  {pname}")
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if count == 0:
            return "(无匹配进程)" if name_filter else "(无运行中的进程)"

        header = f"{'PID':>7}  {'CPU%':>5}  {'MEM%':>5}  {'状态':>8}  名称"
        return f"共 {count} 个进程\n{header}\n" + "\n".join(rows)

    def _process_info(self, pid: int) -> str:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                create_time = proc.create_time()
                from datetime import datetime
                lines = [
                    f"进程名：{proc.name()}",
                    f"PID：{pid}",
                    f"状态：{proc.status()}",
                    f"父 PID：{proc.ppid()}",
                    f"创建时间：{datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M:%S')}",
                    f"CPU 使用率：{proc.cpu_percent(interval=0.3)}%",
                    f"内存使用：{self._fmt(proc.memory_info().rss)} (RSS)",
                    f"内存百分比：{proc.memory_percent():.1f}%",
                    f"线程数：{proc.num_threads()}",
                    f"打开文件数：{len(proc.open_files())}",
                    f"连接数：{len(proc.connections())}",
                ]
                try:
                    cmd = proc.cmdline()
                    lines.append(f"命令行：{' '.join(cmd) if cmd else '(空)'}")
                except (psutil.AccessDenied, FileNotFoundError):
                    lines.append("命令行：(无权限)")
                return "\n".join(lines)
        except psutil.NoSuchProcess:
            return f"(错误) 进程 {pid} 不存在"
        except psutil.AccessDenied:
            return f"(错误) 无权限访问进程 {pid}"
        except Exception as e:
            return f"(错误) {e}"

    def _kill_process(self, pid: int) -> str:
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=3)
            if alive:
                proc.kill()
                return f"进程 {pid} ({name}) 已强制终止 (SIGKILL)"
            return f"进程 {pid} ({name}) 已终止 (SIGTERM)"
        except psutil.NoSuchProcess:
            return f"(错误) 进程 {pid} 不存在"
        except psutil.AccessDenied:
            return f"(错误) 无权限终止进程 {pid}"
        except Exception as e:
            return f"(错误) {e}"

    @staticmethod
    def _fmt(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}TB"
