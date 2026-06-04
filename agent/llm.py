"""
LLM 调用封装 —— 默认使用 DeepSeek API

DeepSeek 的 API 完全兼容 OpenAI 格式，只需改 base_url 和 model。
如果你以后想换其他模型（GPT-4o、Claude 等），只需改环境变量即可。

设计取舍：
- 直接用 httpx 调 REST API，不依赖 openai SDK
- 每次调用记录 token 用量
"""

import json
import os
from dataclasses import dataclass
from typing import Optional
import httpx

from .types import Message, ToolCall


@dataclass
class LLMResponse:
    """LLM 返回的统一结构"""
    content: Optional[str]        # 纯文本回复（没调工具时）
    tool_calls: list[ToolCall]    # 工具调用列表（调工具时）
    finish_reason: str            # "stop" | "tool_calls" | "length" | "error"
    usage: dict[str, int]         # token 用量


class LLMClient:
    """
    LLM 客户端，默认连接 DeepSeek API。

    只需要一个环境变量就能跑：
        export DEEPSEEK_API_KEY=sk-xxx

    换成其他模型也很简单：
        export LLM_API_KEY=sk-xxx
        export LLM_BASE_URL=https://api.openai.com/v1
        export LLM_MODEL=gpt-4o
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
    ):
        # 自动检测：有 DEEPSEEK_API_KEY 就用 DeepSeek
        self.api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY", "")
        )
        self.base_url = (
            (base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"))
        ).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-v4-flash")

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        发送 chat completion 请求。

        参数:
            messages: 完整的对话历史
            tools: 可用的工具定义列表（OpenAI format）
            temperature: 创造性控制（Agent 场景建议低温度以保证一致性）
            max_tokens: 最大输出 token
        """
        url = f"{self.base_url}/chat/completions"

        body = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 自动检测系统代理（Windows 环境变量）
        import urllib.request
        proxies = {}
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http_proxy:
            proxies["http://"] = http_proxy
        if https_proxy:
            proxies["https://"] = https_proxy

        async with httpx.AsyncClient(timeout=120.0, proxy=proxies.get("https://") or proxies.get("http://")) as client:
            try:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code != 200:
                    error_detail = resp.text[:500]
                    return LLMResponse(
                        content=f"(API 错误 {resp.status_code}) {error_detail}",
                        tool_calls=[],
                        finish_reason="error",
                        usage={},
                    )
                data = resp.json()
            except httpx.ConnectError as e:
                return LLMResponse(
                    content=f"(连接失败) 无法连接到 {self.base_url}。"
                            f"请检查网络和代理设置。详情: {e}",
                    tool_calls=[],
                    finish_reason="error",
                    usage={},
                )
            except httpx.TimeoutException:
                return LLMResponse(
                    content=f"(请求超时) 连接 {self.base_url} 超时，请检查网络或代理",
                    tool_calls=[],
                    finish_reason="error",
                    usage={},
                )
            except Exception as e:
                return LLMResponse(
                    content=f"(网络错误) {type(e).__name__}: {e}",
                    tool_calls=[],
                    finish_reason="error",
                    usage={},
                )

        choice = data["choices"][0]
        message = choice["message"]
        finish = choice.get("finish_reason", "stop")
        usage = data.get("usage", {})

        # 解析 tool_calls
        tool_calls = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            try:
                tool_calls.append(ToolCall.from_dict(tc))
            except (json.JSONDecodeError, KeyError) as e:
                # 单个 tool_call 解析失败不阻塞整体
                continue

        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=finish,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )
