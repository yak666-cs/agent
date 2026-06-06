from tools.base import BaseTool, ToolMeta, Permission
import requests
from bs4 import BeautifulSoup


class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="web_search",
            description='搜索互联网信息。适用于：查找最新资讯、技术文档、新闻、天气预报等。'
                        '注意：百度搜索 source="baidu" 当前不可用，请优先使用 source="bing" 或 source="all" 进行搜素。'
                        'source="all" 时，百度会返回实时热搜榜（仅热点/新闻类查询有效），Bing 正常返回搜索结果。'
                        '如果一次搜索没有得到需要的结果，换不同的关键词再试，不要用完全相同的关键词反复搜索。'
                        '对于天气/温度查询，web_search 会自动从搜索结果的天气网站提取实时温度数据。',
            permission=Permission.NETWORK,
            requires_confirmation=False,
            timeout_seconds=20.0,
            cache_ttl=60.0,
            tags=["network", "search"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    'description': '搜索关键词，尽量简洁明确。天气查询时 web_search 会自动从天气网站提取实时温度。',
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
                bing_results = ""
                parts.append(f"【Bing搜索】失败: {e}")

        # 天气查询：从 Bing 结果中找到 weather.com.cn 链接并提取实时温度
        if source in ("bing", "all") and bing_results:
            weather_data = self._extract_weather_from_bing(bing_results, query)
            if weather_data:
                parts.append(f"【天气数据（来自 weather.com.cn）】\n{weather_data}")

        return "\n\n".join(parts) if parts else "(搜索无搜索，请换关键词重试)"

    # ─── 百度热搜榜（替代被屏蔽的百度搜索）───

    def _search_baidu(self, query: str, num: int) -> str:
        """百度搜索已被封禁，改用百度热搜榜。仅对热点/新闻类查询返回结果。"""
        # 只有查询涉及热点/新闻/热搜时才返回热搜榜
        hot_keywords = {"热搜", "热点", "新闻", "今日", " trending", "hot", "news", "头条"}
        if not any(k in query.lower() for k in hot_keywords):
            return "(百度搜索当前不可用，请使用 Bing 搜索)"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            resp = requests.get(
                "https://top.baidu.com/board?tab=realtime",
                headers=headers,
                timeout=10,
            )
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            items = []
            for el in soup.select('[class*="title"]'):
                t = el.get_text(strip=True)
                if len(t) > 2 and t not in ("热搜榜", "热搜"):
                    items.append(f"• {t}")
            if items:
                return "\n".join(items[:num + 5]) + "\n\n更多热搜请访问: https://top.baidu.com/board?tab=realtime"
            return "(百度热搜暂未获取到数据)"
        except Exception as e:
            return f"(百度热搜获取失败: {e})"

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

    # ─── 天气提取（从 Bing 结果的 weather.com.cn 链接）───

    _WEATHER_KEYWORDS = {"天气", "温度", "气温", "weather", "temperature", "forecast",
                         "下雨", "晴天", "阴天", "多云", "雨", "雪", "风", "台风", "湿热"}

    def _extract_weather_from_bing(self, bing_text: str, query: str) -> str | None:
        """从 Bing 搜索结果中找到 weather.com.cn 链接，提取实时温度。"""
        # 只有查询涉及天气才触发
        if not any(k in query for k in self._WEATHER_KEYWORDS):
            return None

        # 从结果文本中提取 weather.com.cn URL
        import re
        urls = re.findall(r'https?://(?:www\.)?weather\.com\.cn\S+', bing_text)
        # 过滤出具体的天气页面（不是首页）
        weather_urls = [u for u in urls if "/weather/" in u or "/city/" in u or "/province/" in u]
        if not weather_urls:
            return None

        target_url = weather_urls[0].rstrip('.')
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        try:
            resp = requests.get(target_url, headers=headers, timeout=8)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            tem_el = soup.select_one("p.tem")
            wea_el = soup.select_one("p.wea")
            win_el = soup.select_one("p.win")

            parts = []
            if tem_el:
                parts.append(f"温度: {tem_el.get_text(strip=True)}")
            if wea_el:
                parts.append(f"天气: {wea_el.get_text(strip=True)}")
            if win_el:
                parts.append(f"风力: {win_el.get_text(strip=True)}")

            if parts:
                return "\n".join(parts)
        except Exception:
            pass

        return None
