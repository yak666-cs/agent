"""
Subagent Delegate Tool —— 将复杂任务委派给子 Agent 池

主 Agent 通过调用此工具，将复杂任务拆解为多个子任务并行/串行执行。
"""

import json
from tools.base import BaseTool, ToolMeta, Permission


class SubagentDelegateTool(BaseTool):
    """将复杂任务委派给子 Agent 池去分解和执行。"""

    def __init__(self, llm=None, tool_registry=None, tool_executor=None,
                 tool_selector=None, context_manager=None, event_cb=None):
        super().__init__(ToolMeta(
            name="subagent_delegate",
            description="当用户要求同时做多件不同领域的事（如同时查CPU、内存、磁盘、进程、网络），"
                        "或者任务可以拆成多个独立子任务并行执行时，使用此工具将任务分解为子任务并行处理。"
                        "特别适合：同时查多个系统指标、同时搜索多个信息、批量文件操作、多维度分析报告。"
                        "注意：如果某些子任务失败，工具结果末尾会包含JSON格式的子任务明细，"
                        "你可以解析后将status=success的任务填入previous_results参数重试，避免重复执行已成功的子任务。",
            permission=Permission.READ_ONLY,
            timeout_seconds=300.0,
            tags=["agent", "delegation"],
        ))
        self._llm = llm
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._tool_selector = tool_selector
        self._context_manager = context_manager
        self._event_cb = event_cb

    def _emit(self, event: str, data: dict):
        if self._event_cb:
            try:
                self._event_cb(event, data)
            except Exception:
                pass

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "需要委派的复杂任务描述，越详细越好",
                },
                "previous_results": {
                    "type": "string",
                    "description": "可选。如果之前已经执行过部分子任务，"
                                   "把上次成功的子任务结果以JSON数组传进来跳过重跑。"
                                   "格式: [{\"id\":\"1\",\"name\":\"...\",\"result\":\"...\",\"status\":\"success\"}]",
                },
                "mode": {
                    "type": "string",
                    "enum": ["mixed", "parallel", "sequential"],
                    "description": "执行模式。mixed 会按依赖关系分批并发；parallel 强制无依赖并发；sequential 串行执行。",
                },
                "max_workers": {
                    "type": "integer",
                    "description": "最大并发子任务数，默认 3，建议 1-8。",
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str = "",
        previous_results: str = "",
        mode: str = "mixed",
        max_workers: int = 3,
        **kwargs,
    ) -> str:
        if not task:
            return "错误：缺少 task 参数"

        from agent.subagent import ExecutionMode, SubagentManager

        # 解析之前已完成的子任务结果
        parsed_previous = []
        if previous_results:
            try:
                parsed_previous = json.loads(previous_results)
                if not isinstance(parsed_previous, list):
                    parsed_previous = []
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            execution_mode = ExecutionMode(str(mode).strip().lower())
        except ValueError:
            execution_mode = ExecutionMode.MIXED

        try:
            worker_count = int(max_workers)
        except (TypeError, ValueError):
            worker_count = 3
        worker_count = min(max(worker_count, 1), 8)

        manager = SubagentManager(
            llm=self._llm,
            tool_registry=self._tool_registry,
            tool_executor=self._tool_executor,
            tool_selector=self._tool_selector,
            context_manager=self._context_manager,
            max_workers=worker_count,
            on_decompose=lambda subtasks: self._emit("subagent_decompose", {
                "subtasks": subtasks,
            }),
            on_subtask_start=lambda sid, name: self._emit("subagent_subtask_start", {
                "subtask_id": sid, "name": name,
            }),
            on_subtask_done=lambda sid, name, status, preview, ms: self._emit("subagent_subtask_done", {
                "subtask_id": sid, "name": name, "status": status,
                "result_preview": preview, "duration_ms": ms,
            }),
            on_summary=lambda summary: self._emit("subagent_summary", {
                "summary": summary,
            }),
        )

        try:
            summary = await manager.run(
                task,
                mode=execution_mode,
                previous_results=parsed_previous,
            )
            # 发送子任务耗时详情（前端展示用）
            if manager._results:
                total_ms = sum(st.duration_ms for st in manager._results)
                self._emit("subagent_timing", {
                    "mode": execution_mode.value,
                    "total_duration_ms": total_ms,
                    "subtasks": [
                        {"id": st.id, "name": st.name, "status": st.status, "duration_ms": st.duration_ms}
                        for st in manager._results
                    ],
                })
            # 构建含每个子任务状态的结构化结果，方便 LLM 后续只重试失败的任务
            results_json = json.dumps([
                {"id": st.id, "name": st.name, "status": st.status,
                 "dependencies": st.dependencies, "error": st.error,
                 "result": (st.result or "")[:500], "duration_ms": st.duration_ms}
                for st in manager._results
            ], ensure_ascii=False)
            return f"{summary}\n\n---\n子任务明细:\n{results_json}"
        except Exception as e:
            return f"子 Agent 执行失败: {type(e).__name__}: {str(e)}"
