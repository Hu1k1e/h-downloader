import re

with open('fmovies.html', 'r', encoding='utf-8') as f:
    text = f.read()

links = set(re.findall(r'href=[\"\'](.*?)[\"\']', text))
with open('links.txt', 'w', encoding='utf-8') as f:
    for link in sorted(links):
        f.write(link + '\n')
