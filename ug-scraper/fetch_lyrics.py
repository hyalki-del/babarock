import os
import re
import sys
import json
import time
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path
import cloudscraper

# Configuration
PLAYLIST_URL = os.getenv(
    "PLAYLIST_URL", 
    "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"
DEBUG_FILE = BASE_DIR / "debug_failed_page.html"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_lyrics_only(raw_text: str) -> str:
    """
    Transforms raw UG/Markup lyrics into clean, readable text.
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

    # 5. Unicode Normalization
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

    # 6. Cleanup whitespace
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def fetch_lyrics_from_lrclib(artist: str, title: str) -> str:
    """
    Fallback lyrics provider using LRCLIB (Free, open-source, no API keys needed).
    Returns plain lyrics string or empty string if not found.
    """
    params = urllib.parse.urlencode({'artist_name': artist, 'track_name': title})
    url = f"https://lrclib.net/api/get?{params}"
    
    headers = {'User-Agent': 'GitHubActions-LyricsFetcher/1.0'}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get('plainLyrics', '') or data.get('syncedLyrics', '')
    except Exception:
        # Secondary fuzzy search endpoint
        search_url = f"https://lrclib.net/api/search?q={urllib.parse.quote(f'{artist} {title}')}"
        try:
            req_search = urllib.request.Request(search_url, headers=headers)
            with urllib.request.urlopen(req_search, timeout=10) as resp:
                if resp.status == 200:
                    results = json.loads(resp.read().decode('utf-8'))
                    if results and isinstance(results, list):
                        return results[0].get('plainLyrics', '')
        except Exception:
            pass

    return ""


def extract_store_from_html(html_content: str) -> dict:
    """Parses window.UG_STORE page state from raw HTML string."""
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
    
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }

    print(f"[+] Fetching playlist: {PLAYLIST_URL}")
    
    try:
        response = scraper.get(PLAYLIST_URL, headers=headers)
    except Exception as e:
        print(f"[-] Network Request Crash: {e}")
        sys.exit(1)

    if response.status_code != 200 or "just a moment" in response.text.lower():
        print(f"[-] WARNING: UG Direct Access Blocked (HTTP {response.status_code} / Cloudflare Challenge).")
        save_debug_snapshot(response.text)
        sys.exit(1)

    store = extract_store_from_html(response.text)
    playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

    if not playlist_items:
        print("[-] CRITICAL FAILURE: Could not parse playlist items from UG_STORE.")
        save_debug_snapshot(response.text)
        sys.exit(1)

    print(f"[+] Extracted {len(playlist_items)} tracks from playlist. Processing...")

    saved_count = 0
    for idx, item in enumerate(playlist_items, 1):
        song_url = item.get('tab_url')
        artist_name = item.get('artist_name', 'Unknown Artist')
        song_title = item.get('song_name', 'Unknown Song')

        filename = sanitize_filename(f"{artist_name} - {song_title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(playlist_items)}] {artist_name} - {song_title}")

        if filepath.exists():
            print(f"  [➜] Skipping: Already exists -> {filename}")
            saved_count += 1
            continue

        raw_content = ""

        # Primary extraction attempt: Ultimate Guitar
        if song_url:
            try:
                tab_response = scraper.get(song_url, headers=headers)
                if tab_response.status_code == 200 and "just a moment" not in tab_response.text.lower():
                    tab_store = extract_store_from_html(tab_response.text)
                    tab_view = tab_store.get('data', {}).get('tab_view', {})
                    raw_content = (
                        tab_view.get('wiki_tab', {}).get('content', '') or 
                        tab_view.get('tab', {}).get('content', '')
                    )
            except Exception as e:
                print(f"  [!] UG Fetch failed: {e}")

        # Secondary fallback: LRCLIB API
        if not raw_content:
            print("  [!] UG tab content unavailable. Querying fallback API (LRCLIB)...")
            raw_content = fetch_lyrics_from_lrclib(artist_name, song_title)

        if raw_content:
            clean_lyrics = clean_lyrics_only(raw_content)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Artist: {artist_name}\nTitle: {song_title}\n")
                if song_url:
                    f.write(f"URL: {song_url}\n")
                f.write("=" * 50 + "\n\n")
                f.write(clean_lyrics)

            saved_count += 1
            print(f"  [✓] Saved -> {filename}")
        else:
            print(f"  [✗] Failed to fetch lyrics from all sources.")

        time.sleep(1)

    print(f"\n[+] SUCCESS: Finished processing. Total available songs: {saved_count}/{len(playlist_items)}.")


if __name__ == "__main__":
    scrape_playlist()
