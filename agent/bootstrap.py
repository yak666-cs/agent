"""
Shared agent capability bootstrap helpers.
"""

from skills.manager import skill_manager
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.memory import MemorySkill
from skills.builtin.subagent_delegation import SubagentDelegationSkill
from skills.builtin.system_debug import SystemDebugSkill
from skills.builtin.task_planning import TaskPlanningSkill
from tools.builtin.bash import BashTool
from tools.builtin.file_deleter import FileDeleterTool
from tools.builtin.file_reader import ReadFileTool
from tools.builtin.file_writer import WriteFileTool
from tools.builtin.ip_geolocation import IpGeolocationTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.process_manager import ProcessManagerTool
from tools.builtin.python_repl import PythonReplTool
from tools.builtin.read_document import ReadDocumentTool
from tools.builtin.subagent_tool import SubagentDelegateTool
from tools.builtin.system_info import SystemInfoTool
from tools.builtin.web_search import WebSearchTool
from tools.registry import tool_registry

from agent.subagent import SubagentDef, subagent_registry


def register_core_tools() -> None:
    """Register the full built-in toolset once."""
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(PythonReplTool())
    tool_registry.register(FileDeleterTool())
    tool_registry.register(SystemInfoTool())
    tool_registry.register(ProcessManagerTool())
    tool_registry.register(ReadDocumentTool())
    tool_registry.register(MemoryTool())
    tool_registry.register(IpGeolocationTool())


def register_core_skills() -> None:
    """Register the default reasoning skills once."""
    skill_manager.register(SystemDebugSkill())
    skill_manager.register(FileOpsSkill())
    skill_manager.register(DataAnalysisSkill())
    skill_manager.register(FileManageSkill())
    skill_manager.register(MemorySkill())
    skill_manager.register(SubagentDelegationSkill())
    skill_manager.register(TaskPlanningSkill())


def register_runtime_tools(
    *,
    llm,
    tool_executor,
    tool_selector,
    context_manager,
    event_cb=None,
) -> None:
    """Register tools that need live runtime dependencies."""
    tool_registry.register(
        SubagentDelegateTool(
            llm=llm,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            tool_selector=tool_selector,
            context_manager=context_manager,
            event_cb=event_cb,
        )
    )


def register_core_subagents() -> None:
    """注册预定义的子代理类型。"""
    subagent_registry.register(SubagentDef(
        name="code-auditor",
        description="代码审计专家，用于审查项目代码质量、架构一致性和潜在缺陷",
        prompt="""你是 KAI AGENT 项目的代码审计专家。

## 审计流程
1. 先用 Glob 获取项目目录结构
2. 按模块审查关键文件（agent/ → tools/ → harness/ → memory/ → 前端）
3. 核对文档与实际文件是否一致
4. 输出结构化报告，每个问题包含：文件路径、行号、严重程度（高/中/低）、改进建议

## 检查重点
- 代码规范：命名一致性、错误处理、类型注解
- 架构问题：循环依赖、职责划分
- 安全风险：硬编码密钥、命令注入
- 文档一致性：README 与实际实现是否匹配
- 重复代码：可提取的公共逻辑""",
        tools=["read_file", "web_search", "grep", "bash", "glob"],
        model="deepseek-chat",
        max_turns=15,
    ))
    subagent_registry.register(SubagentDef(
        name="security-reviewer",
        description="安全审查专家，检查认证缺陷、注入风险和数据泄露",
        prompt="""你是安全审查专家，专注于代码安全审计。

## 审查清单
1. 认证与授权：Token 存储、API 权限控制、密码哈希
2. 注入攻击：SQL 参数化、命令沙箱、输入校验
3. 敏感信息：硬编码密钥、日志泄漏、.gitignore
4. 文件操作：路径遍历、上传限制、临时文件清理

## 输出格式
每条问题包含：【严重程度】问题标题 — 文件路径 — 风险描述 — 修复建议""",
        tools=["read_file", "grep", "glob"],
        model="deepseek-chat",
        max_turns=10,
    ))
    subagent_registry.register(SubagentDef(
        name="test-analyzer",
        description="测试分析专家，检查测试覆盖率和缺失的测试用例",
        prompt="""你是测试分析专家。

## 分析流程
1. 列出所有测试文件，标注对应的被测模块
2. 找出缺少测试文件的模块
3. 评估测试质量：是否覆盖正常/异常路径，命名是否清晰
4. 尝试 pytest --collect-only 获取全部测试用例

## 输出格式
- 有测试的模块：module → tests/test_module.py（N 个用例）
- 缺少测试的模块：module — 无对应测试文件
- 改进建议""",
        tools=["read_file", "grep", "glob", "bash"],
        model="deepseek-chat",
        max_turns=10,
    ))
    subagent_registry.register(SubagentDef(
        name="task-planner",
        description="任务规划专家，将复杂需求分解为可并行执行的子任务",
        prompt="""你是任务规划专家。

## 分解原则
1. 识别独立任务 → 标记为可并行
2. 识别依赖链 → 标记为串行阶段
3. 估算每个子任务的工作量

## 输出格式
- 阶段 1（可并行）：任务 A / 任务 B
- 阶段 2（依赖阶段 1）：任务 C
- 建议的执行策略""",
        tools=["read_file", "grep", "glob"],
        model="deepseek-v4-flash",
        max_turns=8,
    ))
    subagent_registry.register(SubagentDef(
        name="code-explorer",
        description="快速代码搜索和阅读助手，查找文件、定位实现",
        prompt="""你是代码搜索专家。

1. 通过 Glob 查找文件
2. 通过 Grep 搜索关键词/符号
3. 阅读文件提取关键信息（类、函数签名、重要逻辑）
4. 返回结果时附带文件路径和行号""",
        tools=["glob", "grep", "read_file"],
        model="deepseek-chat",
        max_turns=6,
    ))
