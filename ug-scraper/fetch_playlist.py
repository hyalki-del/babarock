import os
import re
import json
import requests
from bs4 import BeautifulSoup

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"
SONGS_DIR = "./songs"

os.makedirs(SONGS_DIR, exist_ok=True)

# Extended browser headers to avoid Cloudflare/bot filtering
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def sanitize_filename(name: str) -> str:
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-')

def extract_tabs_from_json(data: dict) -> list:
    """Recursively searches the nested UG store object for tab arrays."""
    # Try direct known key paths
    try:
        page = data.get('store', {}).get('page', {}).get('data', {})
        if 'songbook' in page:
            return page['songbook'].get('tabs', [])
        if 'playlist' in page:
            return page['playlist'].get('tabs', [])
        if 'tabs' in page:
            return page['tabs']
        if 'list' in page:
            return page['list']
    except Exception as e:
        print(f"Key extraction warning: {e}")

    return []

def fetch_playlist_tabs() -> list:
    print(f"Connecting to UG Playlist URL...")
    res = requests.get(PLAYLIST_URL, headers=HEADERS)
    print(f"HTTP Response Status Code: {res.status_code}")
    
    if res.status_code != 200:
        raise Exception(f"UG rejected request with status code {res.status_code}")

    soup = BeautifulSoup(res.text, 'html.parser')
    js_store = soup.find('script', class_='js-store')
    
    if not js_store or not js_store.string:
        # Check if page was blocked by anti-bot captcha
        if "cloudflare" in res.text.lower() or "captcha" in res.text.lower():
            raise Exception("Page request was intercepted by Cloudflare anti-bot check.")
        raise Exception("Could not find 'js-store' script block in HTML response.")

    print("Successfully retrieved 'js-store' raw data block.")
    data = json.loads(js_store.string)
    
    tabs_data = extract_tabs_from_json(data)
    print(f"Found {len(tabs_data)} raw tab items in dataset.")

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
            print(f"  --> HTTP {res.status_code} when opening {tab_url}")
            return None

        soup = BeautifulSoup(res.text, 'html.parser')
        js_store = soup.find('script', class_='js-store')
        
        if js_store and js_store.string:
            data = json.loads(js_store.string)
            content = data['store']['page']['data']['tab_view']['wiki_tab']['content']
            
            cleaned = re.sub(r'\[\/?ch\]', '', content)
            cleaned = re.sub(r'\[\/?tab\]', '', cleaned)
            return cleaned
    except Exception as e:
        print(f"  --> Exception while parsing tab details: {e}")
        return None

def main():
    try:
        raw_songs = fetch_playlist_tabs()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return

    if not raw_songs:
        print("WARNING: No songs were extracted. Check log trace above.")
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
                print(f"  --> Saved {file_path}")
            else:
                print(f"  --> Failed to download content for {artist} - {title}")
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

    print(f"Process completed. Wrote {len(playlist_output)} items into playlist.json.")

if __name__ == "__main__":
    main()
