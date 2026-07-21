import os
import re
import json
import urllib.parse
import requests

# Constants & Paths
PLAYLIST_FILE = "playlist.json"
SONGS_DIR = "./songs"
LRCLIB_API_URL = "https://lrclib.net/api/search"

# Ensure songs output directory exists
os.makedirs(SONGS_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'BandManagementApp/1.0 (https://github.com/)'
}

def sanitize_filename(name: str) -> str:
    """Creates a filesystem-safe slug (e.g. 'Hotel California!' -> 'hotel-california')."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-')

def fetch_lyrics_from_lrclib(title: str, artist: str) -> str | None:
    """Queries LRCLIB REST API for plain or synced lyrics."""
    params = {
        'track_name': title,
        'artist_name': artist
    }
    
    try:
        response = requests.get(LRCLIB_API_URL, params=params, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            print(f"  -> HTTP {response.status_code} received from LRCLIB.")
            return None

        results = response.json()
        if not results or not isinstance(results, list):
            # Fallback search query if exact field matching yields no results
            fallback_params = {'q': f"{title} {artist}"}
            fallback_res = requests.get(LRCLIB_API_URL, params=fallback_params, headers=HEADERS, timeout=10)
            if fallback_res.status_code == 200:
                results = fallback_res.json()

        if not results:
            return None

        # Prefer plain lyrics, fallback to synced lyrics
        for item in results:
            plain_lyrics = item.get('plainLyrics')
            if plain_lyrics and plain_lyrics.strip():
                return plain_lyrics.strip()

            synced_lyrics = item.get('syncedLyrics')
            if synced_lyrics and synced_lyrics.strip():
                # Strip LRC timestamp markers (e.g., [00:12.34]) for clean plain text display
                cleaned = re.sub(r'\[\d+:\d+\.\d+\]\s*', '', synced_lyrics)
                return cleaned.strip()

    except Exception as e:
        print(f"  -> Exception querying LRCLIB: {e}")

    return None

def main():
    if not os.path.exists(PLAYLIST_FILE):
        print(f"Error: Could not find '{PLAYLIST_FILE}' in root folder.")
        return

    # 1. Load existing playlist JSON
    with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
        try:
            playlist_data = json.load(f)
        except Exception as e:
            print(f"Error parsing {PLAYLIST_FILE}: {e}")
            return

    if not isinstance(playlist_data, list):
        print(f"Error: {PLAYLIST_FILE} must contain a JSON array of songs.")
        return

    print(f"Loaded {len(playlist_data)} songs from {PLAYLIST_FILE}.")

    updated_playlist = []
    download_count = 0

    # 2. Process each track
    for song in playlist_data:
        title = song.get('title', song.get('name', 'Unknown Title'))
        artist = song.get('artist', 'Unknown Artist')
        
        slug = f"{sanitize_filename(artist)}-{sanitize_filename(title)}"
        file_path = f"songs/{slug}.txt"

        # Check if lyrics file exists already (incremental caching)
        if not os.path.exists(file_path):
            print(f"Fetching lyrics for: '{title}' by '{artist}'...")
            lyrics = fetch_lyrics_from_lrclib(title, artist)

            if lyrics:
                header = f"{artist} - {title}\n{'=' * 40}\n\n"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(header + lyrics)
                print(f"  -> Created {file_path}")
                download_count += 1
            else:
                # Place a clear fallback notice if no lyrics exist on LRCLIB
                header = f"{artist} - {title}\n{'=' * 40}\n\nLyrics not found on LRCLIB."
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(header)
                print(f"  -> No lyrics found on LRCLIB for '{title}'. Created placeholder file.")
        else:
            print(f"Skipping (already exists): {file_path}")

        # Explicitly map file property into the schema
        song['file'] = file_path
        updated_playlist.append(song)

    # 3. Write updated records back to playlist.json
    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_playlist, f, indent=2, ensure_ascii=False)

    print(f"\nCompleted! Downloaded {download_count} new song files.")
    print(f"Successfully updated '{PLAYLIST_FILE}'.")

if __name__ == "__main__":
    main()
