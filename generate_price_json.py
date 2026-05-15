import pandas as pd
import json
import sys
import os

CSV_PATH = "btcusd_1-min_data.csv"
OUT_PATH = "btc_daily_price.json"

def main():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found. Download it from:")
        print("https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data/data")
        sys.exit(1)

    print(f"Reading {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH, usecols=["Timestamp", "Close"])
    print(f"  {len(df):,} rows loaded")

    # Convert Unix timestamp (seconds) to date
    df["date"] = pd.to_datetime(df["Timestamp"], unit="s").dt.strftime("%Y-%m-%d")

    # Drop rows with missing Close
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]

    # Last close of each day
    daily = df.groupby("date")["Close"].last()

    out = daily.to_dict()
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"  {len(out):,} days written to {OUT_PATH}")
    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"  File size: {size_kb:.1f} KB")

if __name__ == "__main__":
    main()
