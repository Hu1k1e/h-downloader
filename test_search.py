import asyncio
import logging
import sys

from backend import config
from backend.services.onetwothreemovies import search_media

logging.basicConfig(level=logging.INFO)

async def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "From"
    season = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    print(f"Searching for {title} Season {season}...")
    url = await search_media(title, None, True, season, 1)
    print(f"Result URL: {url}")

if __name__ == "__main__":
    asyncio.run(main())
