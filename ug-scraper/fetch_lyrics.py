import os
import re
import json
import time
from pathlib import Path
import lyricsgenius

CURRENT_DIR = Path(__file__).resolve().parent

# Check local subfolder first, then fallback to root
LOCAL_PLAYLIST = CURRENT_DIR / "playlist.json"
ROOT_PLAYLIST = CURRENT_DIR.parent / "playlist.json"
PLAYLIST_PATH = LOCAL_PLAYLIST if LOCAL_PLAYLIST.exists() else ROOT_PLAYLIST

OUTPUT_DIR = CURRENT_DIR / "songs"
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_genius_lyrics(raw_text: str) -> str:
    if not raw_text:
        return ""
    lines = raw_text.splitlines()
    if lines and "Lyrics" in lines[0]:
        lines[0] = re.sub(r'.*?Lyrics', '', lines[0])
    text = "\n".join(lines)
    text = re.sub(r'\d*Embed$', '', text)
    return text.strip()


def load_playlist() -> list:
    if not PLAYLIST_PATH.exists():
        print(f"[-] CRITICAL ERROR: Target playlist file not found at: {PLAYLIST_PATH}")
        raise FileNotFoundError(f"Missing playlist.json at {PLAYLIST_PATH}")

    print(f"[+] Reading playlist from: {PLAYLIST_PATH}")
    try:
        with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                # Try common keys
                for key in ["items", "tracks", "songs", "data", "playlist"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                
                # If dictionary values are lists, return the first list found
                for val in data.values():
                    if isinstance(val, list):
                        return val

            raise ValueError("Could not locate a valid list of tracks in playlist.json")

    except json.JSONDecodeError as e:
        print(f"[-] CRITICAL ERROR: Failed to parse {PLAYLIST_PATH.name}: {e}")
        raise e


def main():
    if not GENIUS_ACCESS_TOKEN:
        print("[-] CRITICAL ERROR: GENIUS_ACCESS_TOKEN environment variable is missing.")
        raise ValueError("Missing GENIUS_ACCESS_TOKEN environment secret.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tracks = load_playlist()
    print(f"[+] Loaded {len(tracks)} tracks. Initializing Genius API client...\n")

    if not tracks:
        print("[-] WARNING: 0 tracks loaded. Please check structure of playlist.json.")
        return

    genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)
    genius.verbose = False
    genius.remove_section_headers = False
    genius.skip_non_songs = True

    saved_count = 0
    for idx, track in enumerate(tracks, 1):
        # Flexible key extraction
        artist = (
            track.get("artist") 
            or track.get("artist_name") 
            or track.get("performer") 
            or "Unknown Artist"
        )
        title = (
            track.get("title") 
            or track.get("song_name") 
            or track.get("track_name") 
            or "Unknown Title"
        )

        filename = sanitize_filename(f"{artist} - {title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(tracks)}] Searching Genius: {artist} - {title}")

        if filepath.exists():
            print(f"  [➜] Skipping: File already exists -> {filename}")
            saved_count += 1
            continue

        try:
            song = genius.search_song(title, artist)
            
            # Fallback search by title only if query with artist failed
            if not song:
                song = genius.search_song(f"{artist} {title}")

            if song and song.lyrics:
                cleaned = clean_genius_lyrics(song.lyrics)

                with open(filepath, "w", encoding="utf-8") as out:
                    out.write(f"Artist: {artist}\nTitle: {title}\n")
                    if "key" in track:
                        out.write(f"Key: {track['key']}\n")
                    out.write("=" * 50 + "\n\n")
                    out.write(cleaned)

                saved_count += 1
                print(f"  [✓] Successfully saved -> {filename}")
            else:
                print(f"  [✗] Lyrics not found on Genius for: {artist} - {title}")

        except Exception as e:
            print(f"  [!] Genius API Error on {artist} - {title}: {e}")

        time.sleep(1)

    print(f"\n[+] PIPELINE COMPLETE: Saved {saved_count}/{len(tracks)} lyric files in {OUTPUT_DIR.name}/.")


if __name__ == "__main__":
    main()
