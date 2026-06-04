"""
Skill 基类 —— 纯提示词，无执行代码

Skill 是一段注入 System Prompt 的文本，指导 LLM 如何组合 Tool 完成特定场景的任务。

和 Tool 的区别：
- Tool: 有 execute() 执行代码，能被 LLM 通过 tool_call 选中
- Skill: 只有 prompt 文本，注入 System Prompt，LLM 靠它知道"什么时候该用什么 Tool"

相当于 Claude Code 里用户自定义的那些 Skill 文件。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SkillMeta:
    name: str
    description: str
    scenarios: list[str] = field(default_factory=list)


class BaseSkill(ABC):
    """Skill = 纯提示词"""

    def __init__(self, meta: SkillMeta):
        self.meta = meta

    @property
    def name(self) -> str:
        return self.meta.name

    @abstractmethod
    def get_prompt(self) -> str:
        """返回要注入 System Prompt 的文本"""
