import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("Navigating to iframe...")
        await page.goto("https://ployan.me/watch/?v23#K3llZTl3a0lVQUZwaWFBblNocEhobWJsZU1NVFJOc2R2cWtZYjNWRWF6TXowOCtkS2d4dEU1dnQzaWlRUkx1N0ovZFVWYmY1OFd3PQ", timeout=30000)
        
        await asyncio.sleep(5)
        
        content = await page.content()
        with open("iframe_dump.html", "w", encoding="utf-8") as f:
            f.write(content)
        print("Dumped iframe to iframe_dump.html")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
