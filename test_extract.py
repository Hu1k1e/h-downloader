import asyncio
import logging
from backend.services.onetwothreemovies import extract_mp4_url

logging.basicConfig(level=logging.INFO)

async def main():
    res = await extract_mp4_url("https://ww8.123moviesfree.net/season/from-season-3-1630857665/", is_series=True, season=3, episode=1)
    print(f"Raw Res: {res}")
    return res

if __name__ == "__main__":
    asyncio.run(main())
