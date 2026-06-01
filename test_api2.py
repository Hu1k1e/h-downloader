import httpx
import asyncio

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get("https://ww8.123moviesfree.net/searching?q=From+season+3&limit=40&offset=0", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"
        })
        print(r.status_code)
        print(r.text[:500])

if __name__ == "__main__":
    asyncio.run(main())
