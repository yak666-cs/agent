"""
KAI AGENT —— 桌面应用

双击启动，自动运行 FastAPI 后端 + pywebview 原生窗口。
类 Cursor/Codex 桌面应用体验。
"""

import asyncio
import io
import json
import os
import sys
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 提前加载 .env ──
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

from agent.loop import AgentLoop
from agent.llm import LLMClient
from agent.context import ContextManager, DEFAULT_SYSTEM_PROMPT

from tools.registry import tool_registry
from tools.selector import ToolSelector
from tools.executor import ToolExecutor
from tools.builtin.bash import BashTool
from tools.builtin.file_reader import ReadFileTool
from tools.builtin.file_writer import WriteFileTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.python_repl import PythonReplTool
from tools.builtin.file_deleter import FileDeleterTool
from tools.builtin.system_info import SystemInfoTool
from tools.builtin.process_manager import ProcessManagerTool
from tools.builtin.read_document import ReadDocumentTool

from tools.builtin.memory_tool import MemoryTool

from skills.manager import skill_manager
from skills.builtin.system_debug import SystemDebugSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill
from skills.builtin.memory import MemorySkill

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def _register_all():
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(PythonReplTool())
    tool_registry.register(FileDeleterTool())
    tool_registry.register(SystemInfoTool())
    tool_registry.register(ProcessManagerTool())
    tool_registry.register(ReadDocumentTool())
    tool_registry.register(MemoryTool())

    skill_manager.register(SystemDebugSkill())
    skill_manager.register(FileOpsSkill())
    skill_manager.register(DataAnalysisSkill())
    skill_manager.register(FileManageSkill())
    skill_manager.register(MemorySkill())


# 活跃会话管理
active_sessions: dict[str, AgentLoop] = {}

# 多会话持久化
from dataclasses import dataclass
from agent.types import Message

@dataclass
class SessionMeta:
    id: str
    name: str
    created_at: float
    updated_at: float
    message_count: int = 0

sessions_meta: dict[str, SessionMeta] = {}
sessions_history: dict[str, list[Message]] = {}


def gen_session_id() -> str:
    import time
    return f"s{int(time.time())}_{__import__('random').Random().randint(100000, 999999)}"


async def chat_stream(message: str, session_id: str = "", file_context: str = ""):
    queue = asyncio.Queue(maxsize=100)
    _register_all()

    # 加载会话历史
    history_msgs = []
    if session_id and session_id in sessions_history:
        history_msgs = sessions_history[session_id]

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

    orig_exec = agent._tool_executor.execute

    async def web_execute(tool_call, tool):
        if tool_call.name == "file_deleter":
            from agent.types import ToolResult
            return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                              success=False, error="桌面应用模式下不允许删除文件")

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
                                  success=False, error="安全限制：命令不在白名单中")
        elif tool_call.name == "write_file":
            from agent.types import ToolResult
            return ToolResult(tool_call_id=tool_call.id, name=tool_call.name,
                              success=False, error="桌面应用模式下不允许写文件")
        return await orig_exec(tool_call, tool)

    agent._tool_executor.execute = web_execute

    # 如果有文件上下文，拼到用户消息前
    augmented_message = f"{file_context}\n\n{message}" if file_context else message

    # 注入相关长期记忆
    try:
        from memory import MemoryStore
        mem_store = MemoryStore()
        mem_context = mem_store.get_relevant_context(message)
        if mem_context:
            augmented_message = f"{mem_context}\n\n---\n\n{augmented_message}"
    except Exception:
        pass

    async def run():
        try:
            result = await agent.run(augmented_message, previous_messages=history_msgs)

            # 保存会话历史（去掉 system 消息）
            if session_id and hasattr(agent, '_last_state'):
                msgs = [m for m in agent._last_state.messages if m.role.name != "SYSTEM"]
                sessions_history[session_id] = msgs
                if session_id in sessions_meta:
                    sessions_meta[session_id].message_count = len(msgs)

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


# ── FastAPI ──
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pathlib

app = FastAPI(title="KAI AGENT")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    # 文本与代码
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
    ".csv": "CSV", ".tsv": "TSV",
    ".sql": "SQL", ".r": "R", ".m": "MATLAB",
    # 文档
    ".pdf": "PDF 文档",
    ".docx": "Word 文档", ".doc": "Word 文档",
    ".xlsx": "Excel 表格", ".xls": "Excel 表格",
    # 图片（读取基本信息）
    ".png": "PNG 图片", ".jpg": "JPEG 图片", ".jpeg": "JPEG 图片",
    ".gif": "GIF 图片", ".webp": "WebP 图片", ".bmp": "BMP 图片", ".ico": "ICO 图标",
    ".svg": "SVG 矢量图",
}


@app.get("/api/supported-types")
async def get_supported_types():
    """返回支持的文件类型列表"""
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

    import time
    safe_name = f"{int(time.time())}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    target_path = os.path.normpath(save_path)
    return JSONResponse({
        "filename": file.filename,
        "saved_as": safe_name,
        "path": target_path,
        "size": len(content),
        "type": SUPPORTED_EXTENSIONS.get(ext, "未知"),
    })


# ── 多会话 API ──

@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    items = [
        {
            "id": s.id,
            "name": s.name,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "message_count": s.message_count,
        }
        for s in sessions_meta.values()
    ]
    return sorted(items, key=lambda x: x["updated_at"], reverse=True)


@app.post("/api/sessions")
async def create_session():
    """创建新会话，自动分配不重复的名称"""
    sid = gen_session_id()
    import time
    # 找最小可用编号
    used = set()
    for s in sessions_meta.values():
        name = s.name
        if name.startswith("对话 ") and name[3:].isdigit():
            used.add(int(name[3:]))
    n = 1
    while n in used:
        n += 1
    meta = SessionMeta(id=sid, name=f"对话 {n}",
                       created_at=time.time(), updated_at=time.time())
    sessions_meta[sid] = meta
    sessions_history[sid] = []
    return {"id": sid, "name": meta.name}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    """删除会话"""
    sessions_meta.pop(sid, None)
    sessions_history.pop(sid, None)
    return {"status": "ok"}


@app.put("/api/sessions/{sid}/rename")
async def rename_session(sid: str, name: str = ""):
    """重命名会话"""
    if sid in sessions_meta and name:
        sessions_meta[sid].name = name
        return {"status": "ok", "name": name}
    return {"status": "error", "error": "会话不存在或名称为空"}


@app.get("/")
async def index():
    html_path = pathlib.Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(open(html_path, encoding="utf-8").read())
    return HTMLResponse("<h1>KAI AGENT</h1><p>缺少 static/index.html</p>")


@app.get("/api/chat")
async def chat(request: Request, message: str = "", session_id: str = "", file_path: str = ""):
    if not message:
        return StreamingResponse(
            (f"event: error\ndata: {json.dumps({'error': '消息不能为空'})}\n\n" for _ in [1]),
            media_type="text/event-stream",
        )

    # 如果 session 不存在，自动创建
    if session_id and session_id not in sessions_meta:
        import time
        n = len(sessions_meta) + 1
        meta = SessionMeta(id=session_id, name=f"对话 {n}",
                           created_at=time.time(), updated_at=time.time())
        sessions_meta[session_id] = meta
        sessions_history[session_id] = []

    # 如果有上传文件，在 Agent 上下文中注入文件信息
    file_context = ""
    if file_path and os.path.exists(file_path):
        fname = os.path.basename(file_path)
        fext = os.path.splitext(fname)[1].lower()
        fsize = os.path.getsize(file_path)
        ftype = SUPPORTED_EXTENSIONS.get(fext, "未知")
        size_str = f"{fsize/1024:.1f}KB" if fsize > 1024 else f"{fsize}B"
        file_context = f"用户已上传文件：{fname}（{ftype}，{size_str}）\n文件绝对路径：{os.path.normpath(file_path)}\n如需处理该文件，请使用 read_file 工具读取其内容。"

    return StreamingResponse(
        chat_stream(message, session_id, file_context),
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


# ── 桌面窗口 ──
import socket

def _kill_old_instance(port: int):
    """杀掉占用指定端口的旧进程"""
    try:
        import subprocess
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit():
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
    except Exception:
        pass


def start_server(port: int):
    import uvicorn

    class ReuseAddrServer(uvicorn.Server):
        def create_socket(self, family, type_, proto):
            sock = socket.socket(family, type_, proto)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.config.host, self.config.port))
            sock.setblocking(False)
            return sock

    # pythonw.exe 无控制台 sys.stdout=None，uvicorn 默认 log_config 会调用
    # sys.stdout.isatty() 导致 AttributeError。日志写入文件。
    log_file = os.path.join(os.path.dirname(__file__), "kai_server.log")
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning",
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "plain": {"format": "%(asctime)s %(levelname)s %(message)s"},
            },
            "handlers": {
                "plain": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "plain",
                    "filename": log_file,
                    "maxBytes": 1048576,
                    "backupCount": 2,
                },
            },
            "loggers": {
                "uvicorn": {"handlers": ["plain"], "level": "WARNING"},
                "uvicorn.error": {"handlers": ["plain"], "level": "WARNING"},
            },
        },
    )
    server = ReuseAddrServer(config=config)
    server.run()


def main():
    port = int(os.environ.get("KAI_AGENT_PORT", 8765))

    _kill_old_instance(port)

    t = threading.Thread(target=start_server, args=(port,), daemon=True)
    t.start()

    # 轮询等待服务器就绪
    import time
    import urllib.request
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # 读取前端页面，注入 base URL 和图标
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("<head>", f"<head><base href=\"{url}/\">")

    # 生成图标的 base64 数据
    import base64
    from PIL import Image
    icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "OIP-C.webp")
    img = Image.open(icon_path).convert("RGBA")
    img = img.resize((32, 32), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    icon_b64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    html = html.replace("__ICON__", icon_b64)

    # pywebview 窗口
    import webview
    window = webview.create_window(
        "KAI AGENT",
        html=html,
        width=900,
        height=700,
        resizable=True,
        min_size=(600, 400),
    )

    # ── 系统托盘 ──
    import pystray
    from PIL import Image

    ico_path = os.path.join(os.path.dirname(__file__), "kai_agent.ico")
    tray_img = Image.open(ico_path)

    def on_show(icon, item):
        """单击托盘图标：显示窗口"""
        try:
            window.show()
        except Exception:
            pass

    def on_quit(icon, item):
        """右键退出：彻底杀死进程"""
        icon.stop()
        os._exit(0)

    def _start_tray():
        icon = pystray.Icon(
            "kai_agent", tray_img, "KAI AGENT",
            menu=pystray.Menu(
                pystray.MenuItem("显示窗口", on_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", on_quit),
            ),
        )
        icon.run()

    tray_thread = threading.Thread(target=_start_tray, daemon=True)
    tray_thread.start()

    # 点击 X 时隐藏到托盘
    def on_closing():
        try:
            window.hide()
        except Exception:
            pass

    window.events.closing += on_closing

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
