import requests
import json
import datetime
import os
import math
import time

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; btc-analytics-bot/1.0)"}

# ── 1. Fetch BTC market cap history from CoinGecko (free, no key) ────────────
print("Fetching BTC market cap history...")
mcap_resp = requests.get(
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
    params={"vs_currency": "usd", "days": "max", "interval": "daily"},
    headers=HEADERS,
    timeout=30,
)
mcap_resp.raise_for_status()
mcap_raw = mcap_resp.json()

# CoinGecko returns: prices[], market_caps[], total_volumes[]
prices_raw   = mcap_raw.get("prices", [])
mcaps_raw    = mcap_raw.get("market_caps", [])
print(f"Got {len(prices_raw)} price points, {len(mcaps_raw)} market cap points")

# Build price and mcap maps keyed by date string
price_map = {}
mcap_map  = {}
for ts_ms, val in prices_raw:
    d = datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    price_map[d] = round(val, 2)
for ts_ms, val in mcaps_raw:
    d = datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    mcap_map[d] = val

# Brief pause to avoid CoinGecko rate limit
time.sleep(2)

# ── 2. Fetch BTC circulating supply history (for realized cap approx) ────────
# We approximate realized cap using a 365-day rolling average of market cap.
# This is a well-known proxy when on-chain realized cap data is unavailable.
# True realized cap requires full UTXO history (only Glassnode has this free).

print("Building dataset...")
# Align all dates
all_dates = sorted(set(price_map.keys()) & set(mcap_map.keys()))

data = []
for d in all_dates:
    price = price_map.get(d)
    mcap  = mcap_map.get(d)
    if price is None or mcap is None or price == 0:
        continue
    data.append({"date": d, "price": price, "mcap": mcap})

print(f"Aligned dataset: {len(data)} rows")

# ── 3. Compute realized cap approximation ───────────────────────────────────
# Realized cap ≈ 365-day rolling average of market cap
# This smooths out speculation and approximates the realized value of coins
WINDOW = 365
mcap_vals = [d["mcap"] for d in data]

realized_caps = []
for i in range(len(mcap_vals)):
    start = max(0, i - WINDOW + 1)
    window_vals = mcap_vals[start : i + 1]
    realized_caps.append(sum(window_vals) / len(window_vals))

for i, row in enumerate(data):
    row["realized_cap"] = realized_caps[i]
    row["mvrv"] = round(row["mcap"] / row["realized_cap"], 4) if realized_caps[i] > 0 else None

# Remove rows where mvrv couldn't be computed
data = [d for d in data if d["mvrv"] is not None]
mvrv_values = [d["mvrv"] for d in data]
print(f"MVRV computed for {len(data)} rows")

# ── 4. Analytics ─────────────────────────────────────────────────────────────

def zscore_series(values):
    scores = []
    for i, v in enumerate(values):
        window = values[: i + 1]
        if len(window) < 2:
            scores.append(0.0)
        else:
            mean = sum(window) / len(window)
            std  = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
            scores.append(round((v - mean) / std, 4) if std > 0 else 0.0)
    return scores

def moving_avg(values, window):
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            result.append(round(sum(values[i - window + 1 : i + 1]) / window, 4))
    return result

def drawdown_series(values):
    result = []
    peak = values[0]
    for v in values:
        if v > peak:
            peak = v
        result.append(round((v - peak) / peak * 100, 2) if peak > 0 else 0.0)
    return result

def momentum_series(values, period=14):
    result = []
    for i in range(len(values)):
        if i < period:
            result.append(None)
        else:
            prev = values[i - period]
            result.append(round((values[i] - prev) / prev * 100, 4) if prev != 0 else 0.0)
    return result

def mvrv_zone(v):
    if v < 1:   return "Extreme Undervalue"
    if v < 2:   return "Undervalue"
    if v < 3:   return "Fair Value"
    if v < 4:   return "Overvalue"
    return       "Extreme Overvalue"

print("Calculating analytics...")
zscores   = zscore_series(mvrv_values)
ma30      = moving_avg(mvrv_values, 30)
ma90      = moving_avg(mvrv_values, 90)
ma200     = moving_avg(mvrv_values, 200)
drawdowns = drawdown_series(mvrv_values)
momentum  = momentum_series(mvrv_values, 14)

for i, row in enumerate(data):
    row["zscore"]   = zscores[i]
    row["ma30"]     = ma30[i]
    row["ma90"]     = ma90[i]
    row["ma200"]    = ma200[i]
    row["drawdown"] = drawdowns[i]
    row["momentum"] = momentum[i]
    row["zone"]     = mvrv_zone(row["mvrv"])

# ── 5. Summary stats ─────────────────────────────────────────────────────────
latest             = data[-1]
all_time_high_mvrv = max(mvrv_values)
all_time_low_mvrv  = min(mvrv_values)
undervalue_periods = [d for d in data if d["mvrv"] < 1]

# Cycle peaks: local maxima above 2.5
peaks = []
for i in range(1, len(data) - 1):
    if (mvrv_values[i] > 2.5
            and mvrv_values[i] > mvrv_values[i - 1]
            and mvrv_values[i] > mvrv_values[i + 1]):
        peaks.append({
            "date":  data[i]["date"],
            "mvrv":  mvrv_values[i],
            "price": data[i]["price"],
        })

# ── 6. Build snapshot text ───────────────────────────────────────────────────
timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def fmt_price(p):
    return f"${p:,.2f}" if p else "N/A"

lines = [
    "=" * 60,
    "  BTC MVRV ANALYTICS SNAPSHOT",
    f"  Generated : {timestamp}",
    "=" * 60,
    "",
    "── CURRENT STATUS ──────────────────────────────────────",
    f"  Date          : {latest['date']}",
    f"  BTC Price     : {fmt_price(latest['price'])}",
    f"  MVRV Ratio    : {latest['mvrv']:.4f}",
    f"  Zone          : {latest['zone']}",
    f"  Z-Score       : {latest['zscore']:.4f}",
    f"  Drawdown      : {latest['drawdown']:.2f}%",
    f"  Momentum(14d) : {latest['momentum']:.4f}%" if latest["momentum"] is not None else "  Momentum(14d) : N/A",
    "",
    "── MOVING AVERAGES (MVRV) ──────────────────────────────",
    f"  MA30          : {latest['ma30']:.4f}"  if latest["ma30"]  is not None else "  MA30          : N/A",
    f"  MA90          : {latest['ma90']:.4f}"  if latest["ma90"]  is not None else "  MA90          : N/A",
    f"  MA200         : {latest['ma200']:.4f}" if latest["ma200"] is not None else "  MA200         : N/A",
    "",
    "── ALL TIME STATS ──────────────────────────────────────",
    f"  ATH MVRV           : {all_time_high_mvrv:.4f}",
    f"  ATL MVRV           : {all_time_low_mvrv:.4f}",
    f"  Total data points  : {len(data)}",
    f"  Undervalue days    : {len(undervalue_periods)} (MVRV < 1)",
    "",
    "── CYCLE PEAKS (MVRV > 2.5) ────────────────────────────",
]

for p in peaks[-10:]:
    lines.append(f"  {p['date']}  MVRV: {p['mvrv']:.4f}  Price: {fmt_price(p['price'])}")

lines += [
    "",
    "── LAST 10 DATA POINTS ─────────────────────────────────",
    f"  {'Date':<12} {'MVRV':>8} {'Z-Score':>9} {'Drawdown':>10} {'Zone':<22} {'Price':>12}",
    "  " + "-" * 78,
]
for row in data[-10:]:
    lines.append(
        f"  {row['date']:<12} {row['mvrv']:>8.4f} {row['zscore']:>9.4f} "
        f"{row['drawdown']:>9.2f}% {row['zone']:<22} {fmt_price(row['price']):>12}"
    )

lines += ["", "=" * 60]

# ── 7. Save ──────────────────────────────────────────────────────────────────
os.makedirs("exports", exist_ok=True)

with open("exports/latest_snapshot.txt", "w") as f:
    f.write("\n".join(lines))

# Strip heavy fields from JSON to keep file small
json_data = {
    "generated_at": timestamp,
    "latest": {k: v for k, v in latest.items() if k != "realized_cap"},
    "summary": {
        "ath_mvrv":          all_time_high_mvrv,
        "atl_mvrv":          all_time_low_mvrv,
        "total_data_points": len(data),
        "undervalue_days":   len(undervalue_periods),
        "cycle_peaks":       peaks[-10:],
    },
}
with open("exports/latest_snapshot.json", "w") as f:
    json.dump(json_data, f, indent=2)

print("Done. Snapshot saved to exports/")
print("\n".join(lines))
