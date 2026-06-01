import asyncio
import logging
from backend.services.onetwothreemovies import search_media

logging.basicConfig(level=logging.INFO)

async def main():
    url = await search_media("From", None, True, 3, 1)
    print(f"Result URL: {url}")

if __name__ == "__main__":
    asyncio.run(main())
