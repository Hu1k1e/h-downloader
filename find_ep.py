with open('page_dump.html', 'r', encoding='utf-8') as f:
    content = f.read()
idx = content.find('id="ep-3"')
if idx != -1:
    print(content[max(0, idx-3000):idx])
