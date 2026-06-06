"""Complex task planning skill."""

from skills.base import BaseSkill, SkillMeta


class TaskPlanningSkill(BaseSkill):
    """Guide the model to use a plan-first workflow for multi-step work."""

    def __init__(self):
        super().__init__(
            SkillMeta(
                name="task_planning",
                description="复杂任务规划与分解",
                scenarios=[
                    "复杂任务",
                    "分步骤",
                    "先",
                    "然后",
                    "最后",
                    "分析",
                    "报告",
                    "排查",
                    "调研",
                ],
            )
        )

    def get_prompt(self) -> str:
        return """
## Skill: 复杂任务规划
当用户请求涉及多个阶段、多个产物或多个子问题时，不要直接给结论，优先先形成执行骨架。

推荐流程：
1. 识别任务是否至少包含“收集信息 / 执行操作 / 分析判断 / 交付结果”中的两个以上阶段。
2. 如果任务明显复杂，优先调用 `subagent_delegate` 拆成多个子任务，并尽量标注依赖关系。
3. 子任务应尽量具体可执行，避免使用空泛标题；例如“收集系统信息”“分析瓶颈”“生成优化建议”比“处理任务”更好。
4. 当工具返回的数据不足以支撑结论时，继续补充采集，而不是提前结束。
5. 最终回答必须区分：
- 已完成的事实
- 基于事实的判断
- 仍缺失的信息或未完成的部分

对于带有“先…再…最后…”、“分析并报告”、“排查并给建议”、“调研后输出方案”等描述的请求，默认视为复杂任务。
"""
