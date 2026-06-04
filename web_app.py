"""
Agent Loop Lab · Web 版

启动:
    python web_app.py
打开 http://127.0.0.1:8000
"""

import asyncio
import json
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.loop import AgentLoop
from agent.llm import LLMClient
from agent.context import ContextManager, DEFAULT_SYSTEM_PROMPT

# Tool 层
from tools.registry import tool_registry
from tools.selector import ToolSelector
from tools.executor import ToolExecutor
from tools.builtin.bash import BashTool
from tools.builtin.file_reader import ReadFileTool
from tools.builtin.file_writer import WriteFileTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.python_repl import PythonReplTool
from tools.builtin.file_deleter import FileDeleterTool

# Skill 层
from skills.manager import skill_manager
from skills.builtin.system_debug import SystemDebugSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def _register_all():
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(PythonReplTool())
    tool_registry.register(FileDeleterTool())

    skill_manager.register(SystemDebugSkill())
    skill_manager.register(FileOpsSkill())
    skill_manager.register(DataAnalysisSkill())
    skill_manager.register(FileManageSkill())


active_sessions: dict[str, AgentLoop] = {}


async def chat_stream(message: str, session_id: str = ""):
    queue = asyncio.Queue(maxsize=100)
    _register_all()

    skill_prompt = skill_manager.build_skill_prompt()
    llm = LLMClient()
    ctx = ContextManager(system_prompt=DEFAULT_SYSTEM_PROMPT, skill_prompt=skill_prompt)
    agent = AgentLoop(llm=llm, context=ctx, max_turns=12)
    agent.register_tool_registry(tool_registry)
    agent.register_tool_selector(ToolSelector(tool_registry))
    agent.register_tool_executor(ToolExecutor())

    if session_id:
        active_sessions[session_id] = agent

    def safe(data):
        return json.loads(json.dumps(data, ensure_ascii=False, default=str))

    def on_turn_start(state):
        queue.put_nowait(safe({"event": "turn", "data": {"turn": state.turn_count}}))

    def on_tool_call(tc):
        queue.put_nowait(safe({"event": "tool_call", "data": {"name": tc.name, "arguments": tc.arguments}}))

    def on_tool_result(tr):
        queue.put_nowait(safe({
            "event": "tool_result",
            "data": {
                "name": tr.name,
                "status": "success" if tr.success else "failed",
                "output": (tr.output or tr.error or "")[:800],
            }
        }))

    agent.on_turn_start(on_turn_start)
    agent.on_tool_call(on_tool_call)
    agent.on_tool_result(on_tool_result)

    # Web 安全规则
    orig_exec = agent._tool_executor.execute

    async def web_execute(tool_call, tool):
        # 危险操作：Web 模式下拒绝删除文件
        if tool_call.name == "file_deleter":
            from agent.types import ToolResult
            return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                              success=False, error="Web 模式下不允许删除文件")

        if tool_call.name == "bash":
            cmd = tool_call.arguments.get("command", "")
            safe_prefixes = ("ls ", "dir ", "type ", "head ", "tail ",
                            "find ", "grep ", "which ", "echo ", "pwd", "whoami",
                            "df ", "du ", "ps ", "top ", "netstat ",
                            "tasklist ", "systeminfo ", "ipconfig ", "ping ",
                            "wmic ", "chdir ", "cd ", "tree ", "fc ", "comp ",
                            "help ", "ver", "date ", "time ", "where ")
            if not any(cmd.strip().lower().startswith(p) for p in safe_prefixes):
                from agent.types import ToolResult
                return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                                  success=False, error="Web 安全限制：命令不在白名单中")
        elif tool_call.name == "write_file":
            from agent.types import ToolResult
            return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                              success=False, error="Web 模式下不允许写文件")
        return await orig_exec(tool_call, tool)

    agent._tool_executor.execute = web_execute

    async def run():
        try:
            result = await agent.run(message)
            queue.put_nowait(safe({"event": "done", "data": {"reply": result}}))
        except Exception as e:
            logging.exception("Agent 异常")
            queue.put_nowait(safe({"event": "error", "data": {"error": str(e)}}))

    asyncio.create_task(run())

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            if event['event'] in ('done', 'error'):
                break
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"

    if session_id:
        active_sessions.pop(session_id, None)


from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pathlib

app = FastAPI(title="Agent Loop Lab")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def index():
    html_path = pathlib.Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(open(html_path, encoding="utf-8").read())
    return HTMLResponse("<h1>Agent Loop Lab</h1><p>缺少 static/index.html</p>")


@app.get("/api/chat")
async def chat(request: Request, message: str = "", session_id: str = ""):
    if not message:
        return StreamingResponse(
            (f"event: error\ndata: {json.dumps({'error': '消息不能为空'})}\n\n" for _ in [1]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        chat_stream(message, session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/cancel/{session_id}")
async def cancel_chat(session_id: str):
    agent = active_sessions.get(session_id)
    if agent:
        agent.cancel()
        return {"status": "ok", "message": "已发送中断请求"}
    return {"status": "not_found", "message": "未找到活跃会话"}


if __name__ == "__main__":
    try:
        with open(pathlib.Path(__file__).parent / ".env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v
    except FileNotFoundError:
        pass

    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("需要设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    import webbrowser
    webbrowser.open("http://127.0.0.1:8000")
    print(f"启动: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
