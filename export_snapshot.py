import json
import datetime
import os

def export_snapshot():
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    btc_data = {}
    mvrv_data = {}

    try:
        with open("btc_daily_price.json", "r") as f:
            btc_data = json.load(f)
    except Exception as e:
        btc_data = {"error": str(e)}

    try:
        with open("mvrv.json", "r") as f:
            mvrv_data = json.load(f)
    except Exception as e:
        mvrv_data = {"error": str(e)}

    # Get latest BTC price entry
    latest_price = "N/A"
    if isinstance(btc_data, list) and len(btc_data) > 0:
        latest = btc_data[-1]
        latest_price = latest.get("price") or latest.get("close") or latest.get("value") or "N/A"

    # Get latest MVRV entry
    latest_mvrv = "N/A"
    if isinstance(mvrv_data, list) and len(mvrv_data) > 0:
        latest = mvrv_data[-1]
        latest_mvrv = latest.get("mvrv") or latest.get("value") or "N/A"

    lines = [
        "=== BTC Analytics Snapshot ===",
        f"Exported at : {timestamp}",
        f"BTC Price   : {latest_price}",
        f"MVRV        : {latest_mvrv}",
        "",
        "--- Raw BTC Price (last 5 entries) ---",
    ]

    if isinstance(btc_data, list):
        for row in btc_data[-5:]:
            lines.append(str(row))
    else:
        lines.append(str(btc_data))

    lines += ["", "--- Raw MVRV (last 5 entries) ---"]
    if isinstance(mvrv_data, list):
        for row in mvrv_data[-5:]:
            lines.append(str(row))
    else:
        lines.append(str(mvrv_data))

    os.makedirs("exports", exist_ok=True)
    with open("exports/latest_snapshot.txt", "w") as f:
        f.write("\n".join(lines))

    print(f"Snapshot saved at {timestamp}")

if __name__ == "__main__":
    export_snapshot()
