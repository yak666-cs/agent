"""子代理委派 Skill —— 指导 LLM 何时使用 subagent_delegate"""

from skills.base import BaseSkill, SkillMeta


class SubagentDelegationSkill(BaseSkill):
    """指导 LLM 将复杂多任务分解为子代理并行执行"""

    def __init__(self):
        super().__init__(SkillMeta(
            name="subagent_delegation",
            description="复杂多任务分解、并行子代理执行",
            scenarios=["审计", "审查", "同时", "多个", "并行", "批量", "多维度", "汇总"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 子代理委派规则（必须遵守）

当你收到包含 3 个或以上独立子任务的复杂请求时，**必须使用 subagent_delegate 工具**分解任务并行执行，不要自己串行做。

### 必须使用 subagent_delegate 的场景：
1. **多维度审计/审查**：代码审计 + 安全审查 + 测试分析 + 文档检查（传入 subagent_type）
2. **同时查多个系统指标**：CPU + 内存 + 磁盘 + 网络 + 进程
3. **批量文件操作**：同时搜索/读取/分析多个文件
4. **多维度分析报告**：需要从不同角度分析同一份数据
5. **搜索多个信息源**：同时查多个关键词或网站

### 使用方式：
- 有明确领域的任务（审计/安全/测试） → 设置 subagent_type 为对应类型
- 通用并行任务 → 不填 subagent_type，让工具自动分解
- 子任务间有依赖 → 设置 mode="mixed" 或 mode="sequential"
- 所有子任务独立 → 设置 mode="parallel"

### 可用 subagent_type：
- code-auditor：代码审计
- security-reviewer：安全审查
- test-analyzer：测试分析
- task-planner：任务规划
- code-explorer：代码搜索

**禁止**：不要用 bash 或 read_file 串行执行独立子任务，必须用 subagent_delegate 并行处理。
"""
