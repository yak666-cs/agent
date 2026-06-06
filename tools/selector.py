"""
Tool selector with lightweight intent scoring.
"""

import re

from .base import BaseTool
from .registry import ToolRegistry


class ToolSelector:
    _COMPLEXITY_MARKERS = (
        "复杂",
        "分步骤",
        "多步骤",
        "多阶段",
        "多个",
        "先",
        "然后",
        "最后",
        "分析",
        "报告",
        "排查",
        "调研",
        "方案",
        "并且",
        "同时",
        "complex",
        "multi-step",
        "step by step",
        "analyze",
        "report",
        "investigate",
    )

    _TOOL_HINTS = {
        "bash": ("命令", "terminal", "shell", "bash", "powershell", "cmd"),
        "read_file": ("文件", "代码", "read", "open", "查看", "内容"),
        "write_file": ("写入", "保存", "create", "write", "生成文件", "修改文件"),
        "web_search": ("搜索", "联网", "查一下", "web", "google", "bing"),
        "python_repl": ("计算", "脚本", "python", "统计", "分析数据"),
        "file_deleter": ("删除", "remove", "cleanup", "清理文件"),
        "system_info": ("系统", "cpu", "内存", "磁盘", "网络", "性能"),
        "process_manager": ("进程", "pid", "tasklist", "占用", "资源", "kill"),
        "read_document": ("pdf", "word", "excel", "文档", "简历"),
        "memory": ("记住", "回忆", "memory", "记忆", "保存偏好"),
        "ip_geolocation": ("ip", "定位", "地理位置", "地址"),
        "subagent_delegate": (
            "复杂任务",
            "分解",
            "计划",
            "步骤",
            "报告",
            "分析",
            "并行",
            "多阶段",
        ),
    }

    def __init__(self, registry: ToolRegistry, top_k: int = 20):
        self.registry = registry
        self.top_k = top_k

    def filter_by_intent(self, user_message: str) -> list[BaseTool]:
        all_tools = self.registry.list_enabled()
        if len(all_tools) <= self.top_k:
            return all_tools

        message = (user_message or "").lower()
        terms = [term for term in re.split(r"[\s,.;:!?/\\\-_()\[\]{}]+", message) if term]
        is_complex = any(marker in message for marker in self._COMPLEXITY_MARKERS)

        scored: list[tuple[int, int, BaseTool]] = []
        for index, tool in enumerate(all_tools):
            score = self._score_tool(tool, message, terms, is_complex)
            scored.append((score, -index, tool))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [tool for score, _, tool in scored if score > 0][: self.top_k]

        if not selected:
            selected = [tool for _, _, tool in scored[: self.top_k]]

        if is_complex:
            subagent = self.registry.get("subagent_delegate")
            if subagent and subagent not in selected:
                selected = [subagent] + selected[: max(0, self.top_k - 1)]

        return selected

    def build_tools_for_llm(self, user_message: str) -> list[dict]:
        candidates = self.filter_by_intent(user_message)
        return [t.to_openai_tool() for t in candidates]

    def _score_tool(
        self,
        tool: BaseTool,
        message: str,
        terms: list[str],
        is_complex: bool,
    ) -> int:
        score = 0
        haystacks = [tool.name.lower(), tool.description.lower(), " ".join(tool.meta.tags).lower()]

        for hint in self._TOOL_HINTS.get(tool.name, ()):
            if hint.lower() in message:
                score += 8

        for term in terms:
            if any(term in haystack for haystack in haystacks):
                score += 3

        if tool.name == "subagent_delegate" and is_complex:
            score += 50
        elif is_complex and tool.name in {"read_file", "bash", "python_repl"}:
            score += 2

        return score
