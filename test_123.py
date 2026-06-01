import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
try:
    url = "https://123movies.com.pk/search/from/"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx) as r:
        html = r.read().decode('utf-8', errors='ignore')
        import re
        links = re.findall(r'href=["\'](https://123movies.com.pk/series/[^"\']+)["\']', html)
        print("Links found:", links[:5])
        if links:
            req2 = urllib.request.Request(links[0], headers=headers)
            with urllib.request.urlopen(req2, context=ctx) as r2:
                html2 = r2.read().decode('utf-8', errors='ignore')
                eps = re.findall(r'href=["\'](https://123movies.com.pk/episode/[^"\']+)["\']', html2)
                print("Eps:", eps[:5])
except Exception as e:
    print("Failed:", e)
