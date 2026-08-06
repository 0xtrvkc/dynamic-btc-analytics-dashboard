"""
generate_intraday_price_json.py

Builds NEW, standalone JSON price files at 1H and 4H granularity from the
same raw 1-minute CSV used by generate_price_json.py.

This script does NOT read, write, or modify:
  - generate_price_json.py
  - btc_daily_price.json

It only reads the raw CSV (read-only) and writes two new files:
  - btc_1h_price.json
  - btc_4h_price.json

Output format matches btc_daily_price.json's shape (a flat {timestamp: close}
dict) so the existing dashboard's loadData()/RAW.dates/RAW.prices logic works
unchanged -- just point a new DATA_URL at one of these files.
"""

import pandas as pd
import json
import sys
import os

CSV_PATH = "btcusd_1-min_data.csv"

OUTPUTS = {
    "1h": "btc_1h_price.json",
    "4h": "btc_4h_price.json",
}

# Same sanity bounds as the daily script
BTC_MIN_PRICE = 0.01
BTC_MAX_PRICE = 10_000_000

# Minimum bars required in a resampled bucket to keep it (avoids emitting a
# bar built from e.g. only 1 minute of data at the start/end of the CSV)
MIN_MINUTES_PER_BAR = {"1h": 30, "4h": 120}


def build_timeframe(df, rule, min_minutes):
    """Resample minute closes to `rule` (e.g. '1h', '4h'), last-close per bucket."""
    g = df["Close"].resample(rule)
    counts = df["Close"].resample(rule).count()
    last = g.last()

    out = last[counts >= min_minutes]
    out = out.dropna()
    out = out[(out >= BTC_MIN_PRICE) & (out <= BTC_MAX_PRICE)]
    return out


def main():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found. Download it from:")
        print("https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data/data")
        sys.exit(1)

    print(f"Reading {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH, usecols=["Timestamp", "Close"])
    print(f"  {len(df):,} rows loaded")

    df["dt"] = pd.to_datetime(df["Timestamp"], unit="s")
    df = df.dropna(subset=["Close"]).sort_values("dt").set_index("dt")

    for label, out_path in OUTPUTS.items():
        rule = label  # '1h' / '4h'
        series = build_timeframe(df, rule, MIN_MINUTES_PER_BAR[label])

        out = {
            ts.strftime("%Y-%m-%dT%H:%M"): round(float(price), 2)
            for ts, price in series.items()
        }

        with open(out_path, "w") as f:
            json.dump(out, f, separators=(",", ":"))

        size_kb = os.path.getsize(out_path) / 1024
        print(
            f"  [{label}] {len(out):,} bars -> {out_path} "
            f"({series.index[0]} -> {series.index[-1]}, {size_kb:.1f} KB)"
        )

    print("Done. Existing generate_price_json.py and btc_daily_price.json were not touched.")


if __name__ == "__main__":
    main()
