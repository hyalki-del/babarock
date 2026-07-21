import os
import re
import json
import time
from pathlib import Path
import lyricsgenius

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

PLAYLIST_PATH = ROOT_DIR / "playlist.json"
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
        raise FileNotFoundError(f"Missing {PLAYLIST_PATH}")

    try:
        with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("items", []) or data.get("tracks", [])
            return data
    except json.JSONDecodeError as e:
        print(f"[-] CRITICAL ERROR: Failed to parse {PLAYLIST_PATH.name}: {e}")
        raise e


def main():
    if not GENIUS_ACCESS_TOKEN:
        print("[-] CRITICAL ERROR: GENIUS_ACCESS_TOKEN environment variable is missing.")
        raise ValueError("Missing GENIUS_ACCESS_TOKEN environment secret.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tracks = load_playlist()
    print(f"[+] Loaded {len(tracks)} tracks from root playlist.json. Querying Genius API...\n")

    genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)
    genius.verbose = False
    genius.remove_section_headers = False

    saved_count = 0
    for idx, track in enumerate(tracks, 1):
        artist = track.get("artist") or track.get("artist_name") or "Unknown Artist"
        title = track.get("title") or track.get("song_name") or "Unknown Title"

        filename = sanitize_filename(f"{artist} - {title}.txt")
        filepath = OUTPUT_DIR / filename

        print(f"[{idx}/{len(tracks)}] Searching Genius: {artist} - {title}")

        if filepath.exists():
            print(f"  [➜] Skipping: File already exists -> {filename}")
            saved_count += 1
            continue

        try:
            song = genius.search_song(title, artist)
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
