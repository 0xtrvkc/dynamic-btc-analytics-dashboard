import json, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHART_URL    = "https://www.blockchain.com/explorer/charts/mvrv"
MVRV_API     = "https://api.blockchain.info/charts/mvrv?timespan=all&sampled=false&format=json"
PRICE_API    = "https://api.blockchain.info/charts/market-price?timespan=all&sampled=false&format=json"
OUT_FILE     = Path("mvrv.json")

def normalize_values(values: list) -> list:
    """Seconds → milliseconds, drop nulls."""
    result = []
    for point in values:
        x = point.get("x")
        y = point.get("y")
        if x is None or y is None:
            continue
        x_ms = x * 1000 if x < 1_000_000_000_000 else x
        result.append({"x": x_ms, "y": y})
    return result

async def fetch_json(page, url: str) -> dict:
    """Use the live browser context to fetch a JSON API URL (inherits cookies/session)."""
    result = await page.evaluate(f"""
        async () => {{
            const r = await fetch("{url}", {{
                headers: {{ "Accept": "application/json" }}
            }});
            if (!r.ok) throw new Error("HTTP " + r.status);
            return await r.json();
        }}
    """)
    return result

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        page = await context.new_page()

        # Load the page first so the browser has a valid session/cookies
        print("Opening page...")
        await page.goto(CHART_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Now fetch both metrics directly from the API using the live browser context
        print("Fetching MVRV ratio from API...")
        try:
            mvrv_raw = await fetch_json(page, MVRV_API)
            mvrv_values = normalize_values(mvrv_raw.get("values", []))
            print(f"  ✓ {len(mvrv_values)} MVRV points")
        except Exception as e:
            print(f"  ✗ MVRV fetch failed: {e}")
            mvrv_values = []

        print("Fetching market-price from API...")
        try:
            price_raw = await fetch_json(page, PRICE_API)
            price_values = normalize_values(price_raw.get("values", []))
            print(f"  ✓ {len(price_values)} price points")
        except Exception as e:
            print(f"  ✗ Price fetch failed: {e}")
            price_values = []

        await browser.close()

        if not mvrv_values and not price_values:
            raise RuntimeError("Both fetches failed. The API may have changed.")

        if not mvrv_values:
            print("WARNING: MVRV ratio empty — MVRV charts will be blank.")
        if not price_values:
            print("WARNING: Market-price empty — price overlay will be blank.")

        output = {
            "metric1":      "mvrv",
            "metric2":      "market-price",
            "mvrv":         mvrv_values,
            "market-price": price_values,
            "type":         "linear",
            "average":      "1d",
            "timespan":     "all",
        }
        OUT_FILE.write_text(json.dumps(output, separators=(",", ":")))

        size = OUT_FILE.stat().st_size
        print(f"\nSaved {OUT_FILE} ({size:,} bytes)")
        print(f"  mvrv points:         {len(mvrv_values)}")
        print(f"  market-price points: {len(price_values)}")

asyncio.run(main())
