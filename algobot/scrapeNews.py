import requests
from bs4 import BeautifulSoup

URL = 'https://www.todayonchain.com/'
page = requests.get(URL)

soup = BeautifulSoup(page.content, 'html.parser')
links = soup.find('div', class_='api_article_include').find_all('a')

for link in links:
    hyperlink = link['href']
    title = link.find('div', class_='api_article_title_sm').text
    print(title)
    print(hyperlink)