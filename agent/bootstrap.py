"""
Shared agent capability bootstrap helpers.
"""

from skills.manager import skill_manager
from skills.builtin.data_analysis import DataAnalysisSkill
from skills.builtin.file_manage import FileManageSkill
from skills.builtin.file_ops import FileOpsSkill
from skills.builtin.memory import MemorySkill
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
