"""文件管理 Skill —— 纯提示词，指导 LLM 如何安全处理删除操作"""

from skills.base import BaseSkill, SkillMeta


class FileManageSkill(BaseSkill):
    def __init__(self):
        super().__init__(SkillMeta(
            name="file_manage",
            description="文件删除、清理等管理操作",
            scenarios=["删除", "删掉", "清理", "移除"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 文件管理
当用户让你删除文件时：
1. 先用 read_file 或 dir 确认文件存在
2. 直接调 file_deleter 工具执行删除，不要用文字问用户"是否确认"
3. 告知用户删除结果

注意：只删文件，不删目录。
"""
