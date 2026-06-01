import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        stream_url = None

        async def handle_response(response):
            nonlocal stream_url
            url = response.url
            if "ployan.me/get/" in url or "api" in url:
                try:
                    if response.status == 200:
                        text = await response.text()
                        import json
                        data = json.loads(text)
                        if "info" in data:
                            info_hex = data["info"]
                            print("Found encrypted info:", info_hex)
                            # Evaluate decryption in browser
                            decrypted = await page.evaluate('''async ([infoHex, password]) => {
                                const parts = infoHex.split("-");
                                const salt = new Uint8Array(parts[0].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                const iv = new Uint8Array(parts[1].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                const ciphertext = new Uint8Array(parts[2].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                
                                const keyMaterial = await crypto.subtle.importKey(
                                    "raw",
                                    new TextEncoder().encode(password),
                                    "PBKDF2",
                                    false,
                                    ["deriveKey"]
                                );
                                
                                const key = await crypto.subtle.deriveKey(
                                    {
                                        name: "PBKDF2",
                                        salt: salt,
                                        iterations: 1000,
                                        hash: "SHA-256"
                                    },
                                    keyMaterial,
                                    { name: "AES-GCM", length: 256 },
                                    false,
                                    ["decrypt"]
                                );
                                
                                const decryptedBuffer = await crypto.subtle.decrypt(
                                    {
                                        name: "AES-GCM",
                                        iv: iv
                                    },
                                    key,
                                    ciphertext
                                );
                                
                                return new TextDecoder().decode(decryptedBuffer);
                            }''', [info_hex, "player"])
                            
                            print("DECRYPTED:", decrypted)
                            
                            # Construct final URL
                            domain = url.split("/get/")[0]
                            stream_url = f"{domain}/hls/{decrypted}/master.m3u8"
                            print("FINAL STREAM URL:", stream_url)
                except Exception as e:
                    pass

        page.on("response", handle_response)

        # Navigate to season page
        print("Navigating...")
        await page.goto("https://ww8.123moviesfree.net/season/from-season-1-1630861315/", timeout=30000)

        # Wait for the play-now button to exist
        print("Waiting for play-now button...")
        await page.wait_for_selector("#play-now", state="attached")
        print("Clicking play-now...")
        await page.locator("#play-now").click()
        
        # Wait for the episode button to become visible
        print("Waiting for episode 3...")
        await page.wait_for_selector("#ep-3", state="visible")

        # Click the episode button
        print("Clicking episode 3...")
        await page.locator("#ep-3").click()

        print("Waiting for iframe to be created...")
        # Check for iframe after 3 seconds
        await page.wait_for_selector("iframe#playit", state="attached")
        
        # Get the frame
        frame_element = page.locator("iframe#playit")
        frame = await frame_element.element_handle()
        content_frame = await frame.content_frame()
        
        if content_frame:
            print("Found content frame! Waiting for it to load...")
            await content_frame.wait_for_load_state()
            print("Content frame loaded. Waiting for 3 seconds...")
            await asyncio.sleep(3)
            
            # Try to get the stream URL from jwplayer
            try:
                stream_url = await content_frame.evaluate('''() => {
                    if (typeof jwplayer !== 'undefined') {
                        return jwplayer().getPlaylist()[0].file;
                    }
                    return null;
                }''')
                print("Extracted from jwplayer:", stream_url)
            except Exception as e:
                print("Error extracting from jwplayer:", e)
            
            if not stream_url:
                print("Clicking body of content frame to trigger play...")
                await content_frame.locator("body").click(force=True)
                # wait a bit more
                await asyncio.sleep(2)
                print("Clicking again just in case...")
                await content_frame.locator("body").click(force=True)
        else:
            print("Could not get content frame!")

        print("Waiting for stream to be intercepted...")
        for _ in range(20):
            if stream_url:
                break
            await asyncio.sleep(1)

        print("Final stream URL:", stream_url)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
