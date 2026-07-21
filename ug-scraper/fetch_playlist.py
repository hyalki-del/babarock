import os
import re
import json
import requests
from bs4 import BeautifulSoup

# Direct URL to your shared Ultimate Guitar playlist
PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"
SONGS_DIR = "./songs"

os.makedirs(SONGS_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def sanitize_filename(name: str) -> str:
    """Creates filesystem-safe slugs (e.g. 'Hotel California!' -> 'hotel-california')."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-')

def fetch_playlist_tabs() -> list:
    """Scrapes the shared playlist page and extracts song metadata."""
    print(f"Fetching playlist from UG: {PLAYLIST_URL}")
    res = requests.get(PLAYLIST_URL, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"Failed to load playlist page. Status code: {res.status_code}")

    soup = BeautifulSoup(res.text, 'html.parser')
    js_store = soup.find('script', class_='js-store')
    
    if not js_store or not js_store.string:
        raise Exception("Could not find window.UG_STORE.page data on the page.")

    data = json.loads(js_store.string)
    
    # Locate tabs array within UG JSON structure
    page_data = data.get('store', {}).get('page', {}).get('data', {})
    
    # Shared playlists store items in 'songbook' -> 'tabs' or 'list'
    tabs_data = page_data.get('songbook', {}).get('tabs', [])
    if not tabs_data and 'list' in page_data:
        tabs_data = page_data['list']

    extracted_songs = []
    for item in tabs_data:
        tab_info = item.get('tab', item)
        artist = tab_info.get('artist_name', 'Unknown Artist')
        title = tab_info.get('song_name', 'Unknown Title')
        tab_url = tab_info.get('tab_url', '')

        if tab_url:
            extracted_songs.append({
                "artist": artist,
                "title": title,
                "url": tab_url
            })

    print(f"Extracted {len(extracted_songs)} songs from playlist.")
    return extracted_songs

def fetch_ug_tab_content(tab_url: str) -> str | None:
    """Extracts raw chords/lyrics text block from an individual song page."""
    try:
        res = requests.get(tab_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, 'html.parser')
        js_store = soup.find('script', class_='js-store')
        
        if js_store and js_store.string:
            data = json.loads(js_store.string)
            content = data['store']['page']['data']['tab_view']['wiki_tab']['content']
            
            # Strip UG formatting tags ([ch]Am[/ch] -> Am)
            cleaned = re.sub(r'\[\/?ch\]', '', content)
            cleaned = re.sub(r'\[\/?tab\]', '', cleaned)
            return cleaned
    except Exception as e:
        print(f"Error fetching tab from {tab_url}: {e}")
        return None

def main():
    try:
        raw_songs = fetch_playlist_tabs()
    except Exception as e:
        print(f"Error: {e}")
        return

    playlist_output = []

    for song in raw_songs:
        artist = song['artist']
        title = song['title']
        song_url = song['url']

        slug = f"{sanitize_filename(artist)}-{sanitize_filename(title)}"
        file_path = f"songs/{slug}.txt"

        # Incremental fetch: only download if missing
        if not os.path.exists(file_path):
            print(f"Downloading lyrics: {artist} - {title}")
            lyrics_text = fetch_ug_tab_content(song_url)
            
            if lyrics_text:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"{artist} - {title}\n{'=' * 40}\n\n{lyrics_text}")
            else:
                print(f"Failed to fetch lyrics for {artist} - {title}")
        
        playlist_output.append({
            "artist": artist,
            "title": title,
            "url": song_url,
            "file": file_path
        })

    # Save to root playlist.json
    with open("playlist.json", "w", encoding="utf-8") as f:
        json.dump(playlist_output, f, indent=2, ensure_ascii=False)

    print("Pipeline finished successfully. 'playlist.json' updated.")

if __name__ == "__main__":
    main()
