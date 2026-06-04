"""快速诊断：检查 DeepSeek API 连接是否正常"""
import os
import httpx
import asyncio

async def main():
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    print(f"API Key 状态: {'已设置' if api_key else '❌ 未设置！'}")
    if api_key:
        print(f"  Key 前缀: {api_key[:8]}... (长度: {len(api_key)})")

    # 检查代理
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    print(f"代理设置:   {'已配置: ' + proxy if proxy else '无（直连）'}")

    if not api_key:
        print("\n请先设置: set DEEPSEEK_API_KEY=sk-xxx")
        return

    print("\n正在连接 DeepSeek API...")

    try:
        proxies = {}
        if proxy:
            proxies["https://"] = proxy
            proxies["http://"] = proxy

        async with httpx.AsyncClient(timeout=30.0, proxy=proxies.get("https://") or proxies.get("http://")) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "回复OK"}],
                    "max_tokens": 10,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                print(f"✅ 连接成功！DeepSeek 回复: {reply}")
            else:
                print(f"❌ API 返回错误 {resp.status_code}:")
                print(f"   {resp.text[:300]}")
    except httpx.ConnectError as e:
        print(f"❌ 连接失败: {e}")
        if proxy:
            print(f"   当前代理: {proxy}")
            print(f"   试试换代理或去掉代理: set HTTPS_PROXY=")
        else:
            print(f"   你可能需要配置代理:")
            print(f"   set HTTPS_PROXY=http://你的代理地址:端口")
    except Exception as e:
        print(f"❌ 错误: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
