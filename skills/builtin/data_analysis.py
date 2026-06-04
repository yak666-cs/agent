"""数据处理 Skill —— 纯提示词，无代码"""

from skills.base import BaseSkill, SkillMeta


class DataAnalysisSkill(BaseSkill):
    """指导 LLM 如何处理数据分析类任务"""

    def __init__(self):
        super().__init__(SkillMeta(
            name="data_analysis",
            description="数据处理、计算、分析",
            scenarios=["计算", "统计", "分析", "数据", "代码"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 数据处理
当用户让你做计算或数据处理时：
1. 优先用 python_repl 执行 Python 代码（比 bash 更灵活）
2. bash 命令的输出如果是结构化的，可以用 python_repl 进一步处理
3. bash 和 python_repl 可以配合使用：bash 拿数据 → python 分析
"""
