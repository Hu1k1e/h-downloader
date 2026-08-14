import asyncio
import logging
from backend.services.fmovies import search_movie

logging.basicConfig(level=logging.INFO)

class Settings:
    fmovies_base_url = 'https://www.f-movies.org'
    llm_enabled = False
    llm_api_key = ''

async def main():
    url = await search_movie(572151, 'Zombie for Sale', 2019, Settings())
    print(f"Result URL: {url}")

if __name__ == '__main__':
    asyncio.run(main())
