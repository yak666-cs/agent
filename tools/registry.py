"""
Tool 注册中心 —— 管理所有可执行工具的生命周期

等同于原来的 SkillRegistry，只是改名以区分 Skill（纯提示词）。
"""

from typing import Optional
from .base import BaseTool


class ToolRegistry:
    """单例，管理所有 Tool"""

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: dict[str, BaseTool] = {}
            cls._instance._enabled: set[str] = set()
        return cls._instance

    def register(self, tool: BaseTool, enabled: bool = True) -> None:
        self._tools[tool.name] = tool
        if enabled:
            self._enabled.add(tool.name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._enabled.discard(name)

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def enable(self, name: str) -> None:
        if name in self._tools:
            self._enabled.add(name)

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def list_enabled(self) -> list[BaseTool]:
        return [t for n, t in self._tools.items() if n in self._enabled]

    def list_all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_tools_for_llm(self) -> list[dict]:
        """生成传给 LLM 的 tools 参数（OpenAI format）"""
        return [t.to_openai_tool() for t in self.list_enabled()]

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def enabled_count(self) -> int:
        return len(self._enabled)


# 全局单例
tool_registry = ToolRegistry()
