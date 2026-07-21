import os
import re
import json
import time
from pathlib import Path
import lyricsgenius

# Absolute path resolution
# Current file: <ROOT>/ug-scraper/fetch_lyrics.py
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

PLAYLIST_PATH = ROOT_DIR / "playlist.json"
OUTPUT_DIR = CURRENT_DIR / "songs"

# Retrieve Genius Access Token from Secrets
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_genius_lyrics(raw_text: str) -> str:
    """Removes Genius-specific metadata artifacts (headers, footers, embed tags)."""
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    
    # Strip typical Genius metadata from the first line if present
    if lines and "Lyrics" in lines[0]:
        lines[0] = re.sub(r'.*?Lyrics', '', lines[0])

    text = "\n".join(lines)
    # Remove trailing 'Embed' / numeric tag appended by Genius
    text = re.sub(r'\d*Embed$', '', text)
    
    return text.strip()


def load_playlist() -> list:
    """Loads and normalizes track data from root playlist.json."""
    if not PLAYLIST_PATH.exists():
        print(f"[-] CRITICAL ERROR: Target playlist file not found at path: {PLAYLIST_PATH}")
        return []

    try:
        with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Handle both raw arrays [{...}] and wrapped objects {"items": [{...}]}
            if isinstance(data, dict):
                tracks = data.get("items", []) or data.get("tracks", [])
            else:
                tracks = data
                
            return tracks
    except json.JSONDecodeError as e:
        print(f"[-] CRITICAL ERROR: Failed to parse {PLAYLIST_PATH.name}: {e}")
        return []


def main():
    if not GENIUS_ACCESS_TOKEN:
        print("[-] CRITICAL ERROR: GENIUS_ACCESS_TOKEN environment variable is missing.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tracks = load_playlist()
    if not tracks:
        print("[-] Aborting execution: No valid tracks found in playlist.")
        return

    # Initialize Genius API client
    genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)
    genius.verbose = False
    genius.remove_section_headers = False  # Retains structural tags like [Verse], [Chorus]

    print(f"[+] Successfully loaded {len(tracks)} tracks from root playlist.json. Starting pipeline...\n")

    saved_count = 0
    for idx, track in enumerate(tracks, 1):
        # Supports multiple naming conventions (e.g., 'artist' vs 'artist_name')
        artist = track.get("artist") or track.get("artist_name") or "Unknown Artist"
        title = track.get("title") or track.get("song_name") or track.get("track_name") or "Unknown Title"

        filename = sanitize_filename(f"{artist} - {title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(tracks)}] Querying: {artist} - {title}")

        if filepath.exists():
            print(f"  [➜] Skip: Target file already exists -> {filename}")
            saved_count += 1
            continue

        try:
            song = genius.search_song(title, artist)
            if song and song.lyrics:
                cleaned_lyrics = clean_genius_lyrics(song.lyrics)
                
                with open(filepath, "w", encoding="utf-8") as out:
                    out.write(f"Artist: {artist}\nTitle: {title}\n")
                    out.write("=" * 50 + "\n\n")
                    out.write(cleaned_lyrics)

                saved_count += 1
                print(f"  [✓] Successfully saved -> {filename}")
            else:
                print(f"  [✗] Lyrics unavailable on Genius for: {artist} - {title}")

        except Exception as e:
            print(f"  [!] Genius API Exception on {artist} - {title}: {e}")

        # Throttling to respect Genius API rate limits
        time.sleep(1)

    print(f"\n[+] PIPELINE COMPLETE: Processed {saved_count}/{len(tracks)} lyric files in {OUTPUT_DIR.name}/.")


if __name__ == "__main__":
    main()
