"""
Agent Loop Lab · CLI 版

用法:
    python main.py             普通模式
    python main.py --simple    学习模式
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.loop import AgentLoop
from agent.llm import LLMClient
from agent.context import ContextManager, DEFAULT_SYSTEM_PROMPT
from agent.types import AgentState

# ---- 引入 Tool 层（可执行代码） ----
from tools.registry import tool_registry
from tools.selector import ToolSelector
from tools.executor import ToolExecutor
from tools.builtin.bash import BashTool
from tools.builtin.file_reader import ReadFileTool
from tools.builtin.file_writer import WriteFileTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.python_repl import PythonReplTool
from tools.builtin.file_deleter import FileDeleterTool

# ---- 引入 Skill 层（纯提示词） ----
from skills.manager import skill_manager
from skills.builtin.system_debug import SystemDebugSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill


def _register_tools():
    """注册所有 Tool（可执行代码）"""
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(PythonReplTool())
    tool_registry.register(FileDeleterTool())


def _register_skills():
    """注册所有 Skill（纯提示词，注入 System Prompt）"""
    skill_manager.register(SystemDebugSkill())
    skill_manager.register(FileOpsSkill())
    skill_manager.register(DataAnalysisSkill())
    skill_manager.register(FileManageSkill())


# 模块加载时即注册 Tool 和 Skill
_register_tools()
_register_skills()


async def _check_dangerous(tool_name: str, args: dict) -> bool:
    if tool_name == "bash":
        cmd = args.get("command", "")
        safe = ("ls ", "dir ", "cat ", "type ", "head ", "tail ",
                "find ", "grep ", "which ", "echo ", "pwd", "whoami",
                "df ", "du ", "ps ", "top ", "netstat ", "lsof ", "ss ",
                "tasklist ", "systeminfo ", "ipconfig ", "ping ", "tracert ",
                "wmic ", "chdir ", "cd ", "tree ", "help ",
                "ver", "date ", "time ", "where ")
        if any(cmd.strip().lower().startswith(p) for p in safe):
            return True

    print(f"\n  ⚠ Tool 想执行: {tool_name}")
    if tool_name == "bash":
        print(f"     命令: {args.get('command', '?')}")
    elif tool_name == "write_file":
        print(f"     文件: {args.get('path', '?')}")
    resp = input("  允许吗？[y/N] ").strip().lower()
    return resp in ("y", "yes")


def _build_agent():
    # Skill 提示词注入 System Prompt
    skill_prompt = skill_manager.build_skill_prompt()

    llm = LLMClient()
    ctx = ContextManager(
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        skill_prompt=skill_prompt,
    )

    agent = AgentLoop(llm=llm, context=ctx, max_turns=12)
    agent.register_tool_registry(tool_registry)
    agent.register_tool_selector(ToolSelector(tool_registry))
    agent.register_tool_executor(ToolExecutor())
    return agent


async def _beginner_mode():
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("=" * 55)
        print("  需要 DeepSeek API Key！")
        print("  1. 打开 https://platform.deepseek.com/api_keys")
        print("  2. 注册并创建 API Key（新用户送 500 万 token 免费额度）")
        print("=" * 55)
        return

    print("=" * 55)
    print("  Agent Loop Lab · 学习模式")
    print("=" * 55)
    print("\n可用 Tool:", ", ".join(t.name for t in tool_registry.list_enabled()))
    print("可用 Skill:", ", ".join(s for s in skill_manager._enabled))
    print()

    agent = _build_agent()
    orig_exec = agent._tool_executor.execute

    async def step_execute(tool_call, tool):
        print(f"\n  🔧 调用 Tool: {tool_call.name}")
        print(f"     参数: {tool_call.arguments}")
        if tool.meta.requires_confirmation:
            if not await _check_dangerous(tool_call.name, tool_call.arguments):
                from agent.types import ToolResult
                return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                                  success=False, error="用户取消了")
        result = await orig_exec(tool_call, tool)
        preview = (result.output or result.error or "")[:200]
        status = "成功" if result.success else "失败"
        print(f"  📋 结果 [{status}]: {preview}")
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
            print(f"\n✅ {result}\n")
        except Exception as e:
            print(f"\n❌ {e}\n")


if __name__ == "__main__":
    try:
        with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v
    except FileNotFoundError:
        pass

    asyncio.run(_beginner_mode() if "--simple" in sys.argv else _beginner_mode())
