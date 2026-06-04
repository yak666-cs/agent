"""长期记忆 Skill —— 纯提示词，无代码"""

from skills.base import BaseSkill, SkillMeta


class MemorySkill(BaseSkill):
    def __init__(self):
        super().__init__(SkillMeta(
            name="memory",
            description="长期记忆，跨会话持久化",
            scenarios=["记住", "回忆", "记忆", "忘记", "提醒"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 长期记忆
你有长期记忆能力，数据存在 F 盘 SQLite 数据库。注意以下规则：

### 什么时候该保存
- 用户告诉你个人信息（名字、职业、偏好等）
- 用户明确说"记住……"
- 项目相关的重要信息（路径、配置、关键决策）
- 你发现自己反复查询的相同信息

### 什么时候该回忆
- 用户说"还记得……吗"、"我之前说过……"
- 你觉得当前问题和过去信息相关

### 使用方式
- 用 memory 工具的 save action 保存，key 用英文短词，如 user_name、project_root
- 用 memory 工具的 recall action 按 key 回忆
- 用 memory 工具的 search action 模糊搜索
- 重要：每次对话开始时，系统会自动注入相关记忆到上下文中，但你也可以主动调用。
"""


    def get_scenarios(self) -> list[str]:
        return ["记住", "回忆", "记忆", "忘记", "提醒", "保存"]
