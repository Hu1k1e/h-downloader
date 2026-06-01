from bs4 import BeautifulSoup
import sys

with open("search_pw_dump.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), 'lxml')

print("Title:", soup.title.text if soup.title else "No title")

# Try to find common movie item classes
for class_name in ['flw-item', 'film-poster', 'ml-item', 'item', 'movie-item', 'list-movie', 'poster']:
    items = soup.select(f".{class_name}")
    print(f"Class '{class_name}': {len(items)} items found")
    if items and len(items) < 10:
        for i in items[:3]:
            print(i.text.strip())

# See if there's a div holding results
results = soup.select("a")
from_links = [a for a in results if 'from' in (a.get('title') or a.text).lower()]
print(f"Links with 'from': {len(from_links)}")
for a in from_links[:5]:
    print(a.get('title') or a.text, a.get('href'))
