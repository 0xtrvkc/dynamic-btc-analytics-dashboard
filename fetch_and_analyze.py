import requests
import json
import datetime
import os
import math

# ── 1. Fetch MVRV data from blockchain.com ──────────────────────────────────
print("Fetching MVRV data...")
url = "https://api.blockchain.info/charts/mvrv?timespan=all&format=json&cors=true"
resp = requests.get(url, timeout=30)
resp.raise_for_status()
raw = resp.json()
values = raw.get("values", [])

# ── 2. Fetch BTC price data from CoinGecko ───────────────────────────────────
print("Fetching BTC price data...")
price_url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
price_resp = requests.get(price_url, params={"vs_currency": "usd", "days": "max", "interval": "daily"}, timeout=30)
price_resp.raise_for_status()
price_raw = price_resp.json()
price_map = {}
for entry in price_raw.get("prices", []):
    ts_ms, price = entry
    date_str = datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    price_map[date_str] = round(price, 2)

# ── 3. Build combined dataset ────────────────────────────────────────────────
data = []
for v in values:
    ts = v.get("x", 0)
    mvrv = v.get("y", 0)
    if mvrv is None or mvrv == 0:
        continue
    date_str = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    btc_price = price_map.get(date_str, None)
    data.append({"date": date_str, "mvrv": mvrv, "price": btc_price})

# ── 4. Calculate analytics ───────────────────────────────────────────────────
mvrv_values = [d["mvrv"] for d in data if d["mvrv"] is not None]

# Z-Score (rolling: mean and std of all data up to each point)
def zscore_series(values):
    scores = []
    for i, v in enumerate(values):
        window = values[: i + 1]
        if len(window) < 2:
            scores.append(0)
        else:
            mean = sum(window) / len(window)
            std = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
            scores.append(round((v - mean) / std, 4) if std > 0 else 0)
    return scores

zscores = zscore_series(mvrv_values)

# Moving averages (30d, 90d, 200d)
def moving_avg(values, window):
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            result.append(round(sum(values[i - window + 1 : i + 1]) / window, 4))
    return result

ma30 = moving_avg(mvrv_values, 30)
ma90 = moving_avg(mvrv_values, 90)
ma200 = moving_avg(mvrv_values, 200)

# Drawdown from peak
def drawdown_series(values):
    result = []
    peak = values[0]
    for v in values:
        if v > peak:
            peak = v
        dd = round((v - peak) / peak * 100, 2) if peak > 0 else 0
        result.append(dd)
    return result

drawdowns = drawdown_series(mvrv_values)

# Momentum (rate of change over 14 days)
def momentum_series(values, period=14):
    result = []
    for i in range(len(values)):
        if i < period:
            result.append(None)
        else:
            prev = values[i - period]
            result.append(round((values[i] - prev) / prev * 100, 4) if prev != 0 else 0)
    return result

momentum = momentum_series(mvrv_values, 14)

# Zone classification
def mvrv_zone(v):
    if v < 1:   return "Extreme Undervalue"
    if v < 2:   return "Undervalue"
    if v < 3:   return "Fair Value"
    if v < 4:   return "Overvalue"
    return "Extreme Overvalue"

# ── 5. Attach analytics back to data rows ───────────────────────────────────
for i, row in enumerate(data):
    row["zscore"]   = zscores[i]
    row["ma30"]     = ma30[i]
    row["ma90"]     = ma90[i]
    row["ma200"]    = ma200[i]
    row["drawdown"] = drawdowns[i]
    row["momentum"] = momentum[i]
    row["zone"]     = mvrv_zone(row["mvrv"])

# ── 6. Summary stats ─────────────────────────────────────────────────────────
latest = data[-1]
all_time_high_mvrv = max(mvrv_values)
all_time_low_mvrv  = min(mvrv_values)
current_mvrv       = latest["mvrv"]
current_zscore     = latest["zscore"]
current_price      = latest["price"]
current_zone       = latest["zone"]
current_drawdown   = latest["drawdown"]
current_momentum   = latest["momentum"]
current_ma30       = latest["ma30"]
current_ma90       = latest["ma90"]
current_ma200      = latest["ma200"]

# Cycle peaks (entries where mvrv > 3.5 and higher than neighbors)
peaks = []
for i in range(1, len(data) - 1):
    if (mvrv_values[i] > 3.5
            and mvrv_values[i] > mvrv_values[i - 1]
            and mvrv_values[i] > mvrv_values[i + 1]):
        peaks.append({"date": data[i]["date"], "mvrv": mvrv_values[i], "price": data[i]["price"]})

# Undervalue entries (mvrv < 1)
undervalue_periods = [d for d in data if d["mvrv"] < 1]

# ── 7. Write snapshot txt ────────────────────────────────────────────────────
timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

lines = [
    "=" * 60,
    "  BTC MVRV ANALYTICS SNAPSHOT",
    f"  Generated: {timestamp}",
    "=" * 60,
    "",
    "── CURRENT STATUS ──────────────────────────────────────",
    f"  Date          : {latest['date']}",
    f"  BTC Price     : ${current_price:,.2f}" if current_price else "  BTC Price     : N/A",
    f"  MVRV Ratio    : {current_mvrv:.4f}",
    f"  Zone          : {current_zone}",
    f"  Z-Score       : {current_zscore:.4f}",
    f"  Drawdown      : {current_drawdown:.2f}%",
    f"  Momentum(14d) : {current_momentum:.4f}%" if current_momentum else "  Momentum(14d) : N/A",
    "",
    "── MOVING AVERAGES ─────────────────────────────────────",
    f"  MA30          : {current_ma30:.4f}" if current_ma30 else "  MA30          : N/A",
    f"  MA90          : {current_ma90:.4f}" if current_ma90 else "  MA90          : N/A",
    f"  MA200         : {current_ma200:.4f}" if current_ma200 else "  MA200         : N/A",
    "",
    "── ALL TIME STATS ──────────────────────────────────────",
    f"  All-Time High MVRV : {all_time_high_mvrv:.4f}",
    f"  All-Time Low  MVRV : {all_time_low_mvrv:.4f}",
    f"  Total data points  : {len(data)}",
    f"  Undervalue periods : {len(undervalue_periods)} days (MVRV < 1)",
    "",
    "── HISTORICAL CYCLE PEAKS (MVRV > 3.5) ────────────────",
]

for p in peaks[-10:]:  # last 10 peaks
    price_str = f"${p['price']:,.2f}" if p["price"] else "N/A"
    lines.append(f"  {p['date']}  MVRV: {p['mvrv']:.4f}  Price: {price_str}")

lines += [
    "",
    "── LAST 10 DATA POINTS ─────────────────────────────────",
    f"  {'Date':<12} {'MVRV':>8} {'Z-Score':>9} {'Drawdown':>10} {'Zone':<22} {'Price':>12}",
    "  " + "-" * 78,
]

for row in data[-10:]:
    price_str = f"${row['price']:>10,.2f}" if row["price"] else f"{'N/A':>11}"
    lines.append(
        f"  {row['date']:<12} {row['mvrv']:>8.4f} {row['zscore']:>9.4f} "
        f"{row['drawdown']:>9.2f}% {row['zone']:<22} {price_str}"
    )

lines += ["", "=" * 60]

# ── 8. Save files ────────────────────────────────────────────────────────────
os.makedirs("exports", exist_ok=True)

with open("exports/latest_snapshot.txt", "w") as f:
    f.write("\n".join(lines))

with open("exports/latest_snapshot.json", "w") as f:
    json.dump({
        "generated_at": timestamp,
        "latest": latest,
        "summary": {
            "all_time_high_mvrv": all_time_high_mvrv,
            "all_time_low_mvrv": all_time_low_mvrv,
            "total_data_points": len(data),
            "undervalue_days": len(undervalue_periods),
            "cycle_peaks": peaks,
        }
    }, f, indent=2)

print(f"Done. Snapshot saved to exports/")
print("\n".join(lines[-20:]))
