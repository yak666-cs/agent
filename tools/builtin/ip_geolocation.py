"""IP 地理定位 Tool —— 通过 IP 地址获取粗略位置"""

import httpx
from tools.base import BaseTool, ToolMeta, Permission


def _ipv4_client() -> httpx.AsyncClient:
    """强制 IPv4 的 HTTPX 客户端，避免 IPv6 隧道导致定位到国外。"""
    transport = httpx.AsyncHTTPTransport(
        local_address="0.0.0.0",
    )
    return httpx.AsyncClient(transport=transport, timeout=8.0)


class IpGeolocationTool(BaseTool):
    def __init__(self):
        super().__init__(ToolMeta(
            name="ip_geolocation",
            description="获取当前设备的大致地理位置（城市、省份）。用于天气查询、本地服务等场景。注意：此工具每轮对话只需调用一次，返回的位置信息在整个对话中持续有效，无需重复获取。获取城市后如需天气数据请使用 web_search 的 ddg 源搜索城市天气，从结果中选择链接填入 read_content 参数查看详情",
            permission=Permission.READ_ONLY,
            timeout_seconds=10.0,
            cache_ttl=300.0,
            tags=["network", "location"],
        ))

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self) -> str:
        # 主选: api.ip.sb/geoip
        result = await self._try_ip_sb()
        if result:
            return result

        # 备选1: ip-api.com
        result = await self._try_ip_api()
        if result:
            return result

        # 备选2: ipinfo.io
        result = await self._try_ipinfo()
        if result:
            return result

        return "(定位失败: 所有 IP 数据源均不可用)"

    async def _try_ip_sb(self) -> str | None:
        try:
            async with _ipv4_client() as client:
                resp = await client.get("https://api.ip.sb/geoip")
                resp.raise_for_status()
                data = resp.json()
            return (
                f"IP 地址: {data.get('ip', 'N/A')}\n"
                f"位置: {data.get('city', 'N/A')}, {data.get('region', 'N/A')}, {data.get('country', 'N/A')}\n"
                f"运营商: {data.get('isp', '未知')}"
            )
        except Exception:
            return None

    async def _try_ip_api(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("http://ip-api.com/json/?lang=zh-CN")
                resp.raise_for_status()
                data = resp.json()
            if data.get("status") == "success":
                return (
                    f"IP 地址: {data.get('query', 'N/A')}\n"
                    f"位置: {data.get('city', 'N/A')}, {data.get('regionName', 'N/A')}, {data.get('country', 'N/A')}\n"
                    f"运营商: {data.get('isp', '未知')}"
                )
        except Exception:
            pass
        return None

    async def _try_ipinfo(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://ipinfo.io/json")
                resp.raise_for_status()
                data = resp.json()
            return (
                f"IP 地址: {data.get('ip', 'N/A')}\n"
                f"位置: {data.get('city', 'N/A')}, {data.get('region', 'N/A')}, {data.get('country', 'N/A')}"
            )
        except Exception:
            return None
