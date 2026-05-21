import json, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHART_URL = "https://www.blockchain.com/explorer/charts/mvrv"
OUT_FILE  = Path("mvrv.json")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        page = await context.new_page()

        captured = {}

        # Intercept every JSON response — grab whichever one contains mvrv data
        async def on_response(response):
            url = response.url
            if "chart" not in url.lower() and "mvrv" not in url.lower():
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                data = await response.json()
                vals = data.get("values") or data.get("mvrv") or []
                if len(vals) > 100:
                    print(f"  ✓ Captured {len(vals)} points from: {url}")
                    captured["data"] = data
                    captured["url"]  = url
            except Exception:
                pass

        page.on("response", on_response)

        print("Opening page (All timeframe)...")
        await page.goto(CHART_URL, wait_until="domcontentloaded", timeout=60000)

        # Click "All" timeframe button
        try:
            await page.get_by_text("All", exact=True).first.click()
            print("Clicked 'All'")
        except Exception as e:
            print(f"Could not click All: {e}")

        # Wait up to 15s for data to arrive
        for i in range(15):
            await asyncio.sleep(1)
            if "data" in captured:
                break
            print(f"  waiting... {i+1}s")

        await browser.close()

        if "data" not in captured:
            raise RuntimeError("No MVRV data captured. The site may have changed its API.")

        OUT_FILE.write_text(json.dumps(captured["data"], separators=(",", ":")))
        print(f"Saved {OUT_FILE} ({OUT_FILE.stat().st_size:,} bytes) from {captured['url']}")

asyncio.run(main())
