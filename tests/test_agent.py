"""Agent Loop Lab tests."""

import pytest

from agent.context import ContextManager
from agent.types import Message, Role, ToolCall
from tools.base import BaseTool, Permission, ToolMeta
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.selector import ToolSelector
from KAI_AGENT import _build_sandbox_prompt, _sandbox_blocked_intent_reply


class FakeTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(name="echo", description="echo text", permission=Permission.READ_ONLY))

    def parameters_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, text: str = "") -> str:
        return text


class SystemInfoTestTool(BaseTool):
    def __init__(self):
        super().__init__(
            ToolMeta(
                name="system_info",
                description="collect system performance information",
                permission=Permission.READ_ONLY,
                tags=["system", "info"],
            )
        )

    def parameters_schema(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "system"


class SubagentTestTool(BaseTool):
    def __init__(self):
        super().__init__(
            ToolMeta(
                name="subagent_delegate",
                description="decompose complex tasks",
                permission=Permission.READ_ONLY,
                tags=["agent", "delegation"],
            )
        )

    def parameters_schema(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "delegated"


class TestSandboxPolicyPrompt:
    def test_write_file_disabled_intent_gets_clear_reply(self):
        reply = _sandbox_blocked_intent_reply("在桌面创建一个 1.txt 文档，写入你好 dyk")
        assert reply is not None
        assert "write_file" in reply

    def test_sandbox_prompt_lists_disabled_write_file(self):
        prompt = _build_sandbox_prompt()
        assert "Disabled tools" in prompt
        assert "write_file" in prompt


class TestContext:
    def test_system_prompt_inserted(self):
        cm = ContextManager(system_prompt="你好")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert msgs[0].role == Role.SYSTEM

    def test_skill_prompt_appended(self):
        cm = ContextManager(system_prompt="你好", skill_prompt="## Skill: 测试")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert "## Skill: 测试" in msgs[0].content


class TestToolRegistry:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg._tools = {}
        self.reg._enabled = set()

    def test_register(self):
        tool = FakeTool()
        self.reg.register(tool)
        assert self.reg.get("echo") is tool

    def test_disable(self):
        self.reg.register(FakeTool())
        self.reg.disable("echo")
        assert self.reg.enabled_count == 0


class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_success(self):
        exe = ToolExecutor()
        tool = FakeTool()
        tc = ToolCall(id="c1", name="echo", arguments={"text": "hello"})
        result = await exe.execute(tc, tool)
        assert result.success and result.output == "hello"

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio

        class SlowTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="slow", description="slow tool", timeout_seconds=0.1))

            def parameters_schema(self):
                return {"type": "object", "properties": {}}

            async def execute(self) -> str:
                await asyncio.sleep(100)
                return ""

        exe = ToolExecutor(default_timeout=0.1)
        tc = ToolCall(id="c2", name="slow", arguments={})
        result = await exe.execute(tc, SlowTool())
        assert not result.success
        assert "超时" in (result.error or "")


class TestToolSelector:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg._tools = {}
        self.reg._enabled = set()
        self.reg.register(FakeTool())
        self.reg.register(SystemInfoTestTool())
        self.reg.register(SubagentTestTool())

    def test_complex_tasks_prefer_subagent_delegate(self):
        selector = ToolSelector(self.reg, top_k=2)
        names = [tool.name for tool in selector.filter_by_intent("请先分析系统性能，再输出优化报告")]
        assert names[0] == "subagent_delegate"
        assert "system_info" in names
