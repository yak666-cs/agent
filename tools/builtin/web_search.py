from tools.base import BaseTool, ToolMeta, Permission
import requests
from bs4 import BeautifulSoup


class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="web_search",
            description='搜索互联网信息。适用于：查找最新资讯、技术文档、新闻、天气预报等。'
                        '搜索结果包含标题、摘要和来源链接。如果摘要信息不足，'
                        '可以将 read_content 设为某个结果的 URL，工具会打开该链接阅读页面详细内容。'
                        '先搜一次看结果摘要，再决定点哪个链接。'
                        '支持多个搜索引擎：ddg（DuckDuckGo，中文质量好）、bing、all（都搜）。'
                        '如果一次搜索没有得到需要的结果，换不同关键词再试，但同一关键词最多搜 2 次。',
            permission=Permission.NETWORK,
            requires_confirmation=False,
            timeout_seconds=25.0,
            cache_ttl=60.0,
            tags=["network", "search"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    'description': '搜索关键词，尽量简洁明确。搜本地信息时加城市名效果更好。',
                },
                "source": {
                    "type": "string",
                    "description": "搜索引擎：ddg（DuckDuckGo，推荐中文搜索）、bing（仅Bing）、all（两个都搜，默认）",
                    "enum": ["ddg", "bing", "all"],
                    "default": "all",
                },
                "num_results": {
                    "type": "integer",
                    "description": "每个搜索引擎返回的结果数，1-10",
                    "default": 5,
                },
                "read_content": {
                    "type": "string",
                    'description': '要读取详细内容的 URL。从搜索结果中选择一个链接填入即可。工具会打开该链接返回页面纯文本。留空则只返回搜索结果摘要。',
                    "default": "",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, source: str = "all", num_results: int = 5, read_content: str = "") -> str:
        num_results = max(1, min(num_results, 10))
        parts = []
        ddg_ok = False

        if source in ("ddg", "all"):
            try:
                ddg_results = self._search_ddg(query, num_results)
                parts.append(f"【DuckDuckGo搜索】\n{ddg_results}")
                ddg_ok = True
            except Exception as e:
                parts.append(f"【DuckDuckGo搜索】失败: {e}")

        if source in ("bing", "all"):
            try:
                bing_results = self._search_bing(query, num_results)
                parts.append(f"【Bing搜索】\n{bing_results}")
            except Exception as e:
                parts.append(f"【Bing搜索】失败: {e}")

        # 如果指定了 URL，读取该页面内容
        if read_content:
            page_text = self._read_url(read_content)
            if page_text:
                parts.append(f"【页面内容 - {read_content}】\n{page_text}")

        return "\n\n".join(parts) if parts else "(搜索无结果，请换关键词重试)"

    # ─── DuckDuckGo ───

    def _search_ddg(self, query: str, num: int) -> str:
        """使用 DuckDuckGo HTML 版搜索，中文质量比 Bing 好。"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=headers,
            timeout=10,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        items = []

        for result in soup.select(".result"):
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")

            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # 跳过百科类（太过宽泛的条目）
            skip_domains = ("baike.baidu.com", "baike.so.com", "m.baike.com")
            if link and any(d in link.lower() for d in skip_domains):
                continue

            if title:
                items.append(f"• {title}")
                if snippet:
                    items.append(f"  {snippet}")
                if link:
                    items.append(f"  {link}")
                items.append("")
                if len(items) >= num * 3:
                    break

        return "\n".join(items[:num * 3]) if items else "(DuckDuckGo未返回结果)"

    # ─── Bing ───

    _SKIP_DOMAINS = {"baike.baidu.com", "baike.so.com", "m.baike.com",
                      "wiki", "zhidao.baidu.com"}

    def _search_bing(self, query: str, num: int) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": num + 5},
            headers=headers,
            timeout=8,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        items = []

        for li in soup.select("#b_results > li.b_algo"):
            title_el = li.select_one("h2 a")
            summary_el = li.select_one(".b_caption p")

            title = title_el.get_text(strip=True) if title_el else ""
            link = title_el.get("href") if title_el and title_el.has_attr("href") else ""
            summary = summary_el.get_text(strip=True) if summary_el else ""

            if link and any(skip in link.lower() for skip in self._SKIP_DOMAINS):
                continue

            if title:
                items.append(f"• {title}")
                if summary:
                    items.append(f"  {summary}")
                if link:
                    items.append(f"  {link}")
                items.append("")
                if len(items) >= num * 3:
                    break

        return "\n".join(items[:num * 3]) if items else "(Bing未返回结果)"

    # ─── 读取指定 URL 内容 ───

    def _read_url(self, url: str) -> str | None:
        """打开指定 URL，提取纯文本内容（前 3000 字符）。"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            if len(text) > 3000:
                text = text[:3000] + "\n...(已截断)"
            return text
        except Exception as e:
            return f"(读取失败: {e})"
