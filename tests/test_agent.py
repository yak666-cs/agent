"""
Agent Loop Lab 测试
"""
import pytest
from agent.types import Message, Role, ToolCall, ToolResult, AgentStatus
from agent.context import ContextManager, DEFAULT_SYSTEM_PROMPT
from tools.base import BaseTool, ToolMeta, Permission
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor


# ── Context ──

class TestContext:
    def test_system_prompt_inserted(self):
        cm = ContextManager(system_prompt="你好")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert msgs[0].role == Role.SYSTEM

    def test_skill_prompt_appended(self):
        cm = ContextManager(system_prompt="你好", skill_prompt="## Skill: 测试")
        msgs = cm.build_messages([Message(role=Role.USER, content="hi")])
        assert "## Skill: 测试" in msgs[0].content


# ── ToolRegistry ──

class FakeTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(name="echo", description="回声", permission=Permission.READ_ONLY))
    def parameters_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    async def execute(self, text: str = "") -> str:
        return text

class TestToolRegistry:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg._tools = {}
        self.reg._enabled = set()

    def test_register(self):
        t = FakeTool()
        self.reg.register(t)
        assert self.reg.get("echo") is t

    def test_disable(self):
        self.reg.register(FakeTool())
        self.reg.disable("echo")
        assert self.reg.enabled_count == 0


# ── ToolExecutor ──

class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_success(self):
        exe = ToolExecutor()
        t = FakeTool()
        tc = ToolCall(id="c1", name="echo", arguments={"text": "hello"})
        r = await exe.execute(tc, t)
        assert r.success and r.output == "hello"

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio
        class Slow(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="slow", description="慢"))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                await asyncio.sleep(100)

        exe = ToolExecutor(default_timeout=0.1)
        tc = ToolCall(id="c2", name="slow", arguments={})
        r = await exe.execute(tc, Slow())
        assert not r.success and "超时" in r.error
