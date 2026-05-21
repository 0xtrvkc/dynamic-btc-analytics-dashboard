import json, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHART_URL = "https://www.blockchain.com/explorer/charts/mvrv"
OUT_FILE  = Path("mvrv.json")

def detect_metric(data: dict) -> str:
    """Return 'mvrv' or 'market-price' based on response metadata."""
    name = data.get("name", "").lower()
    desc = data.get("description", "").lower()
    if "mvrv" in name or "mvrv" in desc:
        return "mvrv"
    if "price" in name or "usd" in name or "market" in name:
        return "market-price"
    return "unknown"

def normalize_values(values: list) -> list:
    """Convert new-format values to old format (seconds → milliseconds, drop nulls)."""
    result = []
    for point in values:
        x = point.get("x")
        y = point.get("y")
        if x is None or y is None:
            continue
        # New API uses seconds; old format used milliseconds
        x_ms = x * 1000 if x < 1_000_000_000_000 else x
        result.append({"x": x_ms, "y": y})
    return result

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        page = await context.new_page()

        # FIX: collect ALL matching responses keyed by metric type,
        # not just the last one. The MVRV page fires two API calls —
        # one for the MVRV ratio and one for the market-price overlay —
        # and the original code overwrote captured["data"] each time,
        # ending up with only market-price.
        captured = {}   # keyed by metric: "mvrv" | "market-price"

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
                if len(vals) > 1000:
                    metric = detect_metric(data)
                    print(f"  ✓ Captured {len(vals)} points ({metric}) from: {url}")
                    captured[metric] = data
            except Exception:
                pass

        page.on("response", on_response)

        print("Opening page...")
        await page.goto(CHART_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Click "All" timeframe button
        try:
            await page.get_by_text("All", exact=True).first.click()
            print("Clicked 'All'")
            captured.clear()   # discard pre-click data
        except Exception as e:
            print(f"Could not click All: {e}")

        # Wait for both metrics to arrive and stabilize
        prev_counts = {}
        stable_ticks = 0
        for i in range(60):
            await asyncio.sleep(1)
            current_counts = {
                k: len((v or {}).get("values") or [])
                for k, v in captured.items()
            }
            print(f"  waiting... {i+1}s | captured: {current_counts}")

            has_enough = all(c > 1000 for c in current_counts.values()) and len(current_counts) >= 1
            if has_enough:
                if current_counts == prev_counts:
                    stable_ticks += 1
                    if stable_ticks >= 3:
                        print("  Data stabilized.")
                        break
                else:
                    stable_ticks = 0
            prev_counts = current_counts.copy()

        await browser.close()

        if not captured:
            raise RuntimeError("No MVRV data captured. The site may have changed its API.")

        # Build old-format output that index.html expects:
        # { metric1, metric2, mvrv: [{x: ms, y}], "market-price": [{x: ms, y}], type, average, timespan }
        mvrv_data   = captured.get("mvrv", {})
        price_data  = captured.get("market-price", {})

        # Handle old bundled format too (in case site reverts)
        if "mvrv" in mvrv_data and "market-price" in mvrv_data:
            print("  Detected old bundled format — saving as-is.")
            OUT_FILE.write_text(json.dumps(mvrv_data, separators=(",", ":")))
        else:
            mvrv_values  = normalize_values(mvrv_data.get("values", []))
            price_values = normalize_values(price_data.get("values", []))

            if not mvrv_values:
                print("  WARNING: MVRV ratio not captured — only market-price available.")
                print("  MVRV-dependent charts will be empty.")
            if not price_values:
                print("  WARNING: Market-price not captured.")

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
        print(f"Saved {OUT_FILE} ({size:,} bytes)")
        print(f"  mvrv points:         {len(mvrv_values if mvrv_values else [])}")
        print(f"  market-price points: {len(price_values if price_values else [])}")

asyncio.run(main())
