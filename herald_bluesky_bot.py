# herald_bluesky_bot.py (Bluesky bot)
import os
import logging
import requests
import re
import time
import random
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dotenv import load_dotenv
import pytz
from atproto import Client, models

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("herald_bluesky_bot.log"),
        logging.StreamHandler()
    ]
)

class HeraldBlueskyBot:
    BASE_URL = "https://www.heraldscotland.com"
    POLITICS_URL = f"{BASE_URL}/politics/"
    POSTED_URLS_FILE = "posted_urls.txt"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive"
    }

    def __init__(self):
        self.client = Client()
        handle = os.getenv("BLUESKY_HANDLE")
        logging.info(f"Attempting to log in with handle: {handle}")
        if not handle or not os.getenv("BLUESKY_APP_PASSWORD"):
            logging.error("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD is not set.")
            raise ValueError("Missing Bluesky credentials")
        self.client.login(
            login=handle,
            password=os.getenv("BLUESKY_APP_PASSWORD")
        )

    def load_posted_urls(self):
        if not os.path.exists(self.POSTED_URLS_FILE):
            return set()
        with open(self.POSTED_URLS_FILE, 'r') as f:
            return set(line.strip() for line in f)

    def save_posted_url(self, url):
        with open(self.POSTED_URLS_FILE, 'a') as f:
            f.write(f"{url}\n")

    def fetch_article_urls(self):
        try:
            time.sleep(random.uniform(1.5, 3.5))
            response = requests.get(self.POLITICS_URL, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            urls = set()
            for link in soup.find_all('a', href=True):
                href = link['href'].split('#')[0]
                if not href.startswith('/'):
                    continue
                if not re.search(r'/\d{8,}\.', href):
                    continue
                full_url = (self.BASE_URL + href.split('?')[0]).rstrip('/').lower()
                urls.add(full_url)
            logging.info(f"Found {len(urls)} article URLs.")
            return list(urls)
        except Exception as e:
            logging.error(f"Failed to fetch URLs from {self.POLITICS_URL}: {e}")
            return []

    def get_article_info(self, url):
        try:
            time.sleep(random.uniform(1.5, 3.5))
            response = requests.get(url, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            headline = soup.find('h1').get_text(strip=True) if soup.find('h1') else None
            time_tag = soup.find('time')
            published = (
                datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
                if time_tag and time_tag.has_attr('datetime') else None
            )
            return headline, published
        except Exception as e:
            logging.warning(f"Failed to extract info for {url}: {e}")
            return None, None

    def post_to_bluesky(self, headline, url):
        text = f"{headline} {url}"
        if len(text) > 300:
            max_headline_len = 300 - len(url) - 1
            headline = headline[:max_headline_len]
            text = f"{headline} {url}"

        try:
            url_start = len(headline.encode('utf-8')) + 1
            url_end = url_start + len(url.encode('utf-8'))
            facets = [{
                "index": {"byteStart": url_start, "byteEnd": url_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
            }]

            response = requests.get(url, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            og_title = soup.find('meta', property='og:title')
            og_description = soup.find('meta', property='og:description')
            og_image = soup.find('meta', property='og:image')

            title = og_title['content'] if og_title and 'content' in og_title.attrs else headline
            description = og_description['content'] if og_description and 'content' in og_description.attrs else "Read more on Herald Scotland"
            image_url = og_image['content'] if og_image and 'content' in og_image.attrs else None

            external = models.AppBskyEmbedExternal.External(
                uri=url,
                title=title[:300],
                description=description[:1000],
            )

            if image_url:
                try:
                    image_response = requests.get(image_url, headers=self.HEADERS, timeout=10)
                    image_response.raise_for_status()
                    image_data = image_response.content
                    blob = self.client.com.atproto.repo.upload_blob(image_data).blob
                    external.thumb = blob
                except Exception as e:
                    logging.warning(f"Failed to upload image for link card: {e}")

            embed = models.AppBskyEmbedExternal.Main(external=external)
            self.client.send_post(text, facets=facets, embed=embed)
            self.save_posted_url(url)
            return True
        except Exception as e:
            logging.error(f"Failed to post to Bluesky: {e}")
            return False

    def run(self):
        logging.info("Starting Herald Bluesky bot run.")
        bst = pytz.timezone('Europe/London')
        now = datetime.now(timezone.utc).astimezone(bst)
        if not (7 <= now.hour < 20):
            logging.info("Outside 7 AM–8 PM BST. Skipping run.")
            return

        posted_urls = self.load_posted_urls()
        for url in self.fetch_article_urls():
            if url in posted_urls:
                continue
            headline, published = self.get_article_info(url)
            if not headline or not published:
                continue
            if (datetime.now(timezone.utc) - published).total_seconds() > 43200:
                continue
            if self.post_to_bluesky(headline, url):
                break
        logging.info("Herald Bluesky bot finished run.")

if __name__ == "__main__":
    print("Running Herald Bluesky Bot...")
    bot = HeraldBlueskyBot()
    bot.run()
    print("Done!")
