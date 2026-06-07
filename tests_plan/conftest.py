"""
KAI Agent Test Fixtures - shared across all test modules
"""

import pytest
import tempfile
import os
import pathlib

from agent.types import Message, Role, ToolCall, ToolResult
from agent.context import ContextManager
from tools.base import BaseTool, ToolMeta, Permission
from tools.registry import ToolRegistry
from tools.selector import ToolSelector
from tools.executor import ToolExecutor
from tools.sandbox import Sandbox, SandboxPolicy, SandboxMode
from memory import MemoryStore
from memory.conversation_store import ConversationStore


# ── Helper Tools ──

class EchoTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(name="echo", description="回声工具", permission=Permission.READ_ONLY))
    def parameters_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    async def execute(self, text: str = "") -> str:
        return text


class AddTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(name="add", description="加法", permission=Permission.READ_ONLY))
    def parameters_schema(self):
        return {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}
    async def execute(self, a: float = 0, b: float = 0) -> str:
        return str(a + b)


# ── Fixtures ──

@pytest.fixture
def echo_tool():
    return EchoTool()


@pytest.fixture
def add_tool():
    return AddTool()


@pytest.fixture
def fresh_registry():
    reg = ToolRegistry()
    reg._tools = {}
    reg._enabled = set()
    return reg


@pytest.fixture
def fresh_executor():
    return ToolExecutor(default_timeout=5.0)


@pytest.fixture
def restrictive_sandbox():
    return Sandbox(SandboxPolicy(
        mode=SandboxMode.RESTRICTIVE,
        allowed_read_paths=["C:\\Users\\*\\Desktop\\*"],
        blocked_commands=["rm -rf /", "format "],
        disabled_tools=["write_file"],
    ))


@pytest.fixture
def permissive_sandbox():
    return Sandbox(SandboxPolicy(mode=SandboxMode.PERMISSIVE))


@pytest.fixture
def temp_db_dir():
    """Create a temp dir for SQLite databases used in tests."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def temp_memory_store(temp_db_dir):
    db_path = os.path.join(temp_db_dir, "test_memory.db")
    store = MemoryStore(db_path=db_path)
    yield store
    store.close()


@pytest.fixture
def temp_conversation_store(temp_db_dir):
    db_path = os.path.join(temp_db_dir, "test_conversations.db")
    store = ConversationStore(db_path=db_path)
    yield store
    store.close()


@pytest.fixture
def ctx_manager():
    return ContextManager(system_prompt="你是 Kai Agent。")


@pytest.fixture
def sample_tool_call():
    return ToolCall(id="call_1", name="echo", arguments={"text": "hello"})


@pytest.fixture
def sample_tool_result():
    return ToolResult(tool_call_id="call_1", name="echo", success=True, output="hello", duration_ms=10.0)
