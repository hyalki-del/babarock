import os
import re
import json
import requests
from bs4 import BeautifulSoup

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"
SONGS_DIR = "./songs"

os.makedirs(SONGS_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

def sanitize_filename(name: str) -> str:
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-')

def find_tabs_recursively(obj):
    """Recursively traverses JSON to find array containing song/tab objects."""
    if isinstance(obj, dict):
        # Look for standard UG track keys
        for key in ['tabs', 'list', 'items', 'songs']:
            if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
                # Validate that list items look like tab entries
                first = obj[key][0]
                if isinstance(first, dict) and ('tab' in first or 'artist_name' in first or 'tab_url' in first or 'song_name' in first):
                    return obj[key]
        
        for v in obj.values():
            result = find_tabs_recursively(v)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_tabs_recursively(item)
            if result:
                return result
    return []

def fetch_playlist_tabs() -> list:
    print(f"Connecting to UG Playlist: {PLAYLIST_URL}")
    res = requests.get(PLAYLIST_URL, headers=HEADERS)
    print(f"HTTP Response Status: {res.status_code}")
    
    if res.status_code != 200:
        raise Exception(f"HTTP {res.status_code} Error connecting to Ultimate Guitar.")

    soup = BeautifulSoup(res.text, 'html.parser')
    js_store = soup.find('script', class_='js-store')
    
    if not js_store or not js_store.string:
        raise Exception("Could not find 'js-store' script block in UG HTML response.")

    print("Found 'js-store' data block. Parsing JSON...")
    data = json.loads(js_store.string)
    
    # Use recursive deep-search to guarantee finding the track list
    tabs_data = find_tabs_recursively(data)
    print(f"Extracted {len(tabs_data)} tracks from JSON payload.")

    extracted_songs = []
    for item in tabs_data:
        tab_info = item.get('tab', item) if isinstance(item, dict) else {}
        artist = tab_info.get('artist_name', 'Unknown Artist')
        title = tab_info.get('song_name', 'Unknown Title')
        tab_url = tab_info.get('tab_url', '')

        if tab_url:
            extracted_songs.append({
                "artist": artist,
                "title": title,
                "url": tab_url
            })

    return extracted_songs

def fetch_ug_tab_content(tab_url: str) -> str | None:
    try:
        res = requests.get(tab_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, 'html.parser')
        js_store = soup.find('script', class_='js-store')
        
        if js_store and js_store.string:
            data = json.loads(js_store.string)
            # Fetch wiki_tab content recursively or directly
            page = data.get('store', {}).get('page', {}).get('data', {})
            content = page.get('tab_view', {}).get('wiki_tab', {}).get('content', '')
            
            if not content:
                # Alternative nested lookup
                wiki_tab = find_tabs_recursively(data)
            
            cleaned = re.sub(r'\[\/?ch\]', '', content)
            cleaned = re.sub(r'\[\/?tab\]', '', cleaned)
            return cleaned
    except Exception as e:
        print(f"Exception fetching tab content from {tab_url}: {e}")
        return None

def main():
    try:
        raw_songs = fetch_playlist_tabs()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return

    if not raw_songs:
        print("ERROR: No songs could be parsed from playlist. Please inspect logs.")
        return

    playlist_output = []

    for song in raw_songs:
        artist = song['artist']
        title = song['title']
        song_url = song['url']

        slug = f"{sanitize_filename(artist)}-{sanitize_filename(title)}"
        file_path = f"songs/{slug}.txt"

        if not os.path.exists(file_path):
            print(f"Downloading lyrics: {artist} - {title}")
            lyrics_text = fetch_ug_tab_content(song_url)
            
            if lyrics_text:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"{artist} - {title}\n{'=' * 40}\n\n{lyrics_text}")
                print(f"  -> Created {file_path}")
            else:
                print(f"  -> Warning: Failed to extract lyrics text for {artist} - {title}")
        else:
            print(f"Skipping (already exists): {file_path}")
        
        playlist_output.append({
            "artist": artist,
            "title": title,
            "url": song_url,
            "file": file_path
        })

    with open("playlist.json", "w", encoding="utf-8") as f:
        json.dump(playlist_output, f, indent=2, ensure_ascii=False)

    print(f"\nSUCCESS: Updated playlist.json with {len(playlist_output)} items.")

if __name__ == "__main__":
    main()
