import httpx
from bs4 import BeautifulSoup
import asyncio

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get("https://ww8.123moviesfree.net/search/?q=From")
        with open("search_dump.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("Dumped search_dump.html")


if __name__ == "__main__":
    asyncio.run(main())
