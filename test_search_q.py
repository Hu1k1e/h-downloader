import httpx
import asyncio

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get("https://ww8.123moviesfree.net/search/?q=From+season+3")
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print("Title: " + r.text[r.text.find('<title>'):r.text.find('</title>')+8])
            # search for 'flw-item'
            if 'flw-item' in r.text or 'film-poster' in r.text or 'ml-item' in r.text or 'item' in r.text:
                print("Found items!")
            else:
                print("No items found.")
        else:
            print("Failed")

if __name__ == "__main__":
    asyncio.run(main())
