import pandas as pd
import json
import sys
import os
from datetime import date

CSV_PATH = "btcusd_1-min_data.csv"
OUT_PATH = "btc_daily_price.json"

# Sanity bounds: BTC never traded outside these prices in history
BTC_MIN_PRICE = 0.01
BTC_MAX_PRICE = 10_000_000

# If the new output has fewer days than this fraction of the previous output,
# treat it as a bad upstream file and abort rather than overwrite.
MIN_DAY_RETENTION = 0.95


def load_previous(path):
    """Return the day-count of the existing output file, or 0 if absent."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path) as f:
            return len(json.load(f))
    except Exception:
        return 0


def main():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found. Download it from:")
        print("https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data/data")
        sys.exit(1)

    print(f"Reading {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH, usecols=["Timestamp", "Close"])
    print(f"  {len(df):,} rows loaded")

    # Convert Unix timestamp (seconds) to date, sort chronologically
    df["date"] = pd.to_datetime(df["Timestamp"], unit="s").dt.strftime("%Y-%m-%d")
    df = df.sort_values("Timestamp")

    # Drop rows with missing or implausible Close values
    df = df.dropna(subset=["Close"])
    df = df[(df["Close"] >= BTC_MIN_PRICE) & (df["Close"] <= BTC_MAX_PRICE)]
    print(f"  {len(df):,} rows after price sanity filter ({BTC_MIN_PRICE}–{BTC_MAX_PRICE:,})")

    # Last close of each day (after sort, so groupby preserves order)
    daily = df.groupby("date")["Close"].last()

    # Validate date coverage — warn if latest date is more than 2 days ago
    latest = daily.index[-1]
    days_stale = (date.today() - date.fromisoformat(latest)).days
    if days_stale > 2:
        print(f"  WARNING: latest date in CSV is {latest} ({days_stale}d ago). Kaggle dataset may be lagging.")

    print(f"  Date range: {daily.index[0]} → {latest}")

    # Guard against upstream data loss — refuse to shrink output by more than 5%
    prev_count = load_previous(OUT_PATH)
    new_count = len(daily)
    if prev_count > 0 and new_count < prev_count * MIN_DAY_RETENTION:
        print(f"  ERROR: new output has {new_count:,} days vs previous {prev_count:,} "
              f"({new_count/prev_count:.1%}). Aborting to avoid overwriting good data.")
        sys.exit(1)

    out = daily.to_dict()
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"  {new_count:,} days written to {OUT_PATH}")
    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"  File size: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
