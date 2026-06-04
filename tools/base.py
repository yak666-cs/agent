"""
Tool 基类 —— 可执行的原语

Tool 是 Agent 能力的最小单元，有具体的执行代码。
LLM 通过 tool_call 机制选中 Tool、填入参数、获取结果。

相当于 Claude Code 的"内置能力"（bash、读文件、写文件等）。
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class Permission(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    SHELL = "shell"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"


@dataclass
class ToolMeta:
    name: str
    description: str
    permission: Permission = Permission.READ_ONLY
    requires_confirmation: bool = False
    timeout_seconds: float = 30.0
    cache_ttl: float = 0.0
    tags: list[str] = field(default_factory=list)


class BaseTool(ABC):
    """所有 Tool 的抽象基类 ——— 有执行代码"""

    def __init__(self, meta: ToolMeta):
        self.meta = meta

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def description(self) -> str:
        return self.meta.description

    @abstractmethod
    def parameters_schema(self) -> dict:
        """JSON Schema 格式的参数定义"""

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """真正的执行逻辑"""

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            }
        }
