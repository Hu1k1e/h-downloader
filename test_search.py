import asyncio
from backend.services.tamilmv import search_movie
from backend.database import get_settings, Session, engine

async def test():
    domain = "https://www.1tamilmv.cards"
    res = await search_movie("Spa", 2026, domain, ["Malayalam"])
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(test())
