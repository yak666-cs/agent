"""
Skills/Multi-tool 模块测试 — ToolRegistry + ToolSelector + SkillManager + ToolExecutor
"""

import pytest
from tools.base import BaseTool, ToolMeta, Permission
from tools.registry import ToolRegistry
from tools.selector import ToolSelector
from tools.executor import ToolExecutor
from skills.manager import SkillManager
from skills.base import BaseSkill, SkillMeta
from agent.types import ToolCall, ToolResult


class TestToolRegistry:
    """工具注册/获取/禁用"""

    def test_register_and_get(self, fresh_registry, echo_tool):
        fresh_registry.register(echo_tool)
        assert fresh_registry.get("echo") is echo_tool

    def test_get_nonexistent(self, fresh_registry):
        assert fresh_registry.get("nonexistent") is None

    def test_disable(self, fresh_registry, echo_tool):
        fresh_registry.register(echo_tool)
        fresh_registry.disable("echo")
        assert fresh_registry.enabled_count == 0
        assert echo_tool.name not in fresh_registry._enabled

    def test_enable(self, fresh_registry, echo_tool):
        fresh_registry.register(echo_tool, enabled=False)
        assert fresh_registry.enabled_count == 0
        fresh_registry.enable("echo")
        assert fresh_registry.enabled_count == 1

    def test_unregister(self, fresh_registry, echo_tool):
        fresh_registry.register(echo_tool)
        fresh_registry.unregister("echo")
        assert fresh_registry.get("echo") is None
        assert fresh_registry.enabled_count == 0

    def test_list_enabled(self, fresh_registry, echo_tool, add_tool):
        fresh_registry.register(echo_tool, enabled=True)
        fresh_registry.register(add_tool, enabled=False)
        enabled = fresh_registry.list_enabled()
        names = [t.name for t in enabled]
        assert "echo" in names
        assert "add" not in names

    def test_get_tools_for_llm(self, fresh_registry, echo_tool):
        fresh_registry.register(echo_tool)
        tools = fresh_registry.get_tools_for_llm()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "echo"


class TestToolSelector:
    """工具选择器"""

    def test_build_tools_for_llm(self, fresh_registry, echo_tool, add_tool):
        fresh_registry.register(echo_tool)
        fresh_registry.register(add_tool)
        selector = ToolSelector(fresh_registry, top_k=20)
        tools = selector.build_tools_for_llm("帮我算一下")
        names = [t["function"]["name"] for t in tools]
        assert "echo" in names
        assert "add" in names

    def test_filter_disabled(self, fresh_registry, echo_tool, add_tool):
        fresh_registry.register(echo_tool)
        fresh_registry.register(add_tool)
        fresh_registry.disable("add")
        selector = ToolSelector(fresh_registry)
        tools = selector.build_tools_for_llm("帮我算一下")
        names = [t["function"]["name"] for t in tools]
        assert "add" not in names

    def test_top_k_limit(self, fresh_registry, echo_tool, add_tool):
        fresh_registry.register(echo_tool)
        fresh_registry.register(add_tool)
        selector = ToolSelector(fresh_registry, top_k=1)
        tools = selector.build_tools_for_llm("test")
        assert len(tools) == 1


class TestToolExecutor:
    """工具执行器"""

    @pytest.mark.asyncio
    async def test_success(self, fresh_executor, echo_tool):
        tc = ToolCall(id="c1", name="echo", arguments={"text": "hello"})
        r = await fresh_executor.execute(tc, echo_tool)
        assert r.success is True
        assert r.output == "hello"

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio

        class SlowTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="slow", description="慢", timeout_seconds=0.1))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                await asyncio.sleep(10)

        exe = ToolExecutor(default_timeout=0.1)
        tc = ToolCall(id="c2", name="slow", arguments={})
        r = await exe.execute(tc, SlowTool())
        assert r.success is False
        assert "超时" in r.error

    @pytest.mark.asyncio
    async def test_tool_not_found_raises_attribute_error(self, fresh_executor):
        """Executor raises AttributeError when tool is None (handled by AgentLoop)."""
        tc = ToolCall(id="c3", name="nonexistent", arguments={})
        with pytest.raises(AttributeError):
            await fresh_executor.execute(tc, None)

    @pytest.mark.asyncio
    async def test_sandbox_rejection(self, fresh_executor):
        from tools.sandbox import Sandbox, SandboxPolicy, SandboxMode
        sandbox = Sandbox(SandboxPolicy(mode=SandboxMode.RESTRICTIVE, disabled_tools=["echo"]))
        exe = ToolExecutor(sandbox=sandbox)
        tc = ToolCall(id="c4", name="echo", arguments={"text": "x"})
        from conftest import EchoTool
        r = await exe.execute(tc, EchoTool())
        assert r.success is False
        assert "沙箱拒绝" in r.error

    @pytest.mark.asyncio
    async def test_output_truncation(self):
        exe = ToolExecutor(max_output_chars=50)

        class LongOutputTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="long", description="长输出", permission=Permission.READ_ONLY))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                return "a" * 1000

        tc = ToolCall(id="c5", name="long", arguments={})
        r = await exe.execute(tc, LongOutputTool())
        assert r.success is True
        assert len(r.output) <= 50 + 100  # truncation message
        assert "被截断" in r.output


class TestSkillManager:
    """Skill 管理器"""

    def test_register_and_build_prompt(self):
        sm = SkillManager()
        sm._skills = {}
        sm._enabled = set()

        class FakeSkill(BaseSkill):
            def __init__(self):
                super().__init__(SkillMeta(name="test_skill", description="测试"))
            def get_prompt(self):
                return "## Skill: 测试技能\n你可以帮我做测试。"

        sm.register(FakeSkill())
        prompt = sm.build_skill_prompt()
        assert "测试技能" in prompt

    def test_multiple_skills(self):
        sm = SkillManager()
        sm._skills = {}
        sm._enabled = set()

        class SkillA(BaseSkill):
            def __init__(self):
                super().__init__(SkillMeta(name="skill_a", description="A"))
            def get_prompt(self):
                return "## Skill: A"

        class SkillB(BaseSkill):
            def __init__(self):
                super().__init__(SkillMeta(name="skill_b", description="B"))
            def get_prompt(self):
                return "## Skill: B"

        sm.register(SkillA())
        sm.register(SkillB())
        prompt = sm.build_skill_prompt()
        assert "Skill: A" in prompt
        assert "Skill: B" in prompt

    def test_disabled_skill_not_in_prompt(self):
        sm = SkillManager()
        sm._skills = {}
        sm._enabled = set()

        class FakeSkill(BaseSkill):
            def __init__(self):
                super().__init__(SkillMeta(name="disabled_skill", description="禁用"))
            def get_prompt(self):
                return "## Skill: 禁用技能"

        sm.register(FakeSkill(), enabled=False)
        prompt = sm.build_skill_prompt()
        assert prompt == ""

    def test_disable_skill(self):
        sm = SkillManager()
        sm._skills = {}
        sm._enabled = set()

        class FakeSkill(BaseSkill):
            def __init__(self):
                super().__init__(SkillMeta(name="toggled_skill", description="切换"))
            def get_prompt(self):
                return "## Skill: 切换技能"

        sm.register(FakeSkill(), enabled=True)
        assert sm.enabled_count == 1
        sm.disable("toggled_skill")
        assert sm.enabled_count == 0
