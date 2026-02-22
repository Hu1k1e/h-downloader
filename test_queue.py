import asyncio
from backend.services.radarr import _url, _headers
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        resp = await client.get(_url("/queue"), headers=_headers())
        print(resp.status_code)
        print(resp.json())
asyncio.run(main())
