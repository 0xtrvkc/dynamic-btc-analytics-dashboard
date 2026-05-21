import json, requests
from pathlib import Path

URL = "https://api.blockchain.info/charts/mvrv"
PARAMS = {
    "timespan": "all",
    "format": "json",
    "sampled": "false"   # full data, not downsampled
}

def main():
    print("Fetching MVRV data from blockchain.info...")
    r = requests.get(URL, params=PARAMS, timeout=30)
    r.raise_for_status()
    data = r.json()

    # validate
    values = data.get("values", [])
    if not values:
        raise ValueError("No values in response")
    print(f"Got {len(values)} data points. Latest: x={values[-1]['x']}, y={values[-1]['y']}")

    # write to repo root — same format your index.html already expects
    out = Path("mvrv.json")
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Saved to {out} ({out.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
