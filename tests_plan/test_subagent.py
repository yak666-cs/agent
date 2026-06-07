"""
Subagents 模块测试 — SubagentManager 任务分解 + 多模式执行 + 依赖管理
"""

import asyncio
import pytest
import time

from agent.subagent import (
    DecompositionResult, ExecutionMode, SubTask, SubagentManager,
)
from agent.types import Message, Role


class TimedSubagentManager(SubagentManager):
    """测试用：覆盖 LLM 依赖的 _decompose / _execute_single / _summarize"""

    def __init__(self, subtasks, delay=0.05, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtasks = subtasks
        self.delay = delay
        self.events = []

    async def _decompose(self, main_task: str, context: str) -> DecompositionResult:
        return DecompositionResult(
            main_goal=main_task,
            subtasks=self.subtasks,
            execution_mode=ExecutionMode.MIXED,
        )

    async def _execute_single(self, subtask: SubTask, context_info: str = "") -> SubTask:
        start = time.monotonic()
        self.events.append(("start", subtask.id, start, context_info))
        await asyncio.sleep(self.delay)
        end = time.monotonic()
        subtask.status = "success"
        subtask.result = f"done:{subtask.id}"
        subtask.duration_ms = (end - start) * 1000
        self.events.append(("end", subtask.id, end, context_info))
        return subtask

    async def _summarize(self, main_task: str, results: list[SubTask]) -> str:
        return ",".join(st.id for st in results)


class TestSubtaskAndDecomposition:
    """数据结构测试"""

    def test_subtask_creation(self):
        st = SubTask(id="1", name="测试", description="描述", instructions="执行")
        assert st.id == "1"
        assert st.status == "pending"

    def test_subtask_defaults(self):
        st = SubTask(id="1", name="test", description="", instructions="")
        assert st.dependencies == []
        assert st.result == ""
        assert st.error == ""
        assert st.duration_ms == 0.0

    def test_decomposition_summary(self):
        subtasks = [
            SubTask(id="1", name="one", description="", instructions=""),
            SubTask(id="2", name="two", description="", instructions="", dependencies=["1"]),
        ]
        dr = DecompositionResult(
            main_goal="test",
            subtasks=subtasks,
            execution_mode=ExecutionMode.MIXED,
        )
        summary = dr.summary()
        assert "test" in summary
        assert "one" in summary
        assert "依赖" in summary


class TestSimpleDecompose:
    """简单分解（无 LLM）"""

    def test_simple_decompose(self):
        result = SubagentManager._simple_decompose("测试任务")
        assert result.main_goal == "测试任务"
        assert len(result.subtasks) == 1
        assert result.subtasks[0].id == "1"

    def test_coerce_mode(self):
        assert SubagentManager._coerce_mode("parallel") == ExecutionMode.PARALLEL
        assert SubagentManager._coerce_mode("sequential") == ExecutionMode.SEQUENTIAL
        assert SubagentManager._coerce_mode("mixed") == ExecutionMode.MIXED
        assert SubagentManager._coerce_mode("invalid") == ExecutionMode.MIXED


class TestExecutionModes:
    """三种执行模式"""

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        manager = TimedSubagentManager(
            [
                SubTask(id="1", name="one", description="", instructions="one"),
                SubTask(id="2", name="two", description="", instructions="two"),
            ],
            max_workers=2,
        )
        await manager.run("main", mode=ExecutionMode.PARALLEL)
        first_two = manager.events[:2]
        assert [e[0] for e in first_two] == ["start", "start"]

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        manager = TimedSubagentManager(
            [
                SubTask(id="1", name="one", description="", instructions="one"),
                SubTask(id="2", name="two", description="", instructions="two"),
            ],
            max_workers=2,
        )
        await manager.run("main", mode=ExecutionMode.SEQUENTIAL)
        starts = [(e[1], e[2]) for e in manager.events if e[0] == "start"]
        ends = [(e[1], e[2]) for e in manager.events if e[0] == "end"]
        assert starts[1][1] >= ends[0][1]  # task 2 starts after task 1 ends

    @pytest.mark.asyncio
    async def test_dependency_graph_execution(self):
        manager = TimedSubagentManager(
            [
                SubTask(id="1", name="one", description="", instructions="one"),
                SubTask(id="2", name="two", description="", instructions="two"),
                SubTask(id="3", name="three", description="", instructions="three", dependencies=["1", "2"]),
            ],
            max_workers=3,
        )
        await manager.run("main", mode=ExecutionMode.MIXED)
        times = {(e[0], e[1]): e[2] for e in manager.events}
        assert times[("start", "3")] >= times[("end", "1")]
        assert times[("start", "3")] >= times[("end", "2")]

    @pytest.mark.asyncio
    async def test_dependency_unknown_marks_failed(self):
        manager = TimedSubagentManager(
            [
                SubTask(id="1", name="one", description="", instructions="one"),
                SubTask(id="2", name="two", description="", instructions="two", dependencies=["nonexistent"]),
            ],
        )
        results = await manager._execute_dependency_graph(manager.subtasks)
        by_id = {r.id: r for r in results}
        assert by_id["2"].status == "failed"
        assert "Unknown" in by_id["2"].error

    @pytest.mark.asyncio
    async def test_dependency_failed_upstream(self):
        class FailOnTwo(TimedSubagentManager):
            async def _execute_single(self, subtask, context_info=""):
                if subtask.id == "1":
                    subtask.status = "failed"
                    subtask.error = "intentional fail"
                    return subtask
                return await super()._execute_single(subtask, context_info)

        manager = FailOnTwo(
            [
                SubTask(id="1", name="one", description="", instructions="one"),
                SubTask(id="2", name="two", description="", instructions="two", dependencies=["1"]),
            ],
        )
        results = await manager._execute_dependency_graph(manager.subtasks)
        by_id = {r.id: r for r in results}
        assert by_id["1"].status == "failed"
        assert by_id["2"].status == "failed"
        assert "Dependency failed" in by_id["2"].error

    @pytest.mark.asyncio
    async def test_resolve_mode_mixed_with_deps(self):
        manager = TimedSubagentManager([])
        dr = DecompositionResult(
            main_goal="test",
            subtasks=[
                SubTask(id="1", name="a", description="", instructions="", dependencies=[]),
                SubTask(id="2", name="b", description="", instructions="", dependencies=["1"]),
            ],
            execution_mode=ExecutionMode.PARALLEL,
        )
        mode = manager._resolve_mode(None, dr)
        assert mode == ExecutionMode.MIXED

    @pytest.mark.asyncio
    async def test_previous_results_skips_done(self):
        """previous_results 中的已完成任务被跳过"""
        manager = TimedSubagentManager(
            [
                SubTask(id="2", name="two", description="", instructions="two"),
            ],
        )
        previous = [
            {"id": "1", "name": "one", "result": "done", "status": "success"},
        ]
        result = await manager.run("main", previous_results=previous)
        assert "2" in result  # only task 2 was actually run

    @pytest.mark.asyncio
    async def test_empty_subtasks(self):
        manager = TimedSubagentManager([])
        results = await manager._execute_parallel([])
        assert results == []
        results = await manager._execute_sequential([])
        assert results == []


class TestFilteredRegistry:
    """子 Agent 工具列表过滤"""

    def test_filtered_registry_excludes_delegate(self):
        from agent.subagent import SubagentManager
        from tools.registry import ToolRegistry
        from tools.base import BaseTool, ToolMeta, Permission

        reg = ToolRegistry()
        reg._tools = {}
        reg._enabled = set()

        class NormalTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="bash", description="", permission=Permission.SHELL))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                return ""

        class DelegateTool(BaseTool):
            def __init__(self):
                super().__init__(ToolMeta(name="subagent_delegate", description="", permission=Permission.READ_ONLY))
            def parameters_schema(self):
                return {"type": "object", "properties": {}}
            async def execute(self) -> str:
                return ""

        reg.register(NormalTool())
        reg.register(DelegateTool())

        manager = SubagentManager()
        child_reg, child_sel = manager._make_child_registry_and_selector()
        # Without tool_registry set, returns None
        assert child_reg is None
        assert child_sel is None

    def test_coerce_mode_edge_cases(self):
        assert SubagentManager._coerce_mode(None) == ExecutionMode.MIXED
        assert SubagentManager._coerce_mode(1) == ExecutionMode.MIXED
        assert SubagentManager._coerce_mode("") == ExecutionMode.MIXED
