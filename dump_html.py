import httpx
import asyncio

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get("https://ww8.123moviesfree.net")
        with open("123.html", "w", encoding="utf-8") as f:
            f.write(r.text)

if __name__ == "__main__":
    asyncio.run(main())
