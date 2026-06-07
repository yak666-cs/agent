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
    "  - web_search：推荐使用 ddg(DuckDuckGo) 源，中文本地搜索质量更好。\n"
    "    步骤：先搜索看结果摘要 → 如果摘要信息不足，从结果中选一个 URL 填入 read_content 参数 → 工具会打开该链接读取页面详细内容。\n"
    "    同一关键词最多搜 2 次。如果 2 次搜索后仍然找不到答案，直接告诉用户没找到，不要再试。\n"
    "如果一次工具调用没有得到所需数据，换一种搜索方式或直接告知用户已有结果，不要用相同的关键词反复搜索。\n"
    "如果搜索后仍不确定答案，直接说「不知道」或「没找到」，不要编造信息。"
)

class ContextManager:
    """
    对话上下文管理器。

    核心策略（参考 Claude Code）：
    - 不设滑动窗口，不按关键词过滤
    - 保留全部对话历史，只在接近 200K 上限时裁剪
    - 裁剪时从中间删（保留最早轮次 + 最近 N 条），不破坏 tool_call 配对
    """

    def __init__(
        self,
        max_tokens: int = 200_000,
        reserve_tokens: int = 2_000,
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
        self.location_context: str = ""  # 持久化的位置信息，注入 system prompt 不会被裁剪
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
        构建发给 LLM 的消息列表（参考 Claude Code 策略）：

        1. 拼接 system prompt + skill prompt + 位置信息
        2. 前置 system message
        3. 超出 token 预算则从中间裁剪（保留最早 2 轮 + 最近 30 条）
        4. 修复可能残留的 tool_call ↔ tool_result 配对
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

        # 2b. 注入持久化位置信息（不会被后续裁剪/过滤影响）
        if self.location_context:
            full_prompt += f"\n\n{self.location_context}"

        # 3. 插入 system prompt
        if full_prompt and (
            not messages or messages[0].role != Role.SYSTEM
        ):
            messages.insert(0, Message(role=Role.SYSTEM, content=full_prompt))

        budget = self.max_tokens - self.reserve_tokens

        # 3. 预算裁剪：超过 200K 上限时从中间删（保留最早 2 轮 + 最近 30 条）
        if self.estimate_tokens(messages) > budget and len(messages) > 6:
            self._trim_middle(messages)

        # 4. 修复可能残留的不完整 tool_call <-> tool_result 配对
        messages = self.repair_tool_pairs(messages)

        return messages

    # ---- 预算裁剪（参考 Claude Code 中间裁剪策略） ----

    def _trim_middle(self, messages: list[Message]) -> None:
        """
        从中间删除一段完整对话轮次。

        策略（Claude Code 风格）：
        - 保留最早 2 轮用户 ↔ AI 交换
        - 保留最近 30 条消息
        - 删除中间部分
        - repair_tool_pairs 会修复被破坏的配对
        """
        # 找到第 2 个完整 USER 轮次的结束位置
        kept_exchanges = 0
        cut_start = None
        for i in range(1, len(messages)):
            if messages[i].role == Role.USER:
                kept_exchanges += 1
                if kept_exchanges == 2:
                    cut_start = i
                    break

        if cut_start is None:
            return

        # 从 cut_start 往前推，删到保留最近 N 条的前面
        keep_recent = 30
        cut_end = max(cut_start + 1, len(messages) - keep_recent)

        if cut_end <= cut_start + 2:
            return  # 中间没多少可删的

        n_deleted = cut_end - cut_start
        del messages[cut_start:cut_end]
        self.compression_log.append({
            "action": "trim_middle",
            "detail": f"中间裁剪: 删除了约 {n_deleted} 条中间消息，保留最早 2 轮 + 最近 {keep_recent} 条",
        })

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

        # 提取英文/数字词
        keywords = set(re.findall(r"[a-zA-Z0-9_]+", user_message))
        # 空格分词
        for token in user_message.lower().split():
            if len(token) >= 2:
                keywords.add(token)
        # 中文二元分词：把 "保利广场" 拆成 "保利"、"利广"、"广场"
        for i in range(len(user_message) - 1):
            chunk = user_message[i:i+2]
            if all('一' <= c <= '鿿' for c in chunk):
                keywords.add(chunk)

        if not keywords or len(user_message.strip()) < 4:
            return messages

        keep = messages[:1]  # system 始终保留

        # 保留最近 30 条，滑动窗口已经兜底了，这里不用裁太狠
        cutoff = max(1, len(messages) - 30)
        for msg in messages[1:cutoff]:
            content = (msg.content or "").lower()
            if any(kw.lower() in content for kw in keywords):
                keep.append(msg)

        # 最近 30 条全部保留
        for msg in messages[cutoff:]:
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
