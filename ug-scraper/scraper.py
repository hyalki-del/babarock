import os
import re
import sys
import json
import time
import traceback
import unicodedata
from pathlib import Path
import cloudscraper

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

# Path definitions
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"
DEBUG_FILE = BASE_DIR / "debug_failed_page.html"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_lyrics_only(raw_text: str) -> str:
    """
    Transforms raw UG markup into pure text-only lyrics.
    Strips chords, BBCode markup, structural tags, and normalizes unicode.
    """
    if not raw_text:
        return ""

    # 1. Strip chord tags and inner chord content completely
    text = re.sub(r'\[ch\](.*?)\[\/ch\]', '', raw_text)
    
    # 2. Strip remaining structural wrapper tags ([tab], [chords], etc.)
    text = re.sub(r'\[\/?(tab|chords)[^\]]*\]', '', text)

    # 3. Standardize section headers like [Verse 1], [Chorus]
    text = re.sub(
        r'\[(Verse|Chorus|Bridge|Intro|Outro|Solo|Hook|Pre-Chorus)[^\]]*\]', 
        r'[\1]', 
        text, 
        flags=re.IGNORECASE
    )
    
    # 4. Remove stray leftover brackets/tags
    text = re.sub(r'\[\/?([a-zA-Z0-9_\-]+)[^\]]*\]', '', text)

    # 5. Unicode Normalization (smart quotes -> standard ASCII)
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

    # 6. Cleanup empty lines and excessive space
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def extract_store_from_html(html_content: str) -> dict:
    """Attempts to parse window.UG_STORE page state from raw HTML string."""
    # Pattern 1: JSON inside window.UG_STORE = {...}
    match = re.search(r'window\.UG_STORE\s*=\s*(\{.*?\});\s*</script>', html_content, re.DOTALL)
    if not match:
        match = re.search(r'window\.UG_STORE\s*=\s*(\{.*?\});', html_content, re.DOTALL)
        
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get('store', {}).get('page', {}) or data.get('page', {})
        except json.JSONDecodeError as e:
            print(f"[-] JSON decode error on UG_STORE pattern: {e}")

    return {}


def save_debug_snapshot(content: str):
    """Saves raw response payload to disk for GitHub Action Artifact inspection."""
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[!] Saved debug HTML snapshot to: {DEBUG_FILE}")
    except Exception as e:
        print(f"[-] Failed to write debug snapshot: {e}")


def scrape_playlist():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Setup cloudscraper with explicit desktop browser fingerprinting
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    # Custom HTTP headers requesting JSON API format
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }

    print(f"[+] Requesting playlist URL: {PLAYLIST_URL}")
    
    try:
        response = scraper.get(PLAYLIST_URL, headers=headers)
    except Exception as e:
        print(f"[-] Network Request Crash: {e}")
        traceback.print_exc()
        sys.exit(1)

    print(f"[+] HTTP Response Status: {response.status_code}")

    if response.status_code != 200:
        print(f"[-] CRITICAL FAILURE: HTTP {response.status_code} received.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    # Detect Cloudflare CAPTCHA/Challenge text
    if "just a moment" in response.text.lower() or "challenge-running" in response.text.lower():
        print("[-] CRITICAL FAILURE: Cloudflare Challenge page intercepted the runner IP.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    store = extract_store_from_html(response.text)
    playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

    if not playlist_items:
        print("[-] CRITICAL FAILURE: Failed to parse playlist items from window.UG_STORE.")
        print("[-] Saving raw HTML page snapshot for diagnosis...")
        save_debug_snapshot(response.text)
        sys.exit(1)

    print(f"[+] Extracted {len(playlist_items)} items from playlist. Processing lyrics...")

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
            tab_response = scraper.get(song_url, headers=headers)
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

        time.sleep(1.5)  # Rate limiting throttling

    if saved_count == 0:
        print("[-] CRITICAL FAILURE: Processed items but saved 0 files.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    print(f"\n[+] SUCCESS: Process completed. Saved {saved_count}/{len(playlist_items)} lyric files.")


if __name__ == "__main__":
    scrape_playlist()
