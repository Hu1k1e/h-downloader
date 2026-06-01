import httpx
from bs4 import BeautifulSoup
import asyncio

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get("https://ww8.123moviesfree.net")
        soup = BeautifulSoup(r.text, 'lxml')
        form = soup.find('form')
        if form:
            print(f"Form action: {form.get('action')}")
        else:
            print("No form found")

if __name__ == "__main__":
    asyncio.run(main())
