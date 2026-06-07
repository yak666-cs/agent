"""
CLI entrypoint for Agent Loop Lab.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.bootstrap import register_core_skills, register_core_subagents, register_core_tools, register_runtime_tools
from agent.context import ContextManager, DEFAULT_SYSTEM_PROMPT
from agent.llm import LLMClient
from agent.loop import AgentLoop
from harness.observability import AgentObserver
from skills.manager import skill_manager
from tools.executor import ToolExecutor
from tools.registry import tool_registry
from tools.sandbox import Sandbox, SandboxMode, SandboxPolicy
from tools.selector import ToolSelector


def _register_tools() -> None:
    register_core_tools()
    register_core_subagents()


def _register_skills() -> None:
    register_core_skills()


_register_tools()
_register_skills()


def _build_agent():
    skill_prompt = skill_manager.build_skill_prompt()
    llm = LLMClient()
    ctx = ContextManager(
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        skill_prompt=skill_prompt,
    )

    agent = AgentLoop(llm=llm, context=ctx, max_turns=12)
    observer = AgentObserver(model=llm.model)
    agent.on_turn_start(observer.on_turn_start)
    agent.on_turn_end(observer.on_turn_end)
    agent.on_tool_call(observer.on_tool_call)
    agent.on_tool_result(observer.on_tool_result)
    agent.on_llm_response(observer.on_llm_response)

    agent.register_tool_registry(tool_registry)
    agent.register_tool_selector(ToolSelector(tool_registry))
    agent.register_tool_executor(ToolExecutor(sandbox=Sandbox(SandboxPolicy(mode=SandboxMode.PERMISSIVE))))
    return agent, observer


async def _beginner_mode():
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("=" * 55)
        print("  需要配置 DeepSeek / OpenAI 兼容 API Key")
        print("  1. 复制 .env.example 为 .env")
        print("  2. 在 .env 中填写 API Key")
        print("=" * 55)
        return

    print("=" * 55)
    print("  Agent Loop Lab CLI")
    print("=" * 55)
    print("\n可用 Tool:", ", ".join(tool.name for tool in tool_registry.list_enabled()))
    print("可用 Skill:", ", ".join(sorted(skill_manager._enabled)))
    print()

    agent, observer = _build_agent()

    def _cli_subagent_cb(evt, data):
        if evt == "subagent_decompose":
            print(f"\n  任务分解: {len(data['subtasks'])} 个子任务")
            for task in data["subtasks"]:
                print(f"      - [{task['id']}] {task['name']}")
        elif evt == "subagent_subtask_start":
            print(f"\n  开始子任务: {data['name']}")
        elif evt == "subagent_subtask_done":
            icon = "OK" if data["status"] == "success" else "FAIL"
            print(f"  {icon} {data['name']} ({data['duration_ms']:.0f}ms)")
        elif evt == "subagent_summary":
            print("\n  子任务汇总已完成")

    register_runtime_tools(
        llm=agent.llm,
        tool_executor=agent._tool_executor,
        tool_selector=agent._tool_selector,
        context_manager=agent.context,
        event_cb=_cli_subagent_cb,
    )

    original_execute = agent._tool_executor.execute

    async def step_execute(tool_call, tool):
        print(f"\n  调用 Tool: {tool_call.name}")
        print(f"     参数: {tool_call.arguments}")
        result = await original_execute(tool_call, tool)
        preview = (result.output or result.error or "")[:200]
        status = "成功" if result.success else "失败"
        print(f"  结果 [{status}]: {preview}")
        return result

    agent._tool_executor.execute = step_execute

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input == "/quit":
            break

        try:
            result = await agent.run(user_input)
            print(f"\n{result}\n")
            print(f"{observer.metrics.summary()}\n")
        except Exception as exc:
            print(f"\nERROR: {exc}\n")


def _load_env() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = value
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    _load_env()
    asyncio.run(_beginner_mode())
