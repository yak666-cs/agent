"""
上下文管理 —— 对话历史的组织与裁剪

harness 的核心职责之一：如何在有限上下文窗口中装入最有价值的信息。

几个设计决策：
1. System Prompt 固定在最前面，不会被裁剪
2. 裁剪策略：保留最近 N 条消息 + 最早的 system prompt
3. 工具输出截断已在 executor 层做了一次，这里做二次兜底
4. 当上下文接近窗口上限时，自动压缩中间的旧消息
"""

import re

from .types import Message, Role

DEFAULT_SYSTEM_PROMPT = (
    "你是 Kai Agent，一个基于 DeepSeek 的桌面 AI 助手。"
    "你拥有执行系统命令、读写文件、搜索互联网等能力。"
    "对于用户的每个需求，请选择最合适的工具来完成任务。"
    "如果工具调用失败，尝试换一种方式或向用户说明原因。"
    "请始终保持简洁、准确的回答。"
    "For tasks that create, write, edit, delete, read, list, run, or otherwise change/check external state, "
    "you must call the appropriate tool and base the final answer on the tool result. "
    "Never claim that a file was created, written, modified, deleted, or checked unless the matching tool call succeeded. "
    "不要重复调用工具。同一工具在同一轮对话中只应调用一次。\n"
    "  - ip_geolocation：每轮对话只调用一次，第一次返回的位置信息在整个对话中有效，不要重复获取。\n"
    "  - web_search：搜索天气时 web_search 会从搜索结果中的天气网站提取温度数据，无需额外工具。\n"
    "如果一次工具调用没有得到所需数据，换一种搜索方式或直接告知用户已有结果，不要用相同的关键词反复搜索。"
)

class ContextManager:
    """
    对话上下文管理器。

    支持三种高级上下文工程策略：
    - 滑动窗口（window_size）：限制消息条数，超出的从旧到新丢弃
    - 历史摘要（enable_summary）：把旧对话压缩成摘要而非直接删除
    - 相关性裁剪（enable_relevance）：保留与当前问题关键词匹配的消息
    """

    def __init__(
        self,
        max_tokens: int = 128_000,
        reserve_tokens: int = 4_000,
        system_prompt: str = "",
        skill_prompt: str = "",
        window_size: int = 0,
        enable_summary: bool = False,
        enable_relevance: bool = False,
    ):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.system_prompt = system_prompt
        self.skill_prompt = skill_prompt
        self.window_size = window_size
        self.enable_summary = enable_summary
        self.enable_relevance = enable_relevance
        self.compression_log: list[dict] = []  # 记录每次压缩/裁剪操作

    def estimate_tokens(self, messages: list[Message]) -> int:
        total = 0
        for msg in messages:
            total += 4 + len(msg.content) // 2
        return total

    def build_messages(
        self, history: list[Message], user_message: str = ""
    ) -> list[Message]:
        """
        构建发给 LLM 的消息列表：
        1. 拼接 system prompt + skill prompt
        2. 前置 system message
        3. 滑动窗口（如启用）
        4. 超出 token 预算则裁剪（带摘要或直接删）
        5. 按相关性过滤（如启用）
        """
        messages = list(history)

        # 1. 拼出完整的 system prompt = 基础部分 + Skill 提示词
        full_prompt = self.system_prompt
        if self.skill_prompt:
            full_prompt += f"\n\n{self.skill_prompt}"

        # 2. 注入当前日期
        from datetime import date
        today = date.today()
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        date_str = f"今天是 {today.year}年{today.month}月{today.day}日 星期{weekdays[today.weekday()]}"
        full_prompt = f"{date_str}\n\n{full_prompt}"

        # 3. 插入 system prompt
        if full_prompt and (
            not messages or messages[0].role != Role.SYSTEM
        ):
            messages.insert(0, Message(role=Role.SYSTEM, content=full_prompt))

        budget = self.max_tokens - self.reserve_tokens

        # 3. 滑动窗口：限制消息条数
        if self.window_size > 0:
            self._apply_window(messages)

        # 4. 预算裁剪（带摘要或直接删）
        while self.estimate_tokens(messages) > budget and len(messages) > 3:
            if self.enable_summary:
                self._summarize_oldest(messages)
            else:
                self._trim_oldest_safe(messages)

        # 5. 按相关性过滤
        if self.enable_relevance and user_message:
            messages = self._filter_by_relevance(messages, user_message)

        # 6. 修复可能残留的不完整 tool_call <-> tool_result 配对
        messages = self.repair_tool_pairs(messages)

        return messages

    # ---- 滑动窗口 ----

    def _apply_window(self, messages: list[Message]) -> None:
        """滑动窗口：消息数超过 window_size 时，从旧到新删除到 window_size 以内。"""
        while len(messages) > self.window_size + 1 and len(messages) > 3:
            self._trim_oldest_safe(messages)

    # ---- 预算裁剪 ----

    def _trim_oldest_safe(self, messages: list[Message]) -> None:
        """安全删除最早一段完整会话单元，确保 ASSISTANT(tc) <-> TOOL 配对不被破坏。"""
        if messages[1].role == Role.ASSISTANT and messages[1].tool_calls:
            j = 2
            while j < len(messages) and messages[j].role == Role.TOOL:
                j += 1
            summary = f"裁剪: {messages[1].content or '(工具调用)'} 等 {j-1} 条消息"
            del messages[1:j]
        else:
            summary = f"裁剪: {messages[1].content[:60] if messages[1].content else '(空)'}"
            del messages[1]
        self.compression_log.append({"action": "trim", "detail": summary})

    # ---- 历史摘要 ----

    def _summarize_oldest(self, messages: list[Message]) -> None:
        """
        把最早的一段完整对话轮次压缩成一条摘要 USER 消息。

        能处理两种轮次：
        - 简单问答：USER -> ASSISTANT(no tc)
        - 工具调用：USER -> ASSISTANT(tc) -> TOOLs -> ASSISTANT(reply)
        压缩后替换原来的 USER 消息，删除后续所有相关消息。
        """
        for i in range(1, len(messages)):
            if messages[i].role != Role.USER:
                continue

            user_text = messages[i].content[:200]

            # 找到第一个非 TOOL 消息
            j = i + 1
            while j < len(messages) and messages[j].role == Role.TOOL:
                j += 1

            if j >= len(messages) or messages[j].role != Role.ASSISTANT:
                continue

            if messages[j].tool_calls:
                # 工具调用轮次：USER -> ASSISTANT(tc) -> TOOLs -> ASSISTANT(reply)
                k = j + 1
                while k < len(messages) and messages[k].role == Role.TOOL:
                    k += 1
                if k < len(messages) and messages[k].role == Role.ASSISTANT and not messages[k].tool_calls:
                    reply_text = messages[k].content[:400] if messages[k].content else "(工具结果已省略)"
                    summary = f"[历史摘要] 用户: {user_text} → AI: {reply_text}"
                    messages[i] = Message(role=Role.USER, content=summary)
                    del messages[i + 1:k + 1]
                    self.compression_log.append({"action": "summary", "detail": summary})
                    return
            else:
                # 简单问答轮次：USER -> ASSISTANT(no tc)
                reply_text = messages[j].content[:400] if messages[j].content else ""
                summary = f"[历史摘要] 用户: {user_text} → AI: {reply_text}"
                messages[i] = Message(role=Role.USER, content=summary)
                del messages[i + 1:j + 1]
                self.compression_log.append({"action": "summary", "detail": summary})
                return

        # 没有可压缩的轮次，回退到安全删除
        self._trim_oldest_safe(messages)

    # ---- 相关性过滤 ----

    @staticmethod
    def _filter_by_relevance(
        messages: list[Message], user_message: str
    ) -> list[Message]:
        """
        按关键词匹配保留与当前问题相关的消息。

        策略：
        - System prompt 始终保留
        - 从用户问题中提取英文词 (CPU, API, Python 等) 作为关键词
        - 同时保留按空格分词后的 token
        - 中间消息：内容包含任意关键词的保留
        - 最后 2 条消息始终保留（最新对话上下文）
        - 关键词为空或查询过短时跳过过滤
        """
        if len(messages) <= 3:
            return messages

        # 提取英文/数字词 (处理 "CPU是什么"、"Python 代码" 等混合查询)
        keywords = set(re.findall(r"[a-zA-Z0-9_]+", user_message))
        # 空格分词（主要处理英文查询）
        for token in user_message.lower().split():
            if len(token) >= 2:
                keywords.add(token)

        if not keywords or len(user_message.strip()) < 4:
            return messages

        keep = messages[:1]  # system 始终保留

        for msg in messages[1:-2]:
            content = (msg.content or "").lower()
            if any(kw.lower() in content for kw in keywords):
                keep.append(msg)

        # 最后 2 条始终保留，避免重复
        for msg in messages[-2:]:
            if msg not in keep:
                keep.append(msg)

        return keep if len(keep) >= 3 else messages

    # ---- 配对修复 ----

    @staticmethod
    def repair_tool_pairs(messages: list[Message]) -> list[Message]:
        """
        修复 tool_call <-> tool_result 配对完整性。

        遍历消息列表，移除：
        - 缺少对应 TOOL 结果的 ASSISTANT(tc)
        - 缺少对应 ASSISTANT(tc) 的孤儿 TOOL
        - 多余的 TOOL 结果
        """
        result: list[Message] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                tc_ids = {tc.get("id", "") for tc in msg.tool_calls}
                j = i + 1
                found: list[Message] = []
                matched: set[str] = set()
                while j < len(messages) and messages[j].role == Role.TOOL:
                    tid = messages[j].tool_call_id
                    if tid in tc_ids and tid not in matched:
                        found.append(messages[j])
                        matched.add(tid)
                    j += 1

                if tc_ids and tc_ids == matched:
                    result.append(msg)
                    result.extend(found)
                    i = j
                else:
                    i = j
            elif msg.role == Role.TOOL:
                i += 1
            else:
                result.append(msg)
                i += 1

        return result

    def compress_history(self, messages: list[Message]) -> list[Message]:
        return self.build_messages(messages)
