import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        async def handle_response(response):
            if "search" in response.url or "api" in response.url or "ajax" in response.url or "json" in response.url:
                print(f"API/Search call: {response.url}")
        page.on("response", handle_response)
        
        print("Navigating to search...")
        await page.goto("https://ww8.123moviesfree.net/search/?q=From")
        
        await page.wait_for_selector("#resdata", state="attached", timeout=10000)
        # Give it a bit more time to populate
        await asyncio.sleep(2)
        
        content = await page.content()
        with open("search_pw_dump.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
