import os
import re
import json
import time
from playwright.sync_api import sync_playwright

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "songs")

def sanitize_filename(name: str) -> str:
    """Sanitizes strings for cross-platform filesystem compliance."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def extract_ug_store(page) -> dict:
    """Safely extracts the UG React state tree from window.UG_STORE.page."""
    try:
        # Wait up to 10s for the window.UG_STORE object to populate
        page.wait_for_function("() => window.UG_STORE && window.UG_STORE.page", timeout=10000)
        store_data = page.evaluate("window.UG_STORE.page")
        return store_data if store_data else {}
    except Exception as e:
        print(f"[-] Warning: Failed to extract UG_STORE: {e}")
        return {}

def scrape_playlist():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        # Launch Chromium with anti-detection flags
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        
        # Build realistic context with standard desktop screen & headers
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        
        page = context.new_page()
        page.set_default_timeout(60000) # 60 second timeout limit

        print(f"[+] Navigating to shared playlist: {PLAYLIST_URL}")
        
        try:
            # FIX: Use 'domcontentloaded' instead of 'networkidle' to avoid ad stream timeouts
            page.goto(PLAYLIST_URL, wait_until="domcontentloaded")
            time.sleep(3) # Brief pause for initial hydration
        except Exception as e:
            print(f"[-] Initial page load error: {e}")
            browser.close()
            return

        store = extract_ug_store(page)
        
        try:
            playlist_items = store['data']['playlist']['items']
        except KeyError:
            print("[-] Could not parse playlist items. Main page store layout changed or bot detected.")
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
            tab_page.set_default_timeout(60000)
            
            try:
                # FIX: Use 'domcontentloaded' for individual tab pages
                tab_page.goto(song_url, wait_until="domcontentloaded")
                tab_store = extract_ug_store(tab_page)
                
                tab_content = tab_store.get('data', {}).get('tab_view', {}).get('wiki_tab', {}).get('content', '')

                if tab_content:
                    # Clean up chord brackets [ch]C[/ch] -> C
                    cleaned_content = re.sub(r'\[\/?(ch|tab|chords)\]', '', tab_content)
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)
                    print(f"  [✓] Saved -> {filepath}")
                else:
                    print(f"  [!] No tab content found for {song_title}.")

            except Exception as e:
                print(f"  [✗] Error processing {song_url}: {e}")
            finally:
                tab_page.close()
                time.sleep(1.5)

        browser.close()

if __name__ == "__main__":
    scrape_playlist()
