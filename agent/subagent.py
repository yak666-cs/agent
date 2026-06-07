"""
Subagent orchestration for multi-step tasks.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .task_recipes import TaskRecipeExecutor

# ── 子代理定义（类似 Claude SDK 的 AgentDefinition） ──

@dataclass
class SubagentDef:
    """子代理声明式定义。注册后，subagent_delegate 工具可按 subagent_type 自动匹配。"""
    name: str
    description: str       # 描述何时使用（LLM 据此自动匹配）
    prompt: str            # 注入子代理的 system prompt
    tools: list[str]       # 允许的工具白名单（空 = 继承全部）
    model: str = ""        # 模型名（空 = 继承父级）
    max_turns: int = 12
    permission: str = "read_only"


class SubagentRegistry:
    """子代理定义注册表"""

    def __init__(self):
        self._defs: dict[str, SubagentDef] = {}

    def register(self, defn: SubagentDef) -> None:
        self._defs[defn.name] = defn

    def get(self, name: str) -> Optional[SubagentDef]:
        return self._defs.get(name)

    def list(self) -> list[SubagentDef]:
        return list(self._defs.values())


# 全局单例
subagent_registry = SubagentRegistry()

logger = logging.getLogger("agent.subagent")


class ExecutionMode(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    MIXED = "mixed"


@dataclass
class SubTask:
    id: str
    name: str
    description: str
    instructions: str
    dependencies: list[str] = field(default_factory=list)
    result: str = ""
    status: str = "pending"
    error: str = ""
    duration_ms: float = 0.0
    agent_trace: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    main_goal: str
    subtasks: list[SubTask]
    execution_mode: ExecutionMode = ExecutionMode.PARALLEL

    def summary(self) -> str:
        lines = [f"目标: {self.main_goal}", f"模式: {self.execution_mode.value}"]
        for task in self.subtasks:
            deps = f" [依赖: {', '.join(task.dependencies)}]" if task.dependencies else ""
            lines.append(f"  - [{task.id}] {task.name}{deps}")
        return "\n".join(lines)


class SubagentManager:
    def __init__(
        self,
        llm=None,
        tool_registry=None,
        tool_executor=None,
        tool_selector=None,
        context_manager=None,
        max_workers: int = 3,
        on_decompose=None,
        on_subtask_start=None,
        on_subtask_done=None,
        on_summary=None,
    ):
        self._llm = llm
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._tool_selector = tool_selector
        self._context_manager = context_manager
        self.max_workers = max_workers
        self._results: list[SubTask] = []
        self._task_recipes = TaskRecipeExecutor()
        self._cb_decompose = on_decompose
        self._cb_subtask_start = on_subtask_start
        self._cb_subtask_done = on_subtask_done
        self._cb_summary = on_summary

    async def run(
        self,
        main_task: str,
        context: str = "",
        mode: Optional[ExecutionMode] = None,
        previous_results: list[dict] = None,
    ) -> str:
        logger.info("SubagentManager start | task=%s", (main_task or "")[:80])
        self._main_task = main_task

        # 如果 subagent_tool 在 manager 上设置了 _subagent_def，传递给所有子任务
        subagent_def: Optional[SubagentDef] = getattr(self, '_subagent_def', None)

        decomposition = await self._decompose(main_task, context)
        if self._cb_decompose:
            self._cb_decompose(
                [
                    {"id": st.id, "name": st.name, "description": st.description}
                    for st in decomposition.subtasks
                ]
            )

        done_ids = set()
        previous_tasks_by_id: dict[str, SubTask] = {}
        if previous_results:
            for item in previous_results:
                if item.get("status") != "success":
                    continue
                task_id = str(item.get("id") or "")
                if not task_id:
                    continue
                done_ids.add(task_id)
                previous_tasks_by_id[task_id] = SubTask(
                    id=task_id,
                    name=str(item.get("name") or task_id),
                    description=str(item.get("description") or ""),
                    instructions=str(item.get("instructions") or item.get("name") or task_id),
                    result=str(item.get("result") or ""),
                    status="success",
                    duration_ms=float(item.get("duration_ms") or 0.0),
                )

        if done_ids:
            decomposition.subtasks = [task for task in decomposition.subtasks if task.id not in done_ids]

        actual_mode = self._resolve_mode(mode, decomposition)
        if actual_mode == ExecutionMode.PARALLEL:
            results = await self._execute_parallel(decomposition.subtasks, subagent_def=subagent_def)
        elif actual_mode == ExecutionMode.SEQUENTIAL:
            results = await self._execute_sequential(decomposition.subtasks, subagent_def=subagent_def)
        else:
            results = await self._execute_dependency_graph(
                decomposition.subtasks,
                completed=previous_tasks_by_id,
                subagent_def=subagent_def,
            )

        all_results = list(previous_tasks_by_id.values()) + results
        self._results = all_results

        summary = await self._summarize(main_task, all_results)
        if self._cb_summary:
            self._cb_summary(summary)

        logger.info(
            "SubagentManager done | success=%s total=%s",
            sum(1 for result in all_results if result.status == "success"),
            len(all_results),
        )
        return summary

    async def _decompose(self, main_task: str, context: str) -> DecompositionResult:
        if self._task_recipes.matches_repo_audit(main_task):
            return self._task_recipes.make_repo_audit_plan(main_task)

        if not self._llm:
            return self._simple_decompose(main_task)

        prompt = f"""你是任务分解专家。请将用户请求分解为可执行的子任务，只返回 JSON。

用户请求: {main_task}
额外上下文: {context or "(无)"}

要求:
- 每个子任务具体且独立可执行
- 有依赖关系的子任务用 dependencies 标注
- execution_mode 可选 "parallel"、"sequential"、"mixed"

JSON 格式:
{{
  "main_goal": "简短总结",
  "execution_mode": "mixed",
  "subtasks": [
    {{
      "id": "1",
      "name": "子任务名称",
      "description": "做什么",
      "instructions": "详细执行说明",
      "dependencies": []
    }}
  ]
}}"""

        from agent.types import Message, Role

        try:
            response = await self._llm.chat([Message(role=Role.USER, content=prompt)], tools=None)
            if response.finish_reason == "error" or not response.content:
                return self._simple_decompose(main_task)

            text = response.content.strip()
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()

            data = json.loads(text)
            subtasks = [
                SubTask(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    instructions=str(item.get("instructions", item.get("description", ""))),
                    dependencies=[str(dep) for dep in item.get("dependencies", [])],
                )
                for item in data.get("subtasks", [])
            ]
            if not subtasks:
                return self._simple_decompose(main_task)

            return DecompositionResult(
                main_goal=str(data.get("main_goal", main_task)),
                subtasks=subtasks,
                execution_mode=self._coerce_mode(data.get("execution_mode"), ExecutionMode.MIXED),
            )
        except Exception as exc:
            logger.warning("Task decomposition failed, using fallback: %s", exc)
            return self._simple_decompose(main_task)

    @staticmethod
    def _simple_decompose(main_task: str) -> DecompositionResult:
        lowered = (main_task or "").lower()

        if SubagentManager._looks_like_performance_task(lowered):
            return DecompositionResult(
                main_goal=main_task,
                subtasks=[
                    SubTask(
                        id="1",
                        name="收集系统信息",
                        description="采集 CPU、内存、磁盘、网络等基础系统信息",
                        instructions="收集系统基础信息，优先使用 system_info，必要时补充 bash 命令。",
                    ),
                    SubTask(
                        id="2",
                        name="检查高占用进程",
                        description="识别资源占用较高的进程",
                        instructions="查看当前高 CPU、高内存或异常状态的进程，优先使用 process_manager。",
                    ),
                    SubTask(
                        id="3",
                        name="分析瓶颈",
                        description="基于采集结果判断可能的性能瓶颈",
                        instructions="结合系统信息与进程信息分析瓶颈，并区分事实、判断和不确定项。",
                        dependencies=["1", "2"],
                    ),
                    SubTask(
                        id="4",
                        name="生成优化建议报告",
                        description="输出结构化结论与建议",
                        instructions="输出包含现状、瓶颈、优化建议、风险和待补充数据的简明报告。",
                        dependencies=["3"],
                    ),
                ],
                execution_mode=ExecutionMode.MIXED,
            )

        ordered_steps = SubagentManager._extract_ordered_steps(main_task)
        if len(ordered_steps) >= 2:
            subtasks = []
            previous_id: Optional[str] = None
            for index, step in enumerate(ordered_steps, start=1):
                dependencies = [previous_id] if previous_id else []
                subtasks.append(
                    SubTask(
                        id=str(index),
                        name=step[:24],
                        description=step,
                        instructions=step,
                        dependencies=dependencies,
                    )
                )
                previous_id = str(index)
            return DecompositionResult(
                main_goal=main_task,
                subtasks=subtasks,
                execution_mode=ExecutionMode.SEQUENTIAL,
            )

        if SubagentManager._looks_like_complex_task(lowered):
            return DecompositionResult(
                main_goal=main_task,
                subtasks=[
                    SubTask(
                        id="1",
                        name="收集上下文",
                        description="理解目标、约束和现有信息",
                        instructions=f"梳理任务目标、约束、输入材料和缺失信息：{main_task}",
                    ),
                    SubTask(
                        id="2",
                        name="执行核心任务",
                        description="完成主要工作并产出结果",
                        instructions=f"基于已收集的信息执行核心任务：{main_task}",
                        dependencies=["1"],
                    ),
                    SubTask(
                        id="3",
                        name="校验与总结",
                        description="检查完成度、风险与下一步",
                        instructions="检查结果是否满足目标，指出未完成部分、风险、验证结果，并整理最终交付内容。",
                        dependencies=["2"],
                    ),
                ],
                execution_mode=ExecutionMode.MIXED,
            )

        return DecompositionResult(
            main_goal=main_task,
            subtasks=[SubTask(id="1", name=main_task, description=main_task, instructions=main_task)],
            execution_mode=ExecutionMode.PARALLEL,
        )

    @staticmethod
    def _looks_like_complex_task(text: str) -> bool:
        if not text:
            return False
        markers = (
            "复杂",
            "先",
            "然后",
            "最后",
            "同时",
            "并且",
            "分析",
            "报告",
            "排查",
            "调研",
            "方案",
            "总结",
            "complex",
            "multi-step",
            "step by step",
            "analyze",
            "report",
        )
        return len(text) > 40 or any(marker in text for marker in markers)

    @staticmethod
    def _looks_like_performance_task(text: str) -> bool:
        if not text:
            return False
        markers = (
            "性能",
            "瓶颈",
            "cpu",
            "内存",
            "磁盘",
            "network",
            "系统信息",
            "进程",
            "优化建议",
            "performance",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _extract_ordered_steps(main_task: str) -> list[str]:
        if not main_task:
            return []

        text = re.sub(r"\s+", " ", main_task).strip(" 。；;")
        if not text:
            return []

        text = re.sub(r"^\s*(请|帮我|麻烦你|需要你)\s*", "", text)
        text = re.sub(r"(先|然后|再|接着|最后)", "|", text)
        text = text.replace("，再", "|").replace("，然后", "|").replace("，最后", "|")
        parts = [part.strip(" ，。；;|") for part in text.split("|") if part.strip(" ，。；;|")]
        return parts if len(parts) >= 2 else []

    @staticmethod
    def _coerce_mode(value, default: ExecutionMode = ExecutionMode.MIXED) -> ExecutionMode:
        if isinstance(value, ExecutionMode):
            return value
        if isinstance(value, str):
            try:
                return ExecutionMode(value.strip().lower())
            except ValueError:
                return default
        return default

    def _resolve_mode(
        self,
        requested_mode: Optional[ExecutionMode],
        decomposition: DecompositionResult,
    ) -> ExecutionMode:
        mode = self._coerce_mode(requested_mode, decomposition.execution_mode)
        has_deps = any(task.dependencies for task in decomposition.subtasks)
        if mode == ExecutionMode.MIXED:
            return ExecutionMode.MIXED if has_deps else ExecutionMode.PARALLEL
        if mode == ExecutionMode.PARALLEL and has_deps:
            return ExecutionMode.MIXED
        return mode

    def _make_child_context(self):
        from agent.context import ContextManager

        source = self._context_manager
        if not source:
            return ContextManager()
        return ContextManager(
            max_tokens=source.max_tokens,
            reserve_tokens=source.reserve_tokens,
            system_prompt=source.system_prompt,
            skill_prompt=source.skill_prompt,
            window_size=source.window_size,
            enable_summary=source.enable_summary,
            enable_relevance=source.enable_relevance,
        )

    def _make_child_registry_and_selector(self, allowed_tools: list[str] | None = None):
        """创建子 Agent 使用的受限 Registry。

        Args:
            allowed_tools: 如果提供，只放行这些工具；否则默认排除 subagent_delegate。
        """
        if not self._tool_registry:
            return None, None

        if allowed_tools:
            allowed_set = set(allowed_tools)
        else:
            allowed_set = None

        excluded = {"subagent_delegate"}

        class _FilteredRegistry:
            def __init__(self, base, allowed, blocked):
                self._base = base
                self._allowed = allowed
                self._blocked = blocked

            def get(self, name: str):
                if name in self._blocked:
                    return None
                if self._allowed is not None and name not in self._allowed:
                    return None
                return self._base.get(name)

            def list_enabled(self):
                all_tools = self._base.list_enabled()
                if self._allowed is not None:
                    return [t for t in all_tools if t.name not in self._blocked and t.name in self._allowed]
                return [t for t in all_tools if t.name not in self._blocked]

            def get_tools_for_llm(self):
                return [t.to_openai_tool() for t in self.list_enabled()]

            def disable(self, name: str):
                if hasattr(self._base, 'disable'):
                    self._base.disable(name)

            def enable(self, name: str):
                if hasattr(self._base, 'enable'):
                    self._base.enable(name)

        registry = _FilteredRegistry(self._tool_registry, allowed_set, excluded)
        selector = None
        if self._tool_selector:
            from tools.selector import ToolSelector
            selector = ToolSelector(registry, top_k=getattr(self._tool_selector, "top_k", 20))
        return registry, selector

    async def _invoke_execute_single(
        self,
        subtask: SubTask,
        context_info: str = "",
        subagent_def: Optional[SubagentDef] = None,
    ) -> SubTask:
        try:
            return await self._execute_single(
                subtask,
                context_info,
                subagent_def=subagent_def,
            )
        except TypeError as exc:
            if "unexpected keyword argument 'subagent_def'" not in str(exc):
                raise
            return await self._execute_single(subtask, context_info)

    async def _execute_single(self, subtask: SubTask, context_info: str = "",
                              subagent_def: Optional[SubagentDef] = None) -> SubTask:
        start = time.monotonic()
        subtask.status = "running"
        if self._cb_subtask_start:
            self._cb_subtask_start(subtask.id, subtask.name)

        try:
            recipe_result = self._task_recipes.maybe_execute(subtask, context_info)
            if recipe_result is not None:
                subtask.result = recipe_result
                subtask.status = "success"
                subtask.duration_ms = (time.monotonic() - start) * 1000
                if self._cb_subtask_done:
                    self._cb_subtask_done(
                        subtask.id,
                        subtask.name,
                        subtask.status,
                        (subtask.result or "")[:200],
                        subtask.duration_ms,
                    )
                return subtask

            if self._llm and self._tool_registry:
                from agent.loop import AgentLoop

                max_turns = subagent_def.max_turns if subagent_def else 15
                allowed_tools = subagent_def.tools if subagent_def else None

                ctx = self._make_child_context()
                child_registry, child_selector = self._make_child_registry_and_selector(allowed_tools)
                agent = AgentLoop(
                    llm=self._llm,
                    context=ctx,
                    max_turns=max_turns,
                    enable_orchestration=False,
                )
                if child_registry:
                    agent.register_tool_registry(child_registry)
                if self._tool_executor:
                    # 子 Agent 用 PERMISSIVE 沙箱（工具已被白名单过滤，无需沙箱二次拦截）
                    from tools.executor import ToolExecutor as _TE
                    from tools.sandbox import Sandbox, SandboxPolicy, SandboxMode
                    child_executor = _TE(sandbox=Sandbox(SandboxPolicy(mode=SandboxMode.PERMISSIVE)))
                    agent.register_tool_executor(child_executor)
                if child_selector:
                    agent.register_tool_selector(child_selector)

                # 如果有 subagent_def.prompt，用它覆写子 Agent 的 system prompt
                if subagent_def and subagent_def.prompt:
                    ctx.system_prompt = subagent_def.prompt

                full_prompt = subtask.instructions
                if context_info:
                    full_prompt = f"{context_info}\n\n---\n\nSubtask: {subtask.instructions}"

                result = await agent.run(full_prompt)
                subtask.result = result
                if "Reached max reasoning turns" in result:
                    subtask.status = "failed"
                    subtask.error = "Subtask reached max reasoning turns before completion."
                elif not result or result == "(Agent finished without text output)":
                    subtask.status = "failed"
                    subtask.error = "Subtask finished without usable output."
                else:
                    subtask.status = "success"
            else:
                subtask.result = f"[mock] {subtask.name}"
                subtask.status = "success"

            subtask.duration_ms = (time.monotonic() - start) * 1000
        except asyncio.CancelledError:
            subtask.status = "failed"
            subtask.error = "Cancelled"
            subtask.duration_ms = (time.monotonic() - start) * 1000
        except Exception as exc:
            subtask.status = "failed"
            subtask.error = f"{type(exc).__name__}: {exc}"
            subtask.duration_ms = (time.monotonic() - start) * 1000
            logger.warning("Subtask [%s] failed: %s", subtask.id, exc)

        if self._cb_subtask_done:
            self._cb_subtask_done(
                subtask.id,
                subtask.name,
                subtask.status,
                (subtask.result or "")[:200],
                subtask.duration_ms,
            )

        return subtask

    async def _execute_parallel(self, subtasks: list[SubTask],
                                 subagent_def: Optional[SubagentDef] = None) -> list[SubTask]:
        if not subtasks:
            return []

        sem = asyncio.Semaphore(self.max_workers)

        async def _run_with_sem(task: SubTask) -> SubTask:
            async with sem:
                return await self._invoke_execute_single(task, subagent_def=subagent_def)

        return await asyncio.gather(*[_run_with_sem(task) for task in subtasks])

    def _build_dependency_context(self, subtask: SubTask, completed: dict[str, SubTask]) -> str:
        lines = []
        for dep_id in subtask.dependencies:
            dep = completed.get(str(dep_id))
            if dep and dep.result:
                lines.append(f"[{dep.id}] {dep.name}\n{dep.result}")
        if not lines:
            return ""
        return "Dependency results:\n\n" + "\n\n".join(lines)

    def _mark_dependency_failed(self, subtask: SubTask, reason: str) -> SubTask:
        subtask.status = "failed"
        subtask.error = reason
        subtask.duration_ms = 0.0
        if self._cb_subtask_done:
            self._cb_subtask_done(subtask.id, subtask.name, subtask.status, "", subtask.duration_ms)
        return subtask

    async def _execute_dependency_graph(
        self,
        subtasks: list[SubTask],
        completed: dict[str, SubTask] | None = None,
        subagent_def: Optional[SubagentDef] = None,
    ) -> list[SubTask]:
        if not subtasks:
            return []

        original_order = [task.id for task in subtasks]
        original_ids = set(original_order)
        pending = {task.id: task for task in subtasks}
        completed_by_id: dict[str, SubTask] = dict(completed or {})
        completed_ids = {task_id for task_id, task in completed_by_id.items() if task.status == "success"}
        failed_ids = {task_id for task_id, task in completed_by_id.items() if task.status != "success"}
        results_by_id: dict[str, SubTask] = {}
        sem = asyncio.Semaphore(self.max_workers)

        async def _run_ready(task: SubTask) -> SubTask:
            context_info = self._build_dependency_context(task, completed_by_id)
            async with sem:
                return await self._invoke_execute_single(task, context_info, subagent_def=subagent_def)

        while pending:
            progressed = False

            for task in list(pending.values()):
                deps = {str(dep) for dep in task.dependencies if dep}
                unknown = deps - original_ids - completed_ids - failed_ids
                if unknown:
                    result = self._mark_dependency_failed(task, f"Unknown dependencies: {', '.join(sorted(unknown))}")
                    pending.pop(task.id, None)
                    failed_ids.add(task.id)
                    completed_by_id[task.id] = result
                    results_by_id[task.id] = result
                    progressed = True
                    continue

                failed_deps = deps & failed_ids
                if failed_deps:
                    result = self._mark_dependency_failed(task, f"Dependency failed: {', '.join(sorted(failed_deps))}")
                    pending.pop(task.id, None)
                    failed_ids.add(task.id)
                    completed_by_id[task.id] = result
                    results_by_id[task.id] = result
                    progressed = True

            ready = [task for task in pending.values() if {str(dep) for dep in task.dependencies if dep} <= completed_ids]
            if ready:
                batch = await asyncio.gather(*[_run_ready(task) for task in ready])
                for result in batch:
                    pending.pop(result.id, None)
                    completed_by_id[result.id] = result
                    results_by_id[result.id] = result
                    if result.status == "success":
                        completed_ids.add(result.id)
                    else:
                        failed_ids.add(result.id)
                progressed = True

            if not progressed:
                for task in list(pending.values()):
                    result = self._mark_dependency_failed(task, "Dependency cycle or unsatisfied dependencies")
                    pending.pop(task.id, None)
                    failed_ids.add(task.id)
                    completed_by_id[task.id] = result
                    results_by_id[task.id] = result

        return [results_by_id[task_id] for task_id in original_order if task_id in results_by_id]

    async def _execute_sequential(self, subtasks: list[SubTask],
                                   subagent_def: Optional[SubagentDef] = None) -> list[SubTask]:
        results = []
        context = ""
        for task in subtasks:
            result = await self._invoke_execute_single(task, context, subagent_def=subagent_def)
            results.append(result)
            if result.status == "success" and result.result:
                context = result.result
        return results

    async def _summarize(self, main_task: str, results: list[SubTask]) -> str:
        successes = [result for result in results if result.status == "success"]
        total_time = sum(result.duration_ms for result in results)

        if not self._llm or not successes:
            lines = [f"## 任务总结: {main_task}", ""]
            for result in results:
                lines.append(f"### {result.name} ({result.duration_ms:.0f}ms)")
                if result.result:
                    lines.append(result.result[:500])
                elif result.error:
                    lines.append(f"(失败) {result.error}")
                lines.append("")
            return "\n".join(lines)

        summary_prompt = f"""总结以下子任务执行结果，用中文简洁回答。

主任务: {main_task}

执行结果:
{json.dumps([{"id": r.id, "name": r.name, "status": r.status, "result_preview": r.result[:500] if r.result else "", "error": r.error} for r in results], ensure_ascii=False, indent=2)}

要求:
- 整合成功子任务的有用发现
- 明确提及失败或不完整的子任务，不要隐藏
- 区分确认的事实、基于事实的判断、缺失的信息
- 最后给出下一步的实用建议"""

        from agent.types import Message, Role

        try:
            response = await self._llm.chat([Message(role=Role.USER, content=summary_prompt)], tools=None)
            if response.content:
                return response.content
        except Exception:
            pass

        return f"Task completed with {len(successes)}/{len(results)} successful subtasks in {total_time:.0f}ms."

    @staticmethod
    def _decide_mode(decomposition: DecompositionResult) -> ExecutionMode:
        return ExecutionMode.MIXED if any(task.dependencies for task in decomposition.subtasks) else ExecutionMode.PARALLEL
