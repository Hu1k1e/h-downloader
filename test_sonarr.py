import asyncio
import httpx
from sqlmodel import Session, select
from backend.database import engine, AppSettings

async def run():
    with Session(engine) as session:
        s = session.exec(select(AppSettings)).first()
        print("Sonarr Key:", s.sonarr_api_key)
        
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{s.sonarr_url}/api/v3/series", headers={"X-Api-Key": s.sonarr_api_key})
            d = r.json()
            print("Series count:", len(d))
            for x in d[:10]:
                print(x.get('title'), "-> originalLanguage:", x.get('originalLanguage'), "language:", x.get('language'))

asyncio.run(run())
