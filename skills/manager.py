"""
Skill 管理器 —— 收集所有 Skill 的提示词，拼进 System Prompt
"""

from typing import Optional
from .base import BaseSkill


class SkillManager:
    """管理所有 Skill 提示词，生成注入 System Prompt 的文本"""

    _instance: Optional["SkillManager"] = None

    def __new__(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills: dict[str, BaseSkill] = {}
            cls._instance._enabled: set[str] = set()
        return cls._instance

    def register(self, skill: BaseSkill, enabled: bool = True) -> None:
        self._skills[skill.name] = skill
        if enabled:
            self._enabled.add(skill.name)

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)
        self._enabled.discard(name)

    def enable(self, name: str) -> None:
        if name in self._skills:
            self._enabled.add(name)

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def build_skill_prompt(self) -> str:
        """生成所有已启用 Skill 的提示词文本，拼成一段"""
        prompts = []
        for name in self._enabled:
            skill = self._skills.get(name)
            if skill:
                prompt = skill.get_prompt()
                if prompt:
                    prompts.append(prompt)
        if prompts:
            return "\n\n".join(prompts)
        return ""

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def enabled_count(self) -> int:
        return len(self._enabled)


# 全局单例
skill_manager = SkillManager()
