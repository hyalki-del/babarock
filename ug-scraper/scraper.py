import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PLAYLIST_URL = "https://www.ultimate-guitar.com/user/playlist/shared?h=N4oafAvw08YnD1Pep-gUFb1r"

# Absolute path resolution
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "songs"
DEBUG_FILE = BASE_DIR / "debug_failed_page.html"


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe cross-platform file naming."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def strip_ug_tags(content: str) -> str:
    """Strips Ultimate Guitar BBCode-style chord/tab markup including attributes."""
    return re.sub(r'\[\/?(ch|tab|chords)[^\]]*\]', '', content)


def extract_ug_store(page) -> dict:
    """Safely extracts window.UG_STORE.page from the hydration DOM."""
    try:
        page.wait_for_function("() => window.UG_STORE && window.UG_STORE.page", timeout=20000)
        store_data = page.evaluate("window.UG_STORE.page")
        return store_data if isinstance(store_data, dict) else {}
    except Exception as e:
        print(f"[-] Warning: Failed to extract window.UG_STORE: {e}")
        return {}


def scrape_playlist():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Launch Chromium with anti-detection flags
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--window-size=1920,1080"
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1"
            }
        )

        page = context.new_page()
        page.set_default_timeout(60000)

        # Inject script to override navigator.webdriver before page loads
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        print(f"[+] Navigating to shared playlist: {PLAYLIST_URL}")

        try:
            page.goto(PLAYLIST_URL, wait_until="domcontentloaded")
            time.sleep(3)
        except Exception as e:
            print(f"[-] Initial page load failed: {e}")
            # Save HTML snapshot for artifact inspection
            with open(DEBUG_FILE, "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            sys.exit(1)

        store = extract_ug_store(page)
        playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

        if not playlist_items:
            print("[-] CRITICAL ERROR: No items found in store tree.")
            print("[-] Ultimate Guitar likely blocked the runner or window.UG_STORE layout shifted.")
            
            # Save DOM snapshot to inspect Cloudflare/challenge responses
            with open(DEBUG_FILE, "w", encoding="utf-8") as f:
                f.write(page.content())
                
            browser.close()
            sys.exit(1)  # Force non-zero exit code to alert CI runner

        print(f"[+] Successfully retrieved {len(playlist_items)} items from playlist state.")

        saved_count = 0
        for idx, item in enumerate(playlist_items, 1):
            song_url = item.get('tab_url')
            artist_name = item.get('artist_name', 'Unknown Artist')
            song_title = item.get('song_name', 'Unknown Song')

            if not song_url:
                continue

            filename = sanitize_filename(f"{artist_name} - {song_title}.txt")
            filepath = OUTPUT_DIR / filename

            print(f"[{idx}/{len(playlist_items)}] Processing: {artist_name} - {song_title}")

            tab_page = context.new_page()
            tab_page.set_default_timeout(60000)

            try:
                tab_page.goto(song_url, wait_until="domcontentloaded")
                tab_store = extract_ug_store(tab_page)

                # Fallback check across multiple tab formats
                tab_view = tab_store.get('data', {}).get('tab_view', {})
                tab_content = tab_view.get('wiki_tab', {}).get('content', '') or tab_view.get('tab', {}).get('content', '')

                if tab_content:
                    cleaned_content = strip_ug_tags(tab_content)

                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)
                    
                    saved_count += 1
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [!] No tab text found in state for {song_title}.")

            except Exception as e:
                print(f"  [✗] Error processing {song_url}: {e}")
            finally:
                tab_page.close()
                time.sleep(1.5)

        browser.close()
        print(f"[+] Scraping pipeline finished. Total songs saved: {saved_count}/{len(playlist_items)}")


if __name__ == "__main__":
    scrape_playlist()
    with sync_playwright() as p:
        # Stealth launch configurations for CI/CD runners
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        
        page = context.new_page()
        page.set_default_timeout(60000)

        print(f"[+] Navigating to shared playlist: {PLAYLIST_URL}")
        
        try:
            page.goto(PLAYLIST_URL, wait_until="domcontentloaded")
            time.sleep(3)
        except Exception as e:
            print(f"[-] Initial page load failed: {e}")
            browser.close()
            return

        store = extract_ug_store(page)
        playlist_items = store.get('data', {}).get('playlist', {}).get('items', [])

        if not playlist_items:
            print("[-] No items found in store tree. Ultimate Guitar state tree structure may have shifted or blocked by Cloudflare.")
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
            filepath = OUTPUT_DIR / filename

            print(f"[{idx}/{len(playlist_items)}] Processing: {artist_name} - {song_title}")
            
            tab_page = context.new_page()
            tab_page.set_default_timeout(60000)
            
            try:
                tab_page.goto(song_url, wait_until="domcontentloaded")
                tab_store = extract_ug_store(tab_page)
                
                # Check standard wiki_tab first, then fallback to generic tab content
                tab_view = tab_store.get('data', {}).get('tab_view', {})
                tab_content = tab_view.get('wiki_tab', {}).get('content', '') or tab_view.get('tab', {}).get('content', '')

                if tab_content:
                    cleaned_content = strip_ug_tags(tab_content)
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"Artist: {artist_name}\nTitle: {song_title}\nURL: {song_url}\n")
                        f.write("=" * 50 + "\n\n")
                        f.write(cleaned_content)
                    print(f"  [✓] Saved -> {filename}")
                else:
                    print(f"  [!] No content found for {song_title}.")

            except Exception as e:
                print(f"  [✗] Error processing {song_url}: {e}")
            finally:
                tab_page.close()
                time.sleep(1.5)

        browser.close()

if __name__ == "__main__":
    scrape_playlist()
