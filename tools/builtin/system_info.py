"""system_info Tool —— 一键获取系统概况"""

import psutil
import platform
from datetime import datetime
from tools.base import BaseTool, ToolMeta, Permission


class SystemInfoTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="system_info",
            description="一键获取系统概况：OS、CPU、内存、磁盘、网络。info_type 可选 cpu/memory/disk/network/all，默认 all。",
            permission=Permission.READ_ONLY,
            timeout_seconds=15.0,
            cache_ttl=3.0,
            tags=["system", "info"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "info_type": {
                    "type": "string",
                    "description": "要查询的信息类型：cpu / memory / disk / network / all（默认）",
                    "enum": ["cpu", "memory", "disk", "network", "all"],
                },
            },
            "required": [],
        }

    async def execute(self, info_type: str = "all") -> str:
        try:
            parts = []

            if info_type in ("cpu", "all"):
                parts.append(self._get_cpu_info())
            if info_type in ("memory", "all"):
                parts.append(self._get_memory_info())
            if info_type in ("disk", "all"):
                parts.append(self._get_disk_info())
            if info_type in ("network", "all"):
                parts.append(self._get_network_info())

            if info_type == "all":
                header = (
                    f"操作系统：{platform.system()} {platform.release()}\n"
                    f"主机名：{platform.node()}\n"
                    f"Python：{platform.python_version()}\n"
                    f"启动时间：{datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                return header + "\n\n" + "\n\n".join(parts)

            return "\n\n".join(parts)

        except Exception as e:
            return f"(错误) 获取系统信息失败: {e}"

    def _get_cpu_info(self) -> str:
        freq = psutil.cpu_freq()
        freq_str = f"{freq.current:.0f}MHz" if freq else "N/A"
        lines = [
            "[CPU]",
            f"物理核心：{psutil.cpu_count(logical=False)}  逻辑核心：{psutil.cpu_count(logical=True)}",
            f"频率：{freq_str}",
            f"使用率：{psutil.cpu_percent(interval=0.5)}%",
            f"负载(1/5/15分)：{', '.join(f'{x:.2f}' for x in psutil.getloadavg())}",
        ]
        return "\n".join(lines)

    def _get_memory_info(self) -> str:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        lines = [
            "[内存]",
            f"物理内存：总计 {self._fmt(mem.total)}  可用 {self._fmt(mem.available)}  已用 {self._fmt(mem.used)} ({mem.percent}%)",
            f"交换分区：总计 {self._fmt(swap.total)}  已用 {self._fmt(swap.used)} ({swap.percent}%)",
        ]
        return "\n".join(lines)

    def _get_disk_info(self) -> str:
        lines = ["[磁盘]"]
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"{part.device}  {part.mountpoint}  "
                    f"总计 {self._fmt(usage.total)}  已用 {self._fmt(usage.used)} "
                    f"可用 {self._fmt(usage.free)} ({usage.percent}%)  [{part.fstype}]"
                )
            except PermissionError:
                lines.append(f"{part.device}  {part.mountpoint} (无权限)")
        io = psutil.disk_io_counters()
        lines.append(f"I/O 累计：读 {self._fmt(io.read_bytes)}  写 {self._fmt(io.write_bytes)}")
        return "\n".join(lines)

    def _get_network_info(self) -> str:
        net = psutil.net_io_counters()
        addrs = psutil.net_if_addrs()
        lines = ["[网络]"]
        for name, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    lines.append(f"{name}：{addr.address}")
        lines.append(f"流量累计：发送 {self._fmt(net.bytes_sent)}  接收 {self._fmt(net.bytes_recv)}")
        return "\n".join(lines)

    @staticmethod
    def _fmt(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}PB"
