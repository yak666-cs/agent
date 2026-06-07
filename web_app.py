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
from agent.bootstrap import register_core_skills, register_core_subagents, register_core_tools, register_runtime_tools

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

# 工程化模块
from harness.observability import AgentObserver
from tools.prompt_cache import prompt_cache
from tools.sandbox import Sandbox, SandboxPolicy, SandboxMode
from harness.resilience import CircuitState

# 全局可配置沙箱（所有会话共享，前端可实时调整）
_sandbox_policy = SandboxPolicy(
    mode=SandboxMode.RESTRICTIVE,
    disabled_tools=["file_deleter"],
    allowed_commands=[
        "ls ", "dir ", "type ", "head ", "tail ",
        "find ", "grep ", "which ", "echo ", "pwd", "whoami",
        "df ", "du ", "ps ", "top ", "netstat ",
        "tasklist ", "systeminfo ", "ipconfig ", "ping ",
        "wmic ", "chdir ", "cd ", "tree ", "fc ", "comp ",
        "help ", "ver", "date ", "time ", "where ",
    ],
)
active_sandbox = Sandbox(_sandbox_policy)

# Skill 层
from skills.manager import skill_manager
from skills.builtin.system_debug import SystemDebugSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def _register_all():
    register_core_tools()
    register_core_subagents()
    register_core_skills()


active_sessions: dict[str, AgentLoop] = {}


def _sandbox_blocked_intent_reply(message: str) -> str | None:
    """Return an immediate user-facing sandbox denial for common blocked intents."""
    text = (message or "").lower()
    if "write_file" not in _sandbox_policy.disabled_tools:
        return None

    write_markers = [
        "写入", "创建", "新建", "保存", "生成", "建立",
        "write", "create", "save",
    ]
    file_markers = [
        "文件", "文档", ".txt", ".md", ".json", ".csv", ".py",
        "file", "document",
    ]

    if any(k in text for k in write_markers) and any(k in text for k in file_markers):
        return "沙盒当前已禁用文件写入工具 write_file，所以我不能创建或写入文件。"

    return None


def _build_sandbox_prompt() -> str:
    disabled = ", ".join(_sandbox_policy.disabled_tools) or "none"
    return (
        "\n\n## Runtime Sandbox Policy\n"
        f"Disabled tools: {disabled}.\n"
        "If a user request requires a disabled tool, do not claim the task is done. "
        "Explain that the sandbox has disabled that capability and name the disabled tool."
    )


async def chat_stream(message: str, session_id: str = ""):
    queue = asyncio.Queue(maxsize=100)
    _register_all()

    blocked_reply = _sandbox_blocked_intent_reply(message)
    if blocked_reply:
        yield f"event: done\ndata: {json.dumps({'reply': blocked_reply}, ensure_ascii=False)}\n\n"
        return

    skill_prompt = skill_manager.build_skill_prompt() + _build_sandbox_prompt()
    llm = LLMClient()
    ctx = ContextManager(
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        skill_prompt=skill_prompt,
    )
    agent = AgentLoop(llm=llm, context=ctx, max_turns=12)
    agent.register_tool_registry(tool_registry)
    agent.register_tool_selector(ToolSelector(tool_registry))

    agent.register_tool_executor(ToolExecutor(sandbox=active_sandbox))

    # Subagent 委派工具
    from tools.builtin.subagent_tool import SubagentDelegateTool
    tool_registry.register(SubagentDelegateTool(
        llm=llm,
        tool_registry=tool_registry,
        tool_executor=agent._tool_executor,
        tool_selector=agent._tool_selector,
        context_manager=ctx,
        event_cb=lambda evt, data: queue.put_nowait(safe({"event": evt, "data": data})),
    ))

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

    # 观测器
    observer = AgentObserver(model="deepseek-v4-flash", session_id=session_id)
    agent.register_observer(observer)

    async def run():
        try:
            result = await agent.run(message)
            # 保存会话历史到数据库
            if session_id and hasattr(agent, '_last_state'):
                try:
                    rows = []
                    for m in agent._last_state.messages:
                        if m.role.name == "SYSTEM":
                            continue
                        tool_data = None
                        if m.tool_calls:
                            tool_data = {"type": "tool_calls", "data": m.tool_calls}
                        elif m.role.name == "TOOL":
                            tool_data = {"type": "tool_result",
                                         "tool_call_id": m.tool_call_id,
                                         "name": m.name}
                        rows.append({
                            "role": m.role.value,
                            "content": m.content,
                            "tool_data": tool_data,
                        })
                    if rows:
                        conversation_store.replace_session_messages(session_id, rows)
                except Exception:
                    pass
            # 包含观测器指标 + 系统状态
            metrics = observer.metrics.to_dict() if observer.metrics else {}
            cb = agent._circuit_breaker
            queue.put_nowait(safe({
                "event": "done", "data": {
                    "reply": result,
                    "metrics": metrics,
                    "harness": {
                        "circuit_breaker": cb.state.value,
                        "cache_hit_rate": round(prompt_cache.stats.hit_rate, 3),
                        "cache_hits": prompt_cache.stats.hits,
                        "cache_misses": prompt_cache.stats.misses,
                        "sandbox_mode": agent._tool_executor.sandbox.policy.mode,
                    },
                }
            }))
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


from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pathlib
import time

from memory.conversation_store import ConversationStore

conversation_store = ConversationStore()


def get_next_session_name() -> str:
    existing = conversation_store.list_sessions(999)
    used = set()
    for s in existing:
        name = s.get("name", "")
        if name.startswith("对话 ") and name[3:].isdigit():
            used.add(int(name[3:]))
    n = 1
    while n in used:
        n += 1
    return f"对话 {n}"


def gen_session_id() -> str:
    return f"s{int(time.time())}_{__import__('random').Random().randint(100000, 999999)}"


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    ".txt": "文本文档", ".md": "Markdown", ".py": "Python", ".js": "JavaScript",
    ".ts": "TypeScript", ".jsx": "React JSX", ".tsx": "React TSX",
    ".java": "Java", ".cpp": "C++", ".c": "C", ".h": "C 头文件", ".hpp": "C++ 头文件",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
    ".sh": "Shell", ".bat": "批处理", ".ps1": "PowerShell",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "Less",
    ".json": "JSON", ".xml": "XML", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "配置文件", ".conf": "配置文件",
    ".log": "日志", ".env": "环境变量",
    ".csv": "CSV", ".tsv": "TSV", ".sql": "SQL", ".r": "R", ".m": "MATLAB",
    ".pdf": "PDF 文档", ".docx": "Word 文档", ".doc": "Word 文档",
    ".xlsx": "Excel 表格", ".xls": "Excel 表格",
    ".png": "PNG 图片", ".jpg": "JPEG 图片", ".jpeg": "JPEG 图片",
    ".gif": "GIF 图片", ".webp": "WebP 图片", ".bmp": "BMP 图片", ".ico": "ICO 图标",
    ".svg": "SVG 矢量图",
}

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


@app.get("/api/supported-types")
async def get_supported_types():
    return JSONResponse(SUPPORTED_EXTENSIONS)


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        types_list = ", ".join(sorted(SUPPORTED_EXTENSIONS.keys()))
        return JSONResponse(
            {"error": f"不支持 {ext}，支持的类型有：{types_list}"},
            status_code=400,
        )
    safe_name = f"{int(time.time())}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    target_path = os.path.normpath(save_path)
    resp = {
        "filename": file.filename,
        "path": target_path,
        "size": len(content),
        "type": SUPPORTED_EXTENSIONS.get(ext, "未知"),
    }
    return JSONResponse(resp)


@app.get("/api/sessions")
async def list_sessions():
    return conversation_store.list_sessions(50)


@app.get("/api/sessions/{sid}/messages")
async def get_session_messages(sid: str):
    msgs = conversation_store.get_messages(sid)
    return msgs


@app.post("/api/sessions")
async def create_session():
    sid = gen_session_id()
    name = get_next_session_name()
    conversation_store.create_session(sid, name)
    return {"id": sid, "name": name}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    conversation_store.delete_session(sid)
    return {"status": "ok"}


@app.put("/api/sessions/{sid}/rename")
async def rename_session(sid: str, name: str = ""):
    if name:
        ok = conversation_store.rename_session(sid, name)
        return {"status": "ok" if ok else "error"}
    return {"status": "error", "error": "名称为空"}


@app.get("/favicon.ico")
async def favicon():
    ico_path = pathlib.Path(__file__).parent / "kai_agent.ico"
    if ico_path.exists():
        return Response(open(ico_path, "rb").read(), media_type="image/x-icon")
    return Response(status_code=204)


@app.get("/__ICON__")
async def app_icon():
    ico_path = pathlib.Path(__file__).parent / "kai_agent.ico"
    if ico_path.exists():
        return Response(open(ico_path, "rb").read(), media_type="image/x-icon")
    return Response(status_code=204)


# ── 沙箱配置 API ──


@app.get("/api/sandbox/config")
async def get_sandbox_config():
    """获取当前沙箱配置"""
    p = _sandbox_policy
    return {
        "mode": p.mode,
        "disabled_tools": p.disabled_tools,
        "allowed_commands": p.allowed_commands,
        "blocked_commands": p.blocked_commands,
        "write_blocked_files": p.write_blocked_files,
        "max_output_lines": p.max_output_lines,
        "max_output_chars": p.max_output_chars,
    }


@app.put("/api/sandbox/config")
async def update_sandbox_config(body: dict):
    """更新沙箱配置（仅更新请求中携带的字段）"""
    p = _sandbox_policy
    if "mode" in body and body["mode"] in (SandboxMode.RESTRICTIVE, SandboxMode.PERMISSIVE):
        p.mode = body["mode"]
    if "disabled_tools" in body and isinstance(body["disabled_tools"], list):
        p.disabled_tools = body["disabled_tools"]
    if "allowed_commands" in body and isinstance(body["allowed_commands"], list):
        p.allowed_commands = body["allowed_commands"]
    if "blocked_commands" in body and isinstance(body["blocked_commands"], list):
        p.blocked_commands = body["blocked_commands"]
    if "write_blocked_files" in body and isinstance(body["write_blocked_files"], list):
        p.write_blocked_files = body["write_blocked_files"]
    if "max_output_lines" in body and isinstance(body["max_output_lines"], int):
        p.max_output_lines = max(100, body["max_output_lines"])
    if "max_output_chars" in body and isinstance(body["max_output_chars"], int):
        p.max_output_chars = max(1000, body["max_output_chars"])
    return {"status": "ok", "mode": p.mode}


if __name__ == "__main__":
    try:
        with open(pathlib.Path(__file__).parent / ".env", encoding="utf-8") as f:
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
