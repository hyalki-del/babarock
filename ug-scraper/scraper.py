import os
import re
import sys
import json
import time
import traceback
import unicodedata
from pathlib import Path
from bs4 import BeautifulSoup
import cloudscraper

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"
DEBUG_FILE = BASE_DIR / "debug_failed_page.html"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_lyrics_only(raw_text: str) -> str:
    """Transforms raw UG markup into pure text-only lyrics."""
    if not raw_text:
        return ""

    text = re.sub(r'\[ch\](.*?)\[\/ch\]', '', raw_text)
    text = re.sub(r'\[\/?(tab|chords)[^\]]*\]', '', text)
    text = re.sub(r'\[(Verse|Chorus|Bridge|Intro|Outro|Solo|Hook|Pre-Chorus)[^\]]*\]', r'[\1]', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\/?([a-zA-Z0-9_\-]+)[^\]]*\]', '', text)

    text = unicodedata.normalize("NFKD", text)
    text = (
        text.replace('\xa0', ' ')
            .replace('’', "'")
            .replace('‘', "'")
            .replace('”', '"')
            .replace('“', '"')
            .replace('–', '-')
            .replace('—', '-')
    )

    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def extract_store_from_html(html_content: str) -> dict:
    """Extracts window.UG_STORE page dictionary from HTML payload."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    store_tag = soup.find('script', class_='js-store')
    if store_tag and store_tag.string:
        try:
            data = json.loads(store_tag.string)
            return data.get('store', {}).get('page', {})
        except json.JSONDecodeError:
            pass

    match = re.search(r'window\.UG_STORE\s*=\s*(\{.*?\});', html_content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get('store', {}).get('page', {}) or data.get('page', {})
        except json.JSONDecodeError:
            pass

    return {}


def save_debug_snapshot(content: str):
    """Guarantees a debug file is dumped to disk on failure."""
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[!] Saved debug HTML snapshot to {DEBUG_FILE}")
    except Exception as e:
        print(f"[-] Failed to write debug snapshot: {e}")


def scrape_playlist():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    print(f"[+] Requesting playlist URL: {PLAYLIST_URL}")
    
    try:
        response = scraper.get(PLAYLIST_URL)
    except Exception as e:
        print(f"[-] Network Request Crash: {e}")
        traceback.print_exc()
        sys.exit(1)

    print(f"[+] HTTP Response Status: {response.status_code}")

    # Always save raw response snapshot if request fails or isn't 200
    if response.status_code != 200:
        print(f"[-] CRITICAL FAILURE: HTTP {response.status_code} received.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    store = extract_store_from_html(response.text)
    playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

    if not playlist_items:
        print("[-] CRITICAL FAILURE: Failed to parse playlist items from window.UG_STORE.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    print(f"[+] Extracted {len(playlist_items)} items. Processing lyrics...")

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
                raw_content = (
                    tab_view.get('wiki_tab', {}).get('content', '') or 
                    tab_view.get('tab', {}).get('content', '')
                )

                if raw_content:
                    clean_lyrics = clean_lyrics_only(raw_content)

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(clean_lyrics)

                    saved_count += 1
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [!] No content text found for {song_title}")
            else:
                print(f"  [✗] Song page failed with HTTP {tab_response.status_code}")

        except Exception as e:
            print(f"  [✗] Exception on {song_url}: {e}")

        time.sleep(1.5)

    if saved_count == 0:
        print("[-] CRITICAL FAILURE: Processed items but saved 0 files.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    print(f"\n[+] SUCCESS: Saved {saved_count}/{len(playlist_items)} lyric files.")


if __name__ == "__main__":
    scrape_playlist()
