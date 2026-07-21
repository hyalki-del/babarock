import os
import re
import sys
import json
import time
from pathlib import Path
from bs4 import BeautifulSoup
import cloudscraper

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def strip_ug_tags(content: str) -> str:
    """Strips Ultimate Guitar BBCode-style chord/tab markup including attributes [ch id=...]."""
    return re.sub(r'\[\/?(ch|tab|chords)[^\]]*\]', '', content)


def extract_store_from_html(html_content: str) -> dict:
    """
    Extracts the window.UG_STORE page dictionary from HTML using
    BeautifulSoup DOM parsing with Regex fallback.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Primary Method: Locate the specific js-store script container
    store_tag = soup.find('script', class_='js-store')
    if store_tag and store_tag.string:
        try:
            data = json.loads(store_tag.string)
            return data.get('store', {}).get('page', {})
        except json.JSONDecodeError:
            pass

    # 2. Fallback Method: Regex search across full inline scripts
    match = re.search(r'window\.UG_STORE\s*=\s*(\{.*?\});', html_content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            # Handle both root store wrapper or direct page object
            return data.get('store', {}).get('page', {}) or data.get('page', {})
        except json.JSONDecodeError:
            pass

    return {}


def scrape_playlist():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Cloudscraper handles TLS fingerprinting to pass Cloudflare without Playwright
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    print(f"[+] Requesting playlist page: {PLAYLIST_URL}")
    response = scraper.get(PLAYLIST_URL)

    if response.status_code != 200:
        print(f"[-] HTTP Error {response.status_code}: Cloudflare or network issue.")
        sys.exit(1)

    store = extract_store_from_html(response.text)
    playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

    if not playlist_items:
        print("[-] CRITICAL ERROR: Could not parse playlist items from state object.")
        print("[-] The HTML structure may have changed or Cloudflare blocked the request.")
        sys.exit(1)  # Force workflow failure in CI

    print(f"[+] Successfully extracted {len(playlist_items)} songs from playlist.")

    saved_count = 0
    for idx, item in enumerate(playlist_items, 1):
        song_url = item.get('tab_url')
        artist_name = item.get('artist_name', 'Unknown Artist')
        song_title = item.get('song_name', 'Unknown Song')

        if not song_url:
            continue

        filename = sanitize_filename(f"{artist_name} - {song_title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(playlist_items)}] Fetching: {artist_name} - {song_title}")

        try:
            tab_response = scraper.get(song_url)
            if tab_response.status_code == 200:
                tab_store = extract_store_from_html(tab_response.text)
                
                # Check standard wiki_tab first, fall back to tab or preview content
                tab_view = tab_store.get('data', {}).get('tab_view', {})
                tab_content = (
                    tab_view.get('wiki_tab', {}).get('content', '') or 
                    tab_view.get('tab', {}).get('content', '')
                )

                if tab_content:
                    cleaned_content = strip_ug_tags(tab_content)

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)

                    saved_count += 1
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [!] No content found in payload for '{song_title}'.")
            else:
                print(f"  [✗] Failed to fetch song page (HTTP {tab_response.status_code})")

        except Exception as e:
            print(f"  [✗] Error processing {song_url}: {e}")
        
        time.sleep(1)  # Polite request throttling

    print(f"\n[+] Processing finished. Saved {saved_count}/{len(playlist_items)} text files.")


if __name__ == "__main__":
    scrape_playlist()
