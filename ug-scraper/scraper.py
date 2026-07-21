import os
import re
import json
import time
from playwright.sync_api import sync_playwright

# Core Configuration
PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

# Ensure output path is always locked relative to this script inside ug-scraper/songs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "songs")

def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def extract_ug_store(page) -> dict:
    """
    Extracts the global application state object (window.UG_STORE.page) 
    embedded by Ultimate Guitar's React hydration engine.
    """
    try:
        store_data = page.evaluate("window.UG_STORE.page")
        return store_data if store_data else {}
    except Exception as e:
        print(f"[-] Failed to extract window.UG_STORE: {e}")
        return {}

def scrape_playlist():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        # Launch headless Chromium with standard desktop User-Agent to bypass basic checks
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"[+] Navigating to shared playlist: {PLAYLIST_URL}")
        page.goto(PLAYLIST_URL, wait_until="networkidle")

        store = extract_ug_store(page)
        
        try:
            playlist_items = store['data']['playlist']['items']
        except KeyError:
            print("[-] Could not parse playlist items from state object.")
            browser.close()
            return

        print(f"[+] Found {len(playlist_items)} items in playlist.")

        for idx, item in enumerate(playlist_items, 1):
            song_url = item.get('tab_url')
            artist_name = item.get('artist_name', 'Unknown Artist')
            song_title = item.get('song_name', 'Unknown Song')

            if not song_url:
                continue

            filename = sanitize_filename(f"{artist_name} - {song_title}.txt")
            filepath = os.path.join(OUTPUT_DIR, filename)

            print(f"[{idx}/{len(playlist_items)}] Processing: {artist_name} - {song_title}")
            
            tab_page = context.new_page()
            try:
                tab_page.goto(song_url, wait_until="networkidle")
                tab_store = extract_ug_store(tab_page)
                
                tab_content = tab_store.get('data', {}).get('tab_view', {}).get('wiki_tab', {}).get('content', '')

                if tab_content:
                    # Clean up Ultimate Guitar markup formatting (e.g., [ch]C[/ch] -> C)
                    cleaned_content = re.sub(r'\[\/?(ch|tab|chords)\]', '', tab_content)
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)
                    print(f"  [✓] Saved -> {filepath}")
                else:
                    print(f"  [!] No content found for {song_title}.")

            except Exception as e:
                print(f"  [✗] Error processing {song_url}: {e}")
            finally:
                tab_page.close()
                time.sleep(1.5)  # Rate limiting safety delay

        browser.close()

if __name__ == "__main__":
    scrape_playlist()
