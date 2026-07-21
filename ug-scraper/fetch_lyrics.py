import os
import re
import json
import time
import traceback
from pathlib import Path
import lyricsgenius

# Precise path calculations relative to execution subfolder
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

PLAYLIST_PATH = ROOT_DIR / "playlist.json"
OUTPUT_DIR = CURRENT_DIR / "songs"
ERROR_LOG_PATH = CURRENT_DIR / "debug_execution_error.log"

GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def clean_genius_lyrics(raw_text: str) -> str:
    """Strips Genius metadata artifacts and trailing embed tags."""
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    if lines and "Lyrics" in lines[0]:
        lines[0] = re.sub(r'.*?Lyrics', '', lines[0])

    text = "\n".join(lines)
    text = re.sub(r'\d*Embed$', '', text)
    return text.strip()


def load_playlist() -> list:
    """Loads and parses the root-level playlist.json file."""
    if not PLAYLIST_PATH.exists():
        msg = f"Target playlist file missing at expected path: {PLAYLIST_PATH}"
        print(f"[-] {msg}")
        raise FileNotFoundError(msg)

    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict):
            return data.get("items", []) or data.get("tracks", [])
        return data


def main():
    try:
        if not GENIUS_ACCESS_TOKEN:
            msg = "GENIUS_ACCESS_TOKEN secret is empty or missing from environment."
            print(f"[-] {msg}")
            raise ValueError(msg)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        tracks = load_playlist()
        if not tracks:
            msg = "playlist.json parsed successfully but contained 0 track entries."
            print(f"[-] {msg}")
            raise ValueError(msg)

        genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)
        genius.verbose = False
        genius.remove_section_headers = False

        print(f"[+] Loaded {len(tracks)} tracks from {PLAYLIST_PATH.name}. Querying API...\n")

        saved_count = 0
        for idx, track in enumerate(tracks, 1):
            artist = track.get("artist") or track.get("artist_name") or "Unknown Artist"
            title = track.get("title") or track.get("song_name") or track.get("track_name") or "Unknown Title"

            filename = sanitize_filename(f"{artist} - {title}.txt")
            filepath = OUTPUT_DIR / filename

            print(f"[{idx}/{len(tracks)}] Processing: {artist} - {title}")

            if filepath.exists():
                print(f"  [➜] Skipping (File already exists): {filename}")
                saved_count += 1
                continue

            try:
                song = genius.search_song(title, artist)
                if song and song.lyrics:
                    cleaned = clean_genius_lyrics(song.lyrics)
                    with open(filepath, "w", encoding="utf-8") as out:
                        out.write(f"Artist: {artist}\nTitle: {title}\n")
                        out.write("=" * 50 + "\n\n")
                        out.write(cleaned)

                    saved_count += 1
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [✗] Lyrics not found on Genius for: {artist} - {title}")

            except Exception as e:
                print(f"  [!] Exception during song query ({artist} - {title}): {e}")

            time.sleep(1)

        print(f"\n[+] PIPELINE COMPLETED: Processed {saved_count}/{len(tracks)} files successfully.")

    except Exception as err:
        # Dump execution failure trace to file for GitHub Action Artifact uploading
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"Execution Error: {str(err)}\n\n")
            f.write(traceback.format_exc())
        print(f"[!] Critical Error logged to: {ERROR_LOG_PATH.name}")
        raise err


if __name__ == "__main__":
    main()
