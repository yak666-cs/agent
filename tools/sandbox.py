"""
Sandbox —— 工具执行的策略沙箱

三层安全边界：
1. 文件系统沙箱 — 限制工具可读写的路径
2. 命令沙箱 — 限制 bash 工具可执行的命令
3. 资源沙箱 — 限制工具执行时间和输出大小

策略可配置：严格模式（默认拒绝一切未授权操作）vs 宽松模式（默认允许）。
"""

import os
import re
import fnmatch
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


class SandboxMode:
    """安全模式"""
    RESTRICTIVE = "restrictive"   # 默认拒绝，白名单放行
    PERMISSIVE = "permissive"     # 默认允许，黑名单拦截


# ── 默认安全策略 ──

# 允许读的文件路径模式
DEFAULT_ALLOWED_READ_PATHS = [
    "C:\\Users\\*\\Desktop\\*",
    "C:\\Users\\*\\Documents\\*",
    "/home/*",
    "/tmp/*",
]

# 禁止读的敏感路径
DEFAULT_BLOCKED_READ_PATHS = [
    "*\\.env*",
    "*\\.git\\*",
    "*\\.ssh\\*",
    "*\\config\\*secret*",
    "*\\*password*",
    "*\\*credential*",
    "C:\\Windows\\*",
    "/etc/shadow*",
    "/etc/passwd*",
    "C:\\Users\\*\\AppData\\Local\\*",
]

# 默认禁止的系统命令
DEFAULT_BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~",
    "format ", "del /f /s", "rd /s /q",
    "shutdown", "reboot", "halt",
    "> /dev/sda", "dd if=",
    ":(){ :|:& };:",  # fork bomb
    "chmod -R 777 /", "chmod 777 /",
    "mkfs.", "fdisk",
]

# 默认文件名黑名单（禁止写入）
DEFAULT_WRITE_BLOCKED_FILES = [
    "*.exe", "*.dll", "*.sys", "*.bat", "*.vbs", "*.ps1",
    "*.sh", "*.bin", "*.msi",
]


@dataclass
class SandboxPolicy:
    """
    沙箱策略配置。

    可以传入自定义策略，也可使用默认策略。
    """
    mode: str = SandboxMode.RESTRICTIVE
    allowed_read_paths: list[str] = field(default_factory=lambda: DEFAULT_ALLOWED_READ_PATHS[:])
    blocked_read_paths: list[str] = field(default_factory=lambda: DEFAULT_BLOCKED_READ_PATHS[:])
    blocked_commands: list[str] = field(default_factory=lambda: DEFAULT_BLOCKED_COMMANDS[:])
    write_blocked_files: list[str] = field(default_factory=lambda: DEFAULT_WRITE_BLOCKED_FILES[:])
    disabled_tools: list[str] = field(default_factory=list)        # 完全禁用的工具列表
    allowed_commands: list[str] = field(default_factory=list)      # bash 命令白名单（非空时启用）
    max_output_lines: int = 5000
    max_output_chars: int = 50_000
    allowed_working_dirs: list[str] = field(default_factory=list)
    allowed_net_hosts: list[str] = field(default_factory=list)  # 网络白名单


class Sandbox:
    """
    策略沙箱 —— 在工具执行前做安全检查。

    用法:
        sandbox = Sandbox()
        result = sandbox.check("bash", {"command": "ls -la"})
        if result.allowed:
            # 执行工具
        else:
            # 拒绝执行，返回 result.reason
    """

    def __init__(self, policy: Optional[SandboxPolicy] = None):
        self.policy = policy or SandboxPolicy()

    @dataclass
    class CheckResult:
        allowed: bool
        reason: str = ""

    # ── 文件系统检查 ──

    def check_read_path(self, path: str) -> CheckResult:
        """检查路径是否允许读取。"""
        abs_path = os.path.abspath(os.path.normpath(path))

        # 宽松模式：只检查黑名单
        if self.policy.mode == SandboxMode.PERMISSIVE:
            if self._matches_any(abs_path, self.policy.blocked_read_paths):
                return self.CheckResult(False, f"路径在黑名单中: {path}")
            return self.CheckResult(True)

        # 严格模式：检查白名单 + 黑名单
        if not self._matches_any(abs_path, self.policy.allowed_read_paths):
            return self.CheckResult(False, f"路径不在白名单中: {path}")
        if self._matches_any(abs_path, self.policy.blocked_read_paths):
            return self.CheckResult(False, f"路径在黑名单中: {path}")
        return self.CheckResult(True)

    def check_write_path(self, path: str, content: str = "") -> CheckResult:
        """检查路径是否允许写入。"""
        filename = os.path.basename(path)
        if self._matches_any(filename, self.policy.write_blocked_files):
            return self.CheckResult(False, f"禁止写入该文件类型: {filename}")
        if self._matches_any(path, self.policy.blocked_read_paths):
            return self.CheckResult(False, f"路径在黑名单中: {path}")
        return self.CheckResult(True)

    # ── 命令检查 ──

    def check_command(self, command: str) -> CheckResult:
        """检查 shell 命令是否允许执行。"""
        cmd = command.strip().lower()

        # 命令白名单（非空时启用：只允许以这些前缀开头的命令）
        if self.policy.allowed_commands:
            if not any(cmd.startswith(p.lower()) for p in self.policy.allowed_commands):
                return self.CheckResult(False, "命令不在白名单中")

        # 检查黑名单
        for blocked in self.policy.blocked_commands:
            if cmd.startswith(blocked.lower()) or blocked.lower() in cmd:
                return self.CheckResult(False, f"命令被禁止: {blocked}")

        # 严格模式：限制更多
        if self.policy.mode == SandboxMode.RESTRICTIVE:
            dangerous_patterns = [
                r"\bsudo\b", r"\bsu\b", r"\bwget\b", r"\bcurl\b.*\-O",
                r"\bnc\b", r"\bnmap\b", r"\bchown\b",
                r">\s*/dev/", r"\bdd\b", r"\bmkfs\b",
            ]
            for pat in dangerous_patterns:
                if re.search(pat, cmd):
                    return self.CheckResult(False, f"严格模式禁止危险命令: {pat}")

        return self.CheckResult(True)

    # ── 资源检查 ──

    def check_output_size(self, output: str) -> CheckResult:
        """检查输出是否超过限制。"""
        lines = output.count("\n")
        chars = len(output)
        if lines > self.policy.max_output_lines:
            return self.CheckResult(False, f"输出行数 ({lines}) 超过限制 ({self.policy.max_output_lines})")
        if chars > self.policy.max_output_chars:
            return self.CheckResult(False, f"输出字符数 ({chars:,}) 超过限制 ({self.policy.max_output_chars:,})")
        return self.CheckResult(True)

    # ── 统一入口 ──

    def check(self, tool_name: str, arguments: dict) -> CheckResult:
        """统一安全检查入口。"""
        # 检查工具是否被完全禁用
        if tool_name in self.policy.disabled_tools:
            return self.CheckResult(False, f"工具已被禁用: {tool_name}")

        if tool_name == "bash":
            cmd = arguments.get("command", "")
            return self.check_command(cmd)
        elif tool_name in ("read_file", "read_document"):
            path = arguments.get("path", arguments.get("file_path", ""))
            return self.check_read_path(path)
        elif tool_name in ("write_file", "file_writer"):
            path = arguments.get("path", arguments.get("file_path", ""))
            content = arguments.get("content", "")
            return self.check_write_path(path, content)
        elif tool_name == "file_deleter":
            path = arguments.get("path", arguments.get("file_path", ""))
            if self._matches_any(path, self.policy.blocked_read_paths):
                return self.CheckResult(False, f"禁止删除受保护路径: {path}")
            return self.CheckResult(True)
        elif tool_name == "web_search":
            return self.CheckResult(True)
        return self.CheckResult(True)

    # ── 工具方法 ──

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        """检查 text 是否匹配任意一个 fnmatch 模式。"""
        text_lower = text.lower()
        for pat in patterns:
            if fnmatch.fnmatch(text_lower, pat.lower()):
                return True
            if pat.lower() in text_lower:
                return True
        return False


# 全局单例（宽松模式，默认允许）
default_sandbox = Sandbox(SandboxPolicy(mode=SandboxMode.PERMISSIVE))
