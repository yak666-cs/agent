from tools.base import BaseTool, ToolMeta, Permission
import requests
from bs4 import BeautifulSoup


class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="web_search",
            description="搜索互联网信息（同时搜索百度 + Bing）。适用于：查找最新资讯、技术文档、天气预报、新闻等。",
            permission=Permission.NETWORK,
            requires_confirmation=False,
            timeout_seconds=15.0,
            cache_ttl=60.0,
            tags=["network", "search"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，尽量简洁明确",
                },
                "source": {
                    "type": "string",
                    "description": "搜索引擎：baidu（仅百度）、bing（仅Bing）、all（两个都搜，默认）",
                    "enum": ["baidu", "bing", "all"],
                    "default": "all",
                },
                "num_results": {
                    "type": "integer",
                    "description": "每个搜索引擎返回的结果数，1-10",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, source: str = "all", num_results: int = 5) -> str:
        num_results = max(1, min(num_results, 10))
        parts = []

        if source in ("baidu", "all"):
            try:
                baidu_results = self._search_baidu(query, num_results)
                parts.append(f"【百度搜索】\n{baidu_results}")
            except Exception as e:
                parts.append(f"【百度搜索】失败: {e}")

        if source in ("bing", "all"):
            try:
                bing_results = self._search_bing(query, num_results)
                parts.append(f"【Bing搜索】\n{bing_results}")
            except Exception as e:
                parts.append(f"【Bing搜索】失败: {e}")

        return "\n\n".join(parts) if parts else "(搜索无结果，请换关键词重试)"

    # ─── 百度 ───

    def _search_baidu(self, query: str, num: int) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(
            "https://www.baidu.com/s",
            params={"wd": query, "rn": num},
            headers=headers,
            timeout=10,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        items = []

        for div in soup.select("[class*='result'], [class*='c-container'], [class*='c-bottom'], .result-op"):
            if not div.select_one("h3"):
                continue
            title_el = div.select_one("h3")
            link_el = title_el.select_one("a") if title_el else None
            summary_el = (div.select_one(".c-abstract")
                         or div.select_one("[class*='content-right']")
                         or div.select_one(".c-span-last")
                         or div.select_one("[class*='c-color']"))

            title = title_el.get_text(strip=True) if title_el else ""
            link = link_el.get("href") if link_el and link_el.has_attr("href") else ""
            summary = summary_el.get_text(strip=True)[:200] if summary_el else ""

            if title:
                items.append(f"• {title}")
                if summary:
                    items.append(f"  {summary}")
                if link:
                    items.append(f"  {link}")
                items.append("")

        return "\n".join(items[:num * 3]) if items else "(百度未返回结果)"

    # ─── Bing ───

    def _search_bing(self, query: str, num: int) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": num},
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

            if title:
                items.append(f"• {title}")
                if summary:
                    items.append(f"  {summary}")
                if link:
                    items.append(f"  {link}")
                items.append("")

        return "\n".join(items[:num * 3]) if items else "(Bing未返回结果)"
