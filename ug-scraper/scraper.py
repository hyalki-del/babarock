import os
import re
import sys
import json
import time
from pathlib import Path
import cloudscraper

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def strip_ug_tags(content: str) -> str:
    """Strips Ultimate Guitar BBCode-style chord/tab markup including attributes."""
    return re.sub(r'\[\/?(ch|tab|chords)[^\]]*\]', '', content)


def extract_store_from_html(html_content: str) -> dict:
    """Extracts window.UG_STORE data directly from HTML script tags."""
    try:
        # Match the window.UG_STORE store object embedded in HTML
        match = re.search(r'window\.UG_STORE\s*=\s*(\{.*?\});</script>', html_content, re.DOTALL)
        if match:
            json_str = match.group(1)
            # Find the page store component
            data = json.loads(json_str)
            return data.get('store', {}).get('page', {})
    except Exception as e:
        print(f"[-] Error parsing JSON store from HTML: {e}")
    return {}


def scrape_playlist():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize cloudscraper to bypass Cloudflare TLS fingerprints
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    print(f"[+] Fetching playlist page via Cloudflare bypass: {PLAYLIST_URL}")
    response = scraper.get(PLAYLIST_URL)

    if response.status_code != 200:
        print(f"[-] Failed to fetch page. HTTP Status Code: {response.status_code}")
        sys.exit(1)

    store = extract_store_from_html(response.text)
    playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

    if not playlist_items:
        print("[-] CRITICAL ERROR: No items found in store tree.")
        sys.exit(1)

    print(f"[+] Found {len(playlist_items)} items in playlist. Processing...")

    saved_count = 0
    for idx, item in enumerate(playlist_items, 1):
        song_url = item.get('tab_url')
        artist_name = item.get('artist_name', 'Unknown Artist')
        song_title = item.get('song_name', 'Unknown Song')

        if not song_url:
            continue

        filename = sanitize_filename(f"{artist_name} - {song_title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(playlist_items)}] Processing: {artist_name} - {song_title}")

        try:
            tab_response = scraper.get(song_url)
            if tab_response.status_code == 200:
                tab_store = extract_store_from_html(tab_response.text)
                tab_view = tab_store.get('data', {}).get('tab_view', {})
                tab_content = tab_view.get('wiki_tab', {}).get('content', '') or tab_view.get('tab', {}).get('content', '')

                if tab_content:
                    cleaned_content = strip_ug_tags(tab_content)

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)

                    saved_count += 1
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [!] No tab text found in state for {song_title}.")
            else:
                print(f"  [✗] Failed to load song page (HTTP {tab_response.status_code})")

        except Exception as e:
            print(f"  [✗] Error processing {song_url}: {e}")
        
        time.sleep(1)  # Respect rate limits

    print(f"[+] Execution completed. Total songs saved: {saved_count}/{len(playlist_items)}")


if __name__ == "__main__":
    scrape_playlist()
