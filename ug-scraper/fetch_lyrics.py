import os
import re
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Resolve directory paths
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

# Check for playlist.json at repository root first, then local directory
ROOT_PLAYLIST = ROOT_DIR / "playlist.json"
LOCAL_PLAYLIST = CURRENT_DIR / "playlist.json"

PLAYLIST_PATH = ROOT_PLAYLIST if ROOT_PLAYLIST.exists() else LOCAL_PLAYLIST
OUTPUT_DIR = CURRENT_DIR / "songs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def sanitize_filename(name: str) -> str:
    """Sanitizes strings to create valid OS filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def load_playlist() -> list:
    """Loads track data from root or local playlist.json."""
    if not PLAYLIST_PATH.exists():
        print(f"[-] CRITICAL ERROR: Target playlist file not found at: {PLAYLIST_PATH}")
        raise FileNotFoundError(f"Missing playlist.json at {PLAYLIST_PATH}")

    print(f"[+] Reading playlist data from: {PLAYLIST_PATH}")
    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ["items", "tracks", "songs", "data", "playlist"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            for val in data.values():
                if isinstance(val, list):
                    return val

    raise ValueError("Could not extract a valid array of songs from playlist.json")


def clean_ug_content(raw_content: str) -> str:
    """Strips UG BBCode tags while preserving readable text and chords."""
    if not raw_content:
        return ""
    # Strip [ch]Am[/ch] tags to just show chord names
    content = re.sub(r'\[ch\](.*?)\[/ch\]', r'\1', raw_content)
    # Strip [tab] and [/tab] structural tags
    content = re.sub(r'\[/?tab\]', '', content)
    return content.strip()


def fetch_tab_from_ug(artist: str, title: str) -> str:
    """Searches Ultimate Guitar and extracts the raw chord/lyric text."""
    query = f"{artist} {title}"
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://www.ultimate-guitar.com/search.php?search_type=title&value={encoded_query}"

    try:
        # Step 1: Perform search
        req = urllib.request.Request(search_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")

        match = re.search(r'class="js-store"\s+data-content="([^"]+)"', html)
        if not match:
            return ""

        raw_json_str = match.group(1).replace("&quot;", '"').replace("&amp;", "&")
        search_data = json.loads(raw_json_str)

        results = search_data.get("store", {}).get("page", {}).get("data", {}).get("results", [])
        if not results:
            return ""

        # Step 2: Prioritize Chords or Lyrics tab types
        tab_url = None
        for item in results:
            if item.get("type") in ["Chords", "Lyrics", "Ukulele"]:
                tab_url = item.get("tab_url")
                break

        if not tab_url and results:
            tab_url = results[0].get("tab_url")

        if not tab_url:
            return ""

        # Step 3: Fetch the specific Tab page
        tab_req = urllib.request.Request(tab_url, headers=HEADERS)
        with urllib.request.urlopen(tab_req, timeout=12) as tab_resp:
            tab_html = tab_resp.read().decode("utf-8", errors="ignore")

        tab_match = re.search(r'class="js-store"\s+data-content="([^"]+)"', tab_html)
        if not tab_match:
            return ""

        tab_json_str = tab_match.group(1).replace("&quot;", '"').replace("&amp;", "&")
        tab_data = json.loads(tab_json_str)

        wiki_tab = (
            tab_data.get("store", {})
            .get("page", {})
            .get("data", {})
            .get("tab_view", {})
            .get("wiki_tab", {})
        )

        raw_content = wiki_tab.get("content", "")
        return clean_ug_content(raw_content)

    except Exception as e:
        print(f"  [!] UG Engine Error for '{artist} - {title}': {e}")
        return ""


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tracks = load_playlist()

    print(f"[+] Successfully loaded {len(tracks)} tracks from {PLAYLIST_PATH.name}.\n")
    saved_count = 0

    for idx, track in enumerate(tracks, 1):
        artist = track.get("artist") or track.get("artist_name") or "Unknown Artist"
        title = track.get("title") or track.get("song_name") or "Unknown Title"
        key = track.get("key", "N/A")

        filename = sanitize_filename(f"{artist} - {title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(tracks)}] Searching UG: {artist} - {title}")

        if filepath.exists() and filepath.stat().st_size > 0:
            print(f"  [➜] Skipping: File already exists -> {filename}")
            saved_count += 1
            continue

        tab_content = fetch_tab_from_ug(artist, title)

        if tab_content:
            with open(filepath, "w", encoding="utf-8") as out:
                out.write(f"Artist: {artist}\nTitle: {title}\nKey: {key}\n")
                out.write("=" * 50 + "\n\n")
                out.write(tab_content)

            saved_count += 1
            print(f"  [✓] Successfully saved -> {filename}")
        else:
            print(f"  [✗] Could not retrieve tab/lyrics from UG for: {artist} - {title}")

        time.sleep(1.2)  # Courteous delay between requests

    print(f"\n[+] PIPELINE COMPLETE: Saved {saved_count}/{len(tracks)} track files in {OUTPUT_DIR.name}/.")


if __name__ == "__main__":
    main()
