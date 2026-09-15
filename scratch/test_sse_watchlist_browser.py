import asyncio
import os
import subprocess
import time
import urllib.request
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/root/.gemini/antigravity/brain/a3e6a601-d0bd-4ba3-b792-65f243d7eebb"

async def run_browser_verification():
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    server_proc = subprocess.Popen(
        ["python3", "-c", """
import uvicorn
from quantizedalert.cli import _ctx
from quantizedalert.dashboard.app import build_app
pcfg, store, _ = _ctx()
app = build_app(pcfg, store)
uvicorn.run(app, host='127.0.0.1', port=8797, log_level='error')
"""],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll until server responds
    for attempt in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8797/api/v1/macro/regime", timeout=1.0) as r:
                if r.status == 200:
                    print(f"Server ready on attempt {attempt}")
                    break
        except Exception:
            time.sleep(0.5)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 960})

            print("Navigating to http://127.0.0.1:8797/w/alpha_gems...")
            await page.goto("http://127.0.0.1:8797/w/alpha_gems", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)

            # Check that personal watchlist section is present
            print("Checking Personal Live Watchlist section...")
            watchlist_sec = page.locator("#custom-watchlist-section")
            assert await watchlist_sec.is_visible(), "Custom watchlist section not visible"

            # Add NVDA
            print("Adding NVDA to watchlist...")
            input_box = page.locator("#add-watchlist-input")
            await input_box.fill("NVDA")
            add_btn = page.locator("button:has-text('+ ADD')")
            await add_btn.click()
            await page.wait_for_timeout(1000)

            # Check NVDA exists
            nvda_badge = page.locator("#custom-watchlist-items .asset-code:has-text('NVDA')")
            assert await nvda_badge.is_visible(), "NVDA badge not visible in watchlist"

            # Add TSLA
            print("Adding TSLA to watchlist...")
            await input_box.fill("TSLA")
            await add_btn.click()
            await page.wait_for_timeout(1000)

            # Check TSLA exists
            tsla_badge = page.locator("#custom-watchlist-items .asset-code:has-text('TSLA')")
            assert await tsla_badge.is_visible(), "TSLA badge not visible in watchlist"

            # Test 1-click trade button on NVDA
            print("Clicking TRADE button on NVDA...")
            trade_btn = page.locator("#custom-watchlist-items div:has-text('NVDA') button:has-text('TRADE')")
            await trade_btn.click()
            await page.wait_for_timeout(500)

            # Verify order modal is open with NVDA
            modal = page.locator("#order-modal")
            is_active = await modal.evaluate("el => el.classList.contains('active')")
            assert is_active, "Order modal did not open from watchlist"
            modal_ticker = await page.locator("#order-ticker").input_value()
            assert "NVDA" in modal_ticker, f"Modal ticker is {modal_ticker}, expected NVDA"
            print("Order modal successfully pre-populated with NVDA!")

            # Close modal directly
            await page.evaluate("closeOrderModalDirect()")
            await page.wait_for_timeout(500)

            # Scroll to make custom watchlist prominently visible
            await watchlist_sec.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)

            # Capture screenshot
            screenshot_path = os.path.join(ARTIFACT_DIR, "iteration7_live_stream_watchlist.png")
            await page.screenshot(path=screenshot_path)
            print(f"Captured screenshot to {screenshot_path}")

            await browser.close()
    finally:
        server_proc.terminate()
        server_proc.wait()

if __name__ == "__main__":
    asyncio.run(run_browser_verification())
