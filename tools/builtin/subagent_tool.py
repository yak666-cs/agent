"""
Subagent Delegate Tool —— 将复杂任务委派给子 Agent 池

主 Agent 通过调用此工具，将复杂任务拆解为多个子任务并行/串行执行。
支持按 subagent_type 从注册表加载预定义的子代理配置，实现工具/模型隔离。
"""

import json
from tools.base import BaseTool, ToolMeta, Permission


class SubagentDelegateTool(BaseTool):
    """将复杂任务委派给子 Agent 池去分解和执行。"""

    def __init__(self, llm=None, tool_registry=None, tool_executor=None,
                 tool_selector=None, context_manager=None, event_cb=None):
        super().__init__(ToolMeta(
            name="subagent_delegate",
            description="【复杂任务分解工具】收到包含3个以上独立子任务的请求时，必须使用此工具分解为并行子任务，"
                        "不要自己串行执行！传入 task 参数描述总任务，工具会自动分解为子任务并行执行。"
                        "subagent_type 参数可指定预定义的子代理类型（如 code-auditor、security-reviewer）。"
                        "如果之前执行过部分子任务，把上次结果中的status=success任务填入previous_results参数跳过重跑。",
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

    def _available_subagent_types(self) -> str:
        """返回注册的子代理类型描述，供 LLM 参考"""
        try:
            from agent.subagent import subagent_registry
            defs = subagent_registry.list()
            if not defs:
                return ""
            lines = ["可用子代理类型（传入 subagent_type 参数可直用预定义配置）:"]
            for d in defs:
                tools_str = ", ".join(d.tools) if d.tools else "全部"
                lines.append(f"  - {d.name}: {d.description}（工具: {tools_str}）")
            return "\n".join(lines)
        except Exception:
            return ""

    @property
    def description(self) -> str:
        """动态描述：附带当前注册的子代理类型"""
        base = self.meta.description
        types = self._available_subagent_types()
        if types:
            return base + "\n\n" + types
        return base

    def parameters_schema(self) -> dict:
        props = {
            "task": {
                "type": "string",
                "description": "需要委派的复杂任务描述，越详细越好",
            },
            "subagent_type": {
                "type": "string",
                "description": "可选。预定义子代理类型，用 LLM 自动分解执行。"
                               "留空则由 LLM 自动规划子任务。可用类型见 tooltip。",
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
        }
        return {"type": "object", "properties": props, "required": ["task"]}

    async def execute(
        self,
        task: str = "",
        subagent_type: str = "",
        previous_results: str = "",
        mode: str = "mixed",
        max_workers: int = 3,
        **kwargs,
    ) -> str:
        if not task:
            return "错误：缺少 task 参数"

        # ── 从注册表查找子代理定义 ──
        subagent_def = None
        if subagent_type:
            from agent.subagent import subagent_registry
            subagent_def = subagent_registry.get(subagent_type.strip().lower())
            if not subagent_def:
                return f"错误：未知的子代理类型 '{subagent_type}'，可用类型：{self._available_subagent_types()}"

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
            # 如果有 subagent_def，将其传给 run 方法（通过 manager 的额外属性）
            if subagent_def:
                manager._subagent_def = subagent_def

            summary = await manager.run(
                task,
                mode=execution_mode,
                previous_results=parsed_previous,
            )

            # 发送子任务耗时详情
            if hasattr(manager, '_results') and manager._results:
                total_ms = sum(st.duration_ms for st in manager._results)
                self._emit("subagent_timing", {
                    "mode": execution_mode.value,
                    "total_duration_ms": total_ms,
                    "subtasks": [
                        {"id": st.id, "name": st.name, "status": st.status, "duration_ms": st.duration_ms}
                        for st in manager._results
                    ],
                })

            # 构建含每个子任务状态的结构化结果
            results_json = json.dumps([
                {"id": st.id, "name": st.name, "status": st.status,
                 "dependencies": st.dependencies, "error": st.error,
                 "result": (st.result or "")[:500], "duration_ms": st.duration_ms}
                for st in manager._results
            ], ensure_ascii=False)
            return f"{summary}\n\n---\n子任务明细:\n{results_json}"
        except Exception as e:
            return f"子 Agent 执行失败: {type(e).__name__}: {str(e)}"
