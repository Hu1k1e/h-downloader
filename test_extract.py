import asyncio
import logging
from backend.services.onetwothreemovies import extract_mp4_url

logging.basicConfig(level=logging.INFO)

async def main():
    stream_url, cookie_str = await extract_mp4_url("https://ww8.123moviesfree.net/season/from-season-3-1630857665/", is_series=True, season=3, episode=1)
    if stream_url and cookie_str:
        print(f"Result URL: {stream_url}|cookies={cookie_str}")
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-headers", f"Referer: https://ww8.123moviesfree.net/\r\nCookie: {cookie_str}\r\n",
            "-i", stream_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "test_output.mp4"
        ]
        subprocess.run(cmd)
    return stream_url

if __name__ == "__main__":
    asyncio.run(main())
