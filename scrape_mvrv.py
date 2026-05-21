import json, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHART_URL   = "https://www.blockchain.com/explorer/charts/mvrv"
OUT_FILE    = Path("mvrv.json")
MIN_VALID_Y = 0.44   # all-time legitimate MVRV bottom; anything below is bad data
MAX_VALID_Y = 20     # MVRV is never > 20; higher means we grabbed a price chart


def is_mvrv(vals: list) -> bool:
    """Return True only if vals look like real MVRV ratios, not price data."""
    if not vals:
        return False
    y_values = [v.get("y", 0) for v in vals]
    return max(y_values) <= MAX_VALID_Y and len(vals) > 1000


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
                if not is_mvrv(vals):
                    print(f"  ✗ Skipped (not MVRV data, max y={max((v.get('y',0) for v in vals), default=0):.2f}): {url}")
                    return
                print(f"  ✓ Captured {len(vals)} MVRV points from: {url}")
                captured["data"] = data
                captured["vals"] = vals
                captured["url"]  = url
            except Exception:
                pass

        page.on("response", on_response)
        print("Opening page...")
        await page.goto(CHART_URL, wait_until="domcontentloaded", timeout=60000)

        await asyncio.sleep(3)

        try:
            await page.get_by_text("All", exact=True).first.click()
            print("Clicked 'All'")
            captured.clear()   # discard any pre-click data
        except Exception as e:
            print(f"Could not click All: {e}")

        # Wait for MVRV data to arrive and stabilize
        prev_count = 0
        stable_ticks = 0
        for i in range(60):
            await asyncio.sleep(1)
            current_count = len(captured.get("vals") or [])
            print(f"  waiting... {i+1}s | mvrv points: {current_count}")
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

        raw_data = captured["data"]
        vals     = captured["vals"]

        # --- Normalise to the structure index.html expects ---
        # 1. x: convert seconds → milliseconds if needed
        if vals[0].get("x", 0) < 1e12:
            print(f"  Converting x from seconds to milliseconds...")
            for v in vals:
                v["x"] = v["x"] * 1000

        # 2. Build output in the exact shape index.html uses
        out = {
            "metric1":      "mvrv",
            "metric2":      "market-price",
            "mvrv":         vals,
            "market-price": raw_data.get("market-price", []),
            "type":         raw_data.get("type", "linear"),
            "average":      raw_data.get("average", "1d"),
            "timespan":     raw_data.get("timespan", "all"),
        }

        # 3. Strip entries below the all-time legitimate minimum
        original = out["mvrv"]
        cleaned  = [e for e in original if e.get("y", 0) >= MIN_VALID_Y]
        removed  = len(original) - len(cleaned)
        out["mvrv"] = cleaned

        OUT_FILE.write_text(json.dumps(out, separators=(",", ":")))
        print(f"Saved {OUT_FILE} ({OUT_FILE.stat().st_size:,} bytes)")
        if removed:
            print(f"Removed {removed} invalid entries (y < {MIN_VALID_Y})")
        else:
            print("No invalid entries — mvrv.json is clean.")


asyncio.run(main())
