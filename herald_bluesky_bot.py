import os
import logging
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dotenv import load_dotenv
import pytz  # For BST time check
from atproto import Client  # For Bluesky API

# Load environment variables
load_dotenv()

# Configure logging
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
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    def __init__(self):
        # Initialize Bluesky client
        self.client = Client()
        handle = os.getenv("BLUESKY_HANDLE")
        logging.info(f"Attempting to log in with handle: {handle}")
        if not handle or not os.getenv("BLUESKY_APP_PASSWORD"):
            logging.error("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD is not set in environment variables.")
            raise ValueError("Missing Bluesky credentials")
        self.client.login(
            login=handle,
            password=os.getenv("BLUESKY_APP_PASSWORD")
        )

    def load_posted_urls(self):
        """Load URLs that have already been posted."""
        if not os.path.exists(self.POSTED_URLS_FILE):
            logging.info("No posted_urls.txt found, starting fresh.")
            return set()
        with open(self.POSTED_URLS_FILE, 'r') as f:
            urls = set(line.strip() for line in f)
            logging.info(f"Loaded {len(urls)} posted URLs.")
            return urls

    def save_posted_url(self, url):
        """Append a single URL to posted_urls.txt."""
        with open(self.POSTED_URLS_FILE, 'a') as f:
            f.write(f"{url}\n")
        logging.info(f"Saved URL to posted_urls.txt: {url}")

    def fetch_article_urls(self):
        """Fetch article URLs from the politics page."""
        try:
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
            logging.error(f"Failed to fetch URLs: {e}")
            return []

    def get_article_info(self, url):
        """Extract headline and publication time from an article."""
        try:
            response = requests.get(url, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            headline = soup.find('h1').get_text(strip=True) if soup.find('h1') else None
            time_tag = soup.find('time')
            published = (
                datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
                if time_tag and time_tag.has_attr('datetime')
                else None
            )
            logging.info(f"Extracted info for {url}: headline='{headline}', published={published}")
            return headline, published
        except Exception as e:
            logging.warning(f"Failed to extract info for {url}: {e}")
            return None, None

    def post_to_bluesky(self, headline, url):
        """Post an article to Bluesky."""
        text = f"{headline} {url}"[:300]  # Bluesky posts are limited to 300 characters
        try:
            self.client.send_post(text)
            logging.info(f"Posted to Bluesky: {text}")
            self.save_posted_url(url)
            return True
        except Exception as e:
            logging.error(f"Failed to post to Bluesky: {e}")
            return False

    def run(self):
        """Run the bot to post one article, only between 6 AM and 10 PM BST (temporary for testing)."""
        logging.info("Starting Herald Bluesky bot run.")

        # Check if current time is between 6 AM and 10 PM BST (adjusted for testing)
        bst = pytz.timezone('Europe/London')
        now = datetime.now(timezone.utc)
        now_bst = now.astimezone(bst)
        current_hour = now_bst.hour

        if not (6 <= current_hour < 23):  # 6 AM to 10 PM BST (temporary for testing)
            logging.info(f"Current time {now_bst.strftime('%Y-%m-%d %H:%M:%S %Z')} is outside 6 AM-10 PM BST. Skipping run.")
            return

        # Proceed with normal bot logic
        posted_urls = self.load_posted_urls()
        for url in self.fetch_article_urls():
            if url in posted_urls:
                logging.info(f"Skipping already posted URL: {url}")
                continue
            headline, published = self.get_article_info(url)
            if not headline or not published:
                logging.info(f"Skipping {url} due to missing headline or publish time.")
                continue
            age = datetime.now(timezone.utc) - published
            if age.total_seconds() > 43200:  # 12 hours
                logging.info(f"Skipping old article: {url} (published at {published})")
                continue
            if self.post_to_bluesky(headline, url):
                logging.info("Successfully posted one article, stopping.")
                break
            else:
                logging.info(f"Failed to post {url}, trying next article.")
        logging.info("Herald Bluesky bot finished run.")

if __name__ == "__main__":
    print("Running Herald Bluesky Bot...")
    bot = HeraldBlueskyBot()
    bot.run()
    print("Done!")
