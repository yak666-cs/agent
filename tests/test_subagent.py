import asyncio
import time

import pytest

from agent.subagent import (
    DecompositionResult,
    ExecutionMode,
    SubTask,
    SubagentManager,
)


class TimedSubagentManager(SubagentManager):
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


@pytest.mark.asyncio
async def test_independent_subtasks_start_in_parallel():
    manager = TimedSubagentManager(
        [
            SubTask(id="1", name="one", description="", instructions="one"),
            SubTask(id="2", name="two", description="", instructions="two"),
        ],
        max_workers=2,
    )

    await manager.run("main", mode=ExecutionMode.MIXED)

    first_two_events = manager.events[:2]
    assert [event[0] for event in first_two_events] == ["start", "start"]
    assert {event[1] for event in first_two_events} == {"1", "2"}


@pytest.mark.asyncio
async def test_dependencies_run_after_their_prerequisites():
    manager = TimedSubagentManager(
        [
            SubTask(id="1", name="one", description="", instructions="one"),
            SubTask(id="2", name="two", description="", instructions="two"),
            SubTask(
                id="3",
                name="three",
                description="",
                instructions="three",
                dependencies=["1", "2"],
            ),
        ],
        max_workers=3,
    )

    await manager.run("main", mode=ExecutionMode.MIXED)

    times = {(event[0], event[1]): event[2] for event in manager.events}
    assert times[("start", "3")] >= times[("end", "1")]
    assert times[("start", "3")] >= times[("end", "2")]


def test_simple_decompose_builds_performance_workflow():
    result = SubagentManager._simple_decompose("分析当前系统性能并生成优化建议报告")

    assert result.execution_mode == ExecutionMode.MIXED
    assert [task.name for task in result.subtasks] == [
        "收集系统信息",
        "检查高占用进程",
        "分析瓶颈",
        "生成优化建议报告",
    ]
    assert result.subtasks[2].dependencies == ["1", "2"]
    assert result.subtasks[3].dependencies == ["3"]


def test_simple_decompose_respects_ordered_steps():
    result = SubagentManager._simple_decompose("先读取README，再分析代码，最后输出报告")

    assert result.execution_mode == ExecutionMode.SEQUENTIAL
    assert len(result.subtasks) == 3
    assert result.subtasks[1].dependencies == ["1"]
    assert result.subtasks[2].dependencies == ["2"]
