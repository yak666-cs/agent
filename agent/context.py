"""
上下文管理 —— 对话历史的组织与裁剪

harness 的核心职责之一：如何在有限上下文窗口中装入最有价值的信息。

几个设计决策：
1. System Prompt 固定在最前面，不会被裁剪
2. 裁剪策略：保留最近 N 条消息 + 最早的 system prompt
3. 工具输出截断已在 executor 层做了一次，这里做二次兜底
4. 当上下文接近窗口上限时，自动压缩中间的旧消息
"""

from .types import Message, Role


class ContextManager:
    """
    对话上下文管理器。

    可以传入 skill_prompt（由 SkillManager 生成），
    会自动拼接到 system_prompt 末尾注入给 LLM。
    """

    def __init__(
        self,
        max_tokens: int = 128_000,
        reserve_tokens: int = 4_000,
        system_prompt: str = "",
        skill_prompt: str = "",
    ):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.system_prompt = system_prompt
        self.skill_prompt = skill_prompt

    def estimate_tokens(self, messages: list[Message]) -> int:
        total = 0
        for msg in messages:
            total += 4 + len(msg.content) // 2
        return total

    def build_messages(self, history: list[Message]) -> list[Message]:
        """
        构建发给 LLM 的消息列表：
        1. 拼接 system prompt + skill prompt
        2. 前置 system message
        3. 超出 token 预算则裁剪
        """
        messages = list(history)

        # 1. 拼出完整的 system prompt = 基础部分 + Skill 提示词
        full_prompt = self.system_prompt
        if self.skill_prompt:
            full_prompt += f"\n\n{self.skill_prompt}"

        # 2. 插入 system prompt
        if full_prompt and (
            not messages or messages[0].role != Role.SYSTEM
        ):
            messages.insert(0, Message(role=Role.SYSTEM, content=full_prompt))

        # 2. 裁剪（从旧到新保留）
        budget = self.max_tokens - self.reserve_tokens
        while self.estimate_tokens(messages) > budget and len(messages) > 3:
            # 保留 system prompt（index 0）和最后 2 条，从中间删
            if messages[1].role == Role.TOOL:
                # 工具结果不能独立存在 —— 和前一条配对删除
                del messages[2]
                del messages[1]
            else:
                del messages[1]

        return messages

    def compress_history(self, messages: list[Message]) -> list[Message]:
        """
        更智能的压缩：对旧消息做摘要而非简单删除。
        当前是简化版 —— 只做截断，摘要功能留给扩展。
        """
        return self.build_messages(messages)


# 预定义的 System Prompt 模板
DEFAULT_SYSTEM_PROMPT = """你是一个运行在用户 Windows 电脑上的智能助手，可以调用工具来完成实际任务。

## 你的能力
你可以使用以下工具来帮助用户：
- **bash**: 在电脑上执行命令（查看文件、查看进程、磁盘空间、网络状态等）
  *注意：用户是 Windows 系统，优先使用 dir、tasklist、systeminfo、ipconfig 等 Windows 命令*
- **read_file**: 读取文件内容。路径可以是相对于项目根目录的相对路径，例如 "skills/builtin/bash.py"
- **write_file**: 创建或修改文件
- **web_search**: 搜索互联网
- **python_repl**: 运行 Python 代码做计算或数据处理

## 工作方式
1. 理解用户的需求，判断需要用到哪些工具
2. 调用工具获取真实结果（不要编造）
3. 如果一次工具调用不够，继续调用直到拿到足够信息
4. 最后用清晰的中文总结答案

## 重要规则
- 不要猜测命令输出或文件内容，必须真正调用工具
- 优先使用只读命令（dir、type、tasklist、systeminfo 等）
- 永远不要执行 format、del /f /s、rmdir /s /q 等破坏性命令
- **删除流程：先查看文件是否存在和内容，然后直接调 file_deleter 工具，确认由系统负责，不要在文字里问用户"是否确认"**
- **如果用户让你读文件，直接把文件内容原文展示出来，不要总结。**
- **如果用户让你执行命令，直接展示命令的原始输出，不要加工。**
- 回复简洁直接，用户是来解决问题的
"""
