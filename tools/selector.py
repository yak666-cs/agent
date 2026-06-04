"""
Tool 选择器 —— 根据用户意图筛选候选工具

和原来的 SkillSelector 一样，Hybrid 策略：
关键词过滤 → 候选集 → 发给 LLM 选
"""

import re
from .base import BaseTool
from .registry import ToolRegistry


class ToolSelector:
    def __init__(self, registry: ToolRegistry, top_k: int = 8):
        self.registry = registry
        self.top_k = top_k
        self._rules: list[tuple[str, list[str]]] = [
            (r"文件|读取|查看|cat |读|内容", ["read_file"]),
            (r"写入|保存|创建文件|写文件|新建", ["write_file"]),
            (r"命令|执行|运行|bash|shell|终端|cmd", ["bash"]),
            (r"搜索|查找|google|百度|搜一下|查一下|搜索", ["web_search"]),
            (r"代码|python|计算|运算|eval|公式|统计", ["python_repl"]),
            (r"进程|CPU|内存|top|ps|tasklist", ["bash"]),
            (r"端口|netstat|lsof|网络|ipconfig|ping", ["bash"]),
            (r"磁盘|空间|分区|容量|硬盘|du|df|wmic", ["bash"]),
            (r"目录|文件夹|文件列表|ls|dir", ["bash"]),
            (r"curl|http|api|请求|下载", ["web_search", "bash"]),
        ]

    def filter_by_intent(self, user_message: str) -> list[BaseTool]:
        # 不预过滤，把所有工具发给 LLM，让 LLM 自行选择
        all_tools = self.registry.list_enabled()
        return all_tools[:self.top_k]

    def build_tools_for_llm(self, user_message: str) -> list[dict]:
        candidates = self.filter_by_intent(user_message)
        return [t.to_openai_tool() for t in candidates]
