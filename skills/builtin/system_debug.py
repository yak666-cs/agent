"""系统调试 Skill —— 纯提示词，无代码"""

from skills.base import BaseSkill, SkillMeta


class SystemDebugSkill(BaseSkill):
    """指导 LLM 如何处理系统调试类问题"""

    def __init__(self):
        super().__init__(SkillMeta(
            name="system_debug",
            description="系统信息排查（CPU、内存、磁盘、端口、网络）",
            scenarios=["CPU", "内存", "磁盘", "端口", "进程", "系统"],
        ))

    def get_prompt(self) -> str:
        return """
## Skill: 系统排查
当用户询问系统状态相关问题（CPU、内存、磁盘、端口、进程）时：
1. 直接调用 bash 执行对应的系统命令获取真实数据
2. 分析输出，提取关键信息（如使用率最高的进程、剩余空间等）
3. 如果数据不够，继续调命令补充
4. 最后用表格或清晰的中文总结，给出判断和建议

## Skill: CPU / 内存占用排查
当用户要求排查 CPU 或内存占用时：
1. 先用 process_manager 工具列出进程（action=list），或用 bash 执行 tasklist 命令
2. 输出通常很长，只关注前 10-15 个最占资源的进程
3. 对每个高占用进程，解释它的身份（系统进程/浏览器/IDE/后台服务等）
4. 给出判断：哪些正常、哪些可疑、哪些建议关闭
5. 如果用户想关闭进程，引导用户确认后再使用 process_manager 的 kill 操作

## Skill: 磁盘空间诊断与清理
当用户报告磁盘空间不足或要求查看磁盘时：
1. 先查看磁盘概况：bash `wmic logicaldisk get caption,description,freespace,size` 或 `system_info` 工具
2. 如果有分区快满了，定位具体目录：
   - 使用 bash `dir /s /a "C:\\Users\\用户名\\AppData"` 或按需逐层排查
   - 每次只查一级目录，避免 du/dir 长时间无输出
3. 如果命令可能很长时间（扫描全盘），先提示用户并询问是否继续
4. 给出清理建议：临时文件、回收站、Windows 更新缓存、包管理器缓存等
5. 涉及删除操作（del/rm/rd）必须先列出要删的内容，等待用户明确确认后再执行
6. 安全的清理路径（用户确认后可执行）：
   - `del /q /f %temp%\\*` — 临时文件
   - `cleanmgr /sageset:1` — 磁盘清理（仅打开界面）
   - npm/pip 缓存清理（如果存在）
7. 任何涉及删除的危险操作必须用户二次确认
"""

    def get_scenarios(self) -> list[str]:
        return ["CPU", "内存", "磁盘", "端口", "进程", "系统", "排查", "清理", "空间"]
