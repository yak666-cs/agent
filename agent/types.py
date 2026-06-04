"""
Agent Loop 核心类型定义

Message  → 发给 LLM 的消息
ToolCall → LLM 返回的工具调用请求
ToolResult → 工具执行结果
AgentState → Agent 当前状态
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import json


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"       # 等待 LLM 响应
    EXECUTING = "executing"      # 正在执行工具
    DONE = "done"
    ERROR = "error"
    MAX_TURNS = "max_turns"      # 达到最大轮次
    CANCELLED = "cancelled"      # 用户中断


@dataclass
class Message:
    """对话消息"""
    role: Role
    content: str
    tool_call_id: Optional[str] = None   # tool 角色时使用
    name: Optional[str] = None           # 工具名称
    tool_calls: Optional[list[dict]] = None  # assistant 角色时的工具调用

    def to_dict(self) -> dict:
        msg = {"role": self.role.value}
        if self.content:
            msg["content"] = self.content
        else:
            msg["content"] = None
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class ToolCall:
    """LLM 请求的工具调用"""
    id: str
    name: str
    arguments: dict

    @staticmethod
    def from_dict(data: dict) -> "ToolCall":
        return ToolCall(
            id=data["id"],
            name=data["function"]["name"],
            arguments=json.loads(data["function"]["arguments"])
        )


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_call_id: str
    name: str
    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class AgentState:
    """Agent 运行时的完整状态"""
    messages: list[Message] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    turn_count: int = 0
    token_usage: dict[str, int] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    })
    tool_call_history: list[ToolCall] = field(default_factory=list)
    tool_result_history: list[ToolResult] = field(default_factory=list)

    @property
    def last_assistant_message(self) -> Optional[Message]:
        for msg in reversed(self.messages):
            if msg.role == Role.ASSISTANT:
                return msg
        return None
