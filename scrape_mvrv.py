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
                if len(vals) > 1000:   # "All" has 4000+, 1Y only ~365
                    print(f"  ✓ Captured {len(vals)} points from: {url}")
                    captured["data"] = data
                    captured["url"]  = url
            except Exception:
                pass

        page.on("response", on_response)
        print("Opening page...")
        await page.goto(CHART_URL, wait_until="domcontentloaded", timeout=60000)

        # Small wait for page to settle before clicking
        await asyncio.sleep(3)

        # Click "All" timeframe button
        try:
            await page.get_by_text("All", exact=True).first.click()
            print("Clicked 'All'")
            captured.clear()   # discard any pre-click 1Y data
        except Exception as e:
            print(f"Could not click All: {e}")

        # Wait for data to arrive AND stabilize
        prev_count = 0
        stable_ticks = 0
        for i in range(60):   # up to 60 seconds
            await asyncio.sleep(1)
            current_count = len((captured.get("data") or {}).get("values") or [])
            print(f"  waiting... {i+1}s | points: {current_count}")
            if current_count > 1000:
                if current_count == prev_count:
                    stable_ticks += 1
                    if stable_ticks >= 3:
                        print("  Data stabilized.")
                        break
                else:
                    stable_ticks = 0
            prev_count = current_count

        await browser.close()

        if "data" not in captured:
            raise RuntimeError("No MVRV data captured. The site may have changed its API.")

        OUT_FILE.write_text(json.dumps(captured["data"], separators=(",", ":")))
        print(f"Saved {OUT_FILE} ({OUT_FILE.stat().st_size:,} bytes) from {captured['url']}")

asyncio.run(main())

# --- clean invalid entries (y < 0.44, all-time legitimate bottom) ---
MIN_VALID_Y = 0.44

with open(OUT_FILE) as f:
    data = json.load(f)

# The site may use "values" or "mvrv" as the key
list_key = "values" if "values" in data else "mvrv" if "mvrv" in data else None

if isinstance(data, list):
    original = data
    cleaned  = [e for e in original if e.get("y", 0) >= MIN_VALID_Y]
    result   = cleaned
elif list_key:
    original = data[list_key]
    cleaned  = [e for e in original if e.get("y", 0) >= MIN_VALID_Y]
    result   = {**data, list_key: cleaned}
else:
    original = cleaned = []
    result   = data

removed = len(original) - len(cleaned)
if removed:
    with open(OUT_FILE, "w") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"Removed {removed} invalid entries (y < {MIN_VALID_Y}) from {OUT_FILE}")
else:
    print(f"No invalid entries found (all y >= {MIN_VALID_Y}) — mvrv.json is clean.")
