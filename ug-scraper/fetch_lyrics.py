import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Path resolution: Script is in ug-scraper/, playlist.json is in root
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

PLAYLIST_PATH = ROOT_DIR / "playlist.json"
OUTPUT_DIR = CURRENT_DIR / "songs"


def sanitize_filename(name: str) -> str:
    """Removes illegal OS characters from filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def fetch_lyrics_from_lrclib(artist: str, title: str) -> str:
    """Queries LRCLIB API directly. Free, keyless, and headless-friendly."""
    # 1. Direct Signature Search
    params = urllib.parse.urlencode({'artist_name': artist, 'track_name': title})
    url = f"https://lrclib.net/api/get?{params}"
    headers = {'User-Agent': 'GitHubActions-LyricsFetcher/2.0'}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get('plainLyrics', '') or data.get('syncedLyrics', '')
    except Exception:
        pass

    # 2. Fuzzy Query Fallback
    search_query = urllib.parse.quote(f"{artist} {title}")
    search_url = f"https://lrclib.net/api/search?q={search_query}"

    try:
        req_search = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req_search, timeout=10) as resp:
            if resp.status == 200:
                results = json.loads(resp.read().decode('utf-8'))
                if results and isinstance(results, list) and len(results) > 0:
                    return results[0].get('plainLyrics', '') or results[0].get('syncedLyrics', '')
    except Exception as e:
        print(f"  [!] Search error for {artist} - {title}: {e}")

    return ""


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not PLAYLIST_PATH.exists():
        print(f"[-] CRITICAL ERROR: Could not find playlist.json at: {PLAYLIST_PATH}")
        raise FileNotFoundError(f"Missing {PLAYLIST_PATH}")

    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        tracks = data.get("items", []) if isinstance(data, dict) else data

    print(f"[+] Loaded {len(tracks)} tracks from root playlist.json. Starting API extraction...\n")

    saved_count = 0
    for idx, track in enumerate(tracks, 1):
        artist = track.get("artist") or track.get("artist_name") or "Unknown Artist"
        title = track.get("title") or track.get("song_name") or "Unknown Title"

        filename = sanitize_filename(f"{artist} - {title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(tracks)}] Processing: {artist} - {title}")

        if filepath.exists():
            print(f"  [➜] Skip: Already exists -> {filename}")
            saved_count += 1
            continue

        lyrics = fetch_lyrics_from_lrclib(artist, title)

        if lyrics:
            with open(filepath, "w", encoding="utf-8") as out:
                out.write(f"Artist: {artist}\nTitle: {title}\n")
                out.write("=" * 50 + "\n\n")
                out.write(lyrics.strip())

            saved_count += 1
            print(f"  [✓] Successfully saved -> {filename}")
        else:
            print(f"  [✗] Lyrics unavailable on LRCLIB.")

        time.sleep(0.5)

    print(f"\n[+] PIPELINE COMPLETE: Saved {saved_count}/{len(tracks)} files in {OUTPUT_DIR.name}/.")


if __name__ == "__main__":
    main()
