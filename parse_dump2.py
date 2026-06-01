from bs4 import BeautifulSoup

with open("search_pw_dump.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), 'lxml')

list_movie = soup.select_one('.list-movie a')
if list_movie:
    print(list_movie.prettify())
