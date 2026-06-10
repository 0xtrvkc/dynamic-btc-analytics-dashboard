"""
generate_summary.py
Replicates the browser-side exportSummary() from index.html.
Reads mvrv.json + btc_daily_price.json already in the repo,
computes the same stats, writes exports/mvrv_summary_YYYY-MM-DD.txt
WITHOUT touching any other files.
"""

import json, math, os, sys
from datetime import datetime, timezone, date

# ── constants (mirror index.html) ─────────────────────────────────────────────
HALVINGS = [
    "2012-11-28",  # C1
    "2016-07-09",  # C2
    "2020-05-11",  # C3
    "2024-04-20",  # C4
    "2028-03-26",  # C5 est.
    "2032-02-15",  # C6 est.
    "2036-01-10",  # C7 est.
]
CYCLE_LABELS = {1:"2012-15", 2:"2016-19", 3:"2020-23", 4:"2024-27", 5:"2028-31", 6:"2032-35"}

AVG_CYCLE_DAYS   = 1422
ZSCORE_WINDOW    = 365
ZSCORE_CAPIT     = -1.5
ZSCORE_CAUTION   = 1.0
ROC_SHORT        = 30
ROC_LONG         = 90
HALVING_TOL_DAYS = 3

# ── helpers ───────────────────────────────────────────────────────────────────
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)

HALVING_DTS = [parse_date(h) for h in HALVINGS]

def assign_cycle(dt):
    c = 0
    for i, h in enumerate(HALVING_DTS[:-1]):
        if h <= dt < HALVING_DTS[i+1]:
            c = i + 1; break
    if dt >= HALVING_DTS[-1]:
        c = len(HALVING_DTS)
    return c

def cycle_pct(dt, c):
    if c == 0 or c > len(HALVING_DTS):
        return None
    if c < len(HALVING_DTS):
        total = (HALVING_DTS[c] - HALVING_DTS[c-1]).days
        days_in = (dt - HALVING_DTS[c-1]).days
        return min(100.0, days_in / total * 100)
    # open-ended last cycle
    days_in = (dt - HALVING_DTS[c-1]).days
    return min(100.0, days_in / AVG_CYCLE_DAYS * 100)

def median(arr):
    if not arr: return None
    s = sorted(arr)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m-1]+s[m])/2

def iqr_outlier(val, arr):
    if len(arr) < 4: return False
    s = sorted(arr)
    q1 = s[int(len(s)*0.25)]; q3 = s[int(len(s)*0.75)]
    iqr = q3 - q1
    return val < q1 - 1.5*iqr or val > q3 + 1.5*iqr

def linreg(xs, ys):
    n = len(xs)
    if n < 2: return (0, 0)
    mx = sum(xs)/n; my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    den = sum((x-mx)**2 for x in xs)
    slope = num/den if den else 0
    intercept = my - slope*mx
    return slope, intercept

def logreg(xs, ys):
    lxs = [math.log(x) for x in xs if x > 0]
    return linreg(lxs, ys[:len(lxs)])

# ── load data ─────────────────────────────────────────────────────────────────
def load_mvrv(path="mvrv.json"):
    with open(path) as f:
        raw = json.load(f)
    arr = raw.get("mvrv") or raw.get("values") or []
    # The source file is sub-daily; deduplicate to one row per calendar day
    # (keep the last entry per day, matching how the dashboard renders data)
    daily: dict = {}
    for p in arr:
        x = p["x"]
        y = p.get("y")
        if y is None: continue
        dt = datetime.fromtimestamp(x/1000, tz=timezone.utc)
        daily[dt.strftime("%Y-%m-%d")] = (dt, float(y))
    rows = [
        {"dt": dt, "date": day, "mvrv": y}
        for day, (dt, y) in sorted(daily.items())
    ]
    return rows

def load_prices(path="btc_daily_price.json"):
    if not os.path.exists(path): return {}
    with open(path) as f:
        return json.load(f)

# ── enrich DATA rows ──────────────────────────────────────────────────────────
def build_data(raw_rows, price_map):
    data = []
    mvrvs = [r["mvrv"] for r in raw_rows]
    n = len(mvrvs)
    for i, r in enumerate(raw_rows):
        dt = r["dt"]
        c  = assign_cycle(dt)
        cp = cycle_pct(dt, c)

        # z-score: rolling 365-day window
        win_start = max(0, i - ZSCORE_WINDOW + 1)
        win = mvrvs[win_start:i+1]
        wm = sum(win)/len(win)
        wstd = math.sqrt(sum((v-wm)**2 for v in win)/len(win)) if len(win)>1 else 0
        zscore = (mvrvs[i]-wm)/wstd if wstd else 0

        roc30 = ((mvrvs[i]-mvrvs[i-ROC_SHORT])/mvrvs[i-ROC_SHORT]*100) if i>=ROC_SHORT else None
        roc90 = ((mvrvs[i]-mvrvs[i-ROC_LONG ])/mvrvs[i-ROC_LONG ]*100) if i>=ROC_LONG  else None

        # moving averages
        ma20  = sum(mvrvs[max(0,i-19):i+1])/min(i+1,20)
        ma50  = sum(mvrvs[max(0,i-49):i+1])/min(i+1,50)
        ma200 = sum(mvrvs[max(0,i-199):i+1])/min(i+1,200)

        price = price_map.get(r["date"])

        # drawdown from cycle peak so far
        same_c = [d["mvrv"] for d in data if d["cycle"] == c]
        cpeak = max(same_c) if same_c else r["mvrv"]
        drawdown = ((r["mvrv"]-cpeak)/cpeak*100) if cpeak else None

        data.append({
            "dt": dt, "date": r["date"], "mvrv": r["mvrv"],
            "cycle": c, "cyclePct": cp,
            "zscore": zscore, "ma20": ma20, "ma50": ma50, "ma200": ma200,
            "roc30": roc30, "roc90": roc90,
            "price": float(price) if price else None,
            "drawdown": drawdown,
        })
    return data

def build_stats(data):
    if not data: return {}
    mvrvs = [d["mvrv"] for d in data]
    last  = data[-1]
    mean  = sum(mvrvs)/len(mvrvs)
    peak_row = max(data, key=lambda d: d["mvrv"])
    bot_row  = min(data, key=lambda d: d["mvrv"])

    cycles = sorted({d["cycle"] for d in data if d["cycle"] > 0})
    by_cycle = {c: [d for d in data if d["cycle"]==c] for c in cycles}

    cycle_data = []
    for c in cycles:
        pts = by_cycle[c]
        if not pts: continue
        pk = max(pts, key=lambda d: d["mvrv"])
        tr = min(pts, key=lambda d: d["mvrv"])
        days = (pts[-1]["dt"] - pts[0]["dt"]).days + 1
        below1   = sum(1 for d in pts if d["mvrv"]<1)
        below1_5 = sum(1 for d in pts if d["mvrv"]<1.5)
        above2   = sum(1 for d in pts if d["mvrv"]>=2)
        above3   = sum(1 for d in pts if d["mvrv"]>=3)
        cycle_data.append({
            "cycle": c, "days": days,
            "peak": pk["mvrv"], "peakDate": pk["date"],
            "trough": tr["mvrv"], "troughDate": tr["date"],
            "below1": below1, "below1_5": below1_5,
            "above2": above2, "above3": above3,
            "pts": pts,
        })

    # regression
    completed = [cd for cd in cycle_data
                 if cd["cycle"] < last["cycle"] or
                    (cd["cycle"] == last["cycle"] and HALVING_DTS[cd["cycle"]] < last["dt"]
                     if cd["cycle"] < len(HALVING_DTS) else False)]
    pk_cycles = [cd["cycle"] for cd in completed]
    pk_vals   = [cd["peak"]  for cd in completed]
    tr_cycles = [cd["cycle"] for cd in completed]
    tr_vals   = [cd["trough"] for cd in completed]

    log_slope,  log_int  = logreg(pk_cycles, pk_vals) if len(pk_cycles)>1 else (0,0)
    lin_slope,  lin_int  = linreg(pk_cycles, pk_vals) if len(pk_cycles)>1 else (0,0)
    tlog_slope, tlog_int = logreg(tr_cycles, tr_vals) if len(tr_cycles)>1 else (0,0)
    tlin_slope, tlin_int = linreg(tr_cycles, tr_vals) if len(tr_cycles)>1 else (0,0)

    has_price = any(d["price"] for d in data)
    next_cycle = last["cycle"] + 1

    return {
        "last": last, "mean": mean, "peakRow": peak_row, "botRow": bot_row,
        "cycleData": cycle_data, "byCycle": by_cycle,
        "logR":      {"slope": log_slope,  "intercept": log_int},
        "linR":      {"slope": lin_slope,  "intercept": lin_int},
        "troughLogR":{"slope": tlog_slope, "intercept": tlog_int},
        "troughLinR":{"slope": tlin_slope, "intercept": tlin_int},
        "hasPrice": has_price, "nextCycle": next_cycle,
        "availCycles": [cd["cycle"] for cd in cycle_data],
    }

# ── backtest (price projections) ──────────────────────────────────────────────
def run_backtest(data, stats, price_map):
    """Mirrors runBacktest() from index.html."""
    all_results = []
    cur_cycle = stats["last"]["cycle"]

    def price_at_halving(hi):
        if hi >= len(HALVINGS): return None
        hd = HALVINGS[hi]
        for delta in range(HALVING_TOL_DAYS+1):
            for sign in ([0,1,-1] if delta else [0]):
                d = (date.fromisoformat(hd) +
                     __import__("datetime").timedelta(days=sign*delta)).isoformat()
                if d in price_map: return float(price_map[d])
        return None

    for c_idx, cd in enumerate(stats["cycleData"]):
        c = cd["cycle"]
        pts = cd["pts"]
        price_pts = [d for d in pts if d["price"]]

        # prior completed cycles for projection
        prior = [cx for cx in stats["cycleData"] if cx["cycle"] < c]

        # price at halving for this cycle
        halving_price = price_at_halving(c-1)

        # actual ATH / bottom
        actual_ath    = max((d["price"] for d in price_pts), default=None)
        actual_bottom = min((d["price"] for d in price_pts), default=None)

        is_current = (c == cur_cycle)

        # ── ceiling models (need ≥2 prior cycles) ──────────────────────────
        m1 = m2 = m3 = m4 = consensus = None
        if len(prior) >= 2:
            # M1: MVRV upside — price at MVRV peak × median remaining upside
            rem_upsides = []
            for px in prior:
                p_pts = [d for d in px["pts"] if d["price"]]
                if not p_pts: continue
                ath  = max(d["price"] for d in p_pts)
                pmvp = price_map.get(px["peakDate"])
                if pmvp and ath:
                    rem_upsides.append((ath - float(pmvp)) / float(pmvp) * 100)
            cur_mvrv_pk = price_map.get(cd["peakDate"])
            if cur_mvrv_pk and rem_upsides:
                med_up = median(rem_upsides)
                m1 = float(cur_mvrv_pk) * (1 + med_up/100)

            # M2: halving multiplier — log-decay fitted on prior
            hm_pairs = [(px["cycle"], max((d["price"] for d in px["pts"] if d["price"]),
                         default=None) / (price_at_halving(px["cycle"]-1) or 1))
                        for px in prior if any(d["price"] for d in px["pts"])]
            hm_pairs = [(cc, mult) for cc, mult in hm_pairs if mult]
            if halving_price and len(hm_pairs) >= 2:
                sl, ic = logreg([p[0] for p in hm_pairs], [p[1] for p in hm_pairs])
                proj_mult = max(0, sl * math.log(c) + ic) if c > 0 else 0
                m2 = halving_price * proj_mult if proj_mult else None

            # M3: ATH multiplier — prev ATH × log-decay ratio
            ath_pairs = []
            for i, px in enumerate(prior[1:], 1):
                prev_ath = max((d["price"] for d in prior[i-1]["pts"] if d["price"]), default=None)
                cur_ath  = max((d["price"] for d in px["pts"] if d["price"]), default=None)
                if prev_ath and cur_ath:
                    ath_pairs.append((px["cycle"], cur_ath/prev_ath))
            prev_cycle_ath = max((d["price"] for d in prior[-1]["pts"] if d["price"]), default=None)
            if prev_cycle_ath and len(ath_pairs) >= 2:
                sl, ic = logreg([p[0] for p in ath_pairs], [p[1] for p in ath_pairs])
                proj_ratio = max(0, sl * math.log(c) + ic) if c > 0 else 0
                m3 = prev_cycle_ath * proj_ratio if proj_ratio else None

            # M4: MVRV × realised cap proxy
            start_prices = []
            for px in prior:
                if px["pts"] and px["pts"][0]["price"]:
                    start_prices.append(px["pts"][0]["price"])
            # project peak MVRV via log regression on prior peaks
            pk_nums = [px["cycle"] for px in prior]
            pk_vs   = [px["peak"]  for px in prior]
            if len(pk_nums) >= 2:
                sl, ic = logreg(pk_nums, pk_vs)
                proj_pk_mvrv = max(0, sl * math.log(c) + ic) if c > 0 else 0
                start_price = pts[0]["price"] if pts and pts[0]["price"] else None
                cur_mvrv0   = pts[0]["mvrv"]  if pts else 1
                if start_price and cur_mvrv0 and proj_pk_mvrv:
                    m4 = (start_price / cur_mvrv0) * proj_pk_mvrv

            valid_ceil = [v for v in [m1,m2,m3,m4] if v]
            clean_ceil = [v for v in valid_ceil if not iqr_outlier(v, valid_ceil)]
            consensus  = median(clean_ceil) if clean_ceil else None

        # ── floor models ───────────────────────────────────────────────────
        bm1 = bm2 = bm3 = consensus_bot = None
        if len(prior) >= 2:
            # BM1: MVRV downside
            furt_downsides = []
            for px in prior:
                p_pts = [d for d in px["pts"] if d["price"]]
                if not p_pts: continue
                bot  = min(d["price"] for d in p_pts)
                ptrough = price_map.get(px["troughDate"])
                if ptrough and bot:
                    furt_downsides.append((bot - float(ptrough)) / float(ptrough) * 100)
            cur_mvrv_tr = price_map.get(cd["troughDate"])
            if cur_mvrv_tr and furt_downsides:
                med_dn = median(furt_downsides)
                bm1 = float(cur_mvrv_tr) * (1 + med_dn/100)

            # BM2: halving floor ratio
            hf_pairs = [(px["cycle"],
                         min((d["price"] for d in px["pts"] if d["price"]), default=None) /
                         (price_at_halving(px["cycle"]-1) or 1))
                        for px in prior if any(d["price"] for d in px["pts"])]
            hf_pairs = [(cc, r) for cc, r in hf_pairs if r]
            if halving_price and len(hf_pairs) >= 2:
                sl, ic = logreg([p[0] for p in hf_pairs], [p[1] for p in hf_pairs])
                proj_fr = max(0, sl * math.log(c) + ic) if c > 0 else 0
                bm2 = halving_price * proj_fr if proj_fr else None

            # BM3: bottom multiplier
            bot_pairs = []
            for i, px in enumerate(prior[1:], 1):
                prev_bot = min((d["price"] for d in prior[i-1]["pts"] if d["price"]), default=None)
                cur_bot  = min((d["price"] for d in px["pts"] if d["price"]), default=None)
                if prev_bot and cur_bot:
                    bot_pairs.append((px["cycle"], cur_bot/prev_bot))
            prev_cycle_bot = min((d["price"] for d in prior[-1]["pts"] if d["price"]), default=None)
            if prev_cycle_bot and len(bot_pairs) >= 2:
                sl, ic = logreg([p[0] for p in bot_pairs], [p[1] for p in bot_pairs])
                proj_br = max(0, sl * math.log(c) + ic) if c > 0 else 0
                bm3 = prev_cycle_bot * proj_br if proj_br else None

            valid_floor = [v for v in [bm1,bm2,bm3] if v]
            clean_floor = [v for v in valid_floor if not iqr_outlier(v, valid_floor)]
            consensus_bot = median(clean_floor) if clean_floor else None

        all_results.append({
            "cycle": c, "isCurrent": is_current,
            "halvingPrice": halving_price,
            "actualATH": actual_ath, "actualBottom": actual_bottom,
            "m1": m1, "m2": m2, "m3": m3, "m4": m4, "consensus": consensus,
            "bm1": bm1, "bm2": bm2, "bm3": bm3, "consensusBot": consensus_bot,
        })

    completed_results = [r for r in all_results if not r["isCurrent"]]
    return all_results, completed_results

# ── format helpers ────────────────────────────────────────────────────────────
def fmt_price(p):
    return f"${round(p):,}" if p else "—"

# ── main export writer ────────────────────────────────────────────────────────
def build_export(data, stats, price_map, all_results, completed_results):
    s   = stats
    l   = s["last"]
    has = s["hasPrice"]
    lines = []

    def hr(title): lines.extend(["", f"=== {title} ==="])
    def row(label, val): lines.append(f"{label}: {val}")

    signal = ("Capitulation" if l["zscore"] < ZSCORE_CAPIT
              else "Accumulate" if l["zscore"] < 0
              else "Neutral"    if l["zscore"] < ZSCORE_CAUTION
              else "Caution")

    hr("CURRENT STATUS")
    row("Date",               l["date"])
    row("MVRV",               f"{l['mvrv']:.3f}")
    row("Z-score",            f"{l['zscore']:.3f}")
    row("Signal",             signal)
    row("MA20",               f"{l['ma20']:.3f}")
    row("MA50",               f"{l['ma50']:.3f}")
    row("MA200",              f"{l['ma200']:.3f}")
    ma_label = ("Bullish (MA20>MA50>MA200)" if l["ma20"]>l["ma50"]>l["ma200"]
                else "Bearish (MA20<MA50<MA200)" if l["ma20"]<l["ma50"]<l["ma200"]
                else "Mixed")
    row("MA stack",           ma_label)
    row("ROC 30d",            f"{l['roc30']:.1f}%" if l["roc30"] is not None else "—")
    row("ROC 90d",            f"{l['roc90']:.1f}%" if l["roc90"] is not None else "—")
    if has and l["price"]:
        row("BTC Price", fmt_price(l["price"]))
    row("All-time MVRV peak", f"{s['peakRow']['mvrv']:.3f} on {s['peakRow']['date']}")
    row("All-time MVRV bottom", f"{s['botRow']['mvrv']:.3f} on {s['botRow']['date']}")
    row("Historical mean MVRV", f"{s['mean']:.3f}")
    row("Data range",         f"{data[0]['date']} to {data[-1]['date']}")
    row("Total data points",  f"{len(data):,}")

    hr("CURRENT CYCLE POSITION")
    cc = l["cycle"]
    cd = next((c for c in s["cycleData"] if c["cycle"]==cc), None)
    row("Current cycle",      f"C{cc}" + (f" ({CYCLE_LABELS[cc]})" if cc in CYCLE_LABELS else ""))
    row("Cycle position",     f"{l['cyclePct']:.1f}%" if l["cyclePct"] is not None else "unknown")
    if cd:
        row("Cycle peak so far",           f"{cd['peak']:.3f} on {cd['peakDate']}")
        row("Current MVRV vs cycle peak",  f"{l['mvrv']/cd['peak']*100:.0f}% of cycle peak")
        row("Days in current cycle",       cd["days"])
        row("Current drawdown from cycle peak",
            f"{(l['mvrv']-cd['peak'])/cd['peak']*100:.1f}%")

    hr("CYCLE SUMMARY")
    for c in s["cycleData"]:
        lines.append("")
        lines.append(f"Cycle {c['cycle']}" +
                     (f" ({CYCLE_LABELS[c['cycle']]})" if c["cycle"] in CYCLE_LABELS else "") + ":")
        row("  Peak MVRV",  f"{c['peak']:.3f} on {c['peakDate']}")
        row("  Trough MVRV", f"{c['trough']:.3f} on {c['troughDate']}")
        row("  Peak-to-trough range",
            f"{(c['peak']-c['trough'])/c['peak']*100:.0f}% compression")
        row("  Duration",   f"{c['days']} days")
        if has:
            pp = price_map.get(c["peakDate"])
            if pp: row("  BTC price at MVRV peak", fmt_price(float(pp)))
            tp = price_map.get(c["troughDate"])
            if tp: row("  BTC price at MVRV trough", fmt_price(float(tp)))

    hr("DRAWDOWN — Max MVRV drawdown from cycle peak")
    for c in s["cycleData"]:
        pts = [d for d in c["pts"] if d["drawdown"] is not None]
        if not pts: continue
        worst = min(pts, key=lambda d: d["drawdown"])
        lines.append(""); lines.append(f"Cycle {c['cycle']}:")
        row("  Max drawdown", f"{worst['drawdown']:.1f}% on {worst['date']}")
        if has and worst["price"]:
            row("  BTC price at worst drawdown", fmt_price(worst["price"]))

    hr("MA CROSSOVERS — Golden & death cross events (MA20 vs MA50)")
    crossovers = []
    for i in range(1, len(data)):
        prev, curr = data[i-1], data[i]
        if prev["ma20"] < prev["ma50"] and curr["ma20"] >= curr["ma50"]:
            crossovers.append({**curr, "type": "Golden cross"})
        elif prev["ma20"] > prev["ma50"] and curr["ma20"] <= curr["ma50"]:
            crossovers.append({**curr, "type": "Death cross"})
    if crossovers:
        now_dt = datetime.now(timezone.utc)
        for x in crossovers:
            info = f"C{x['cycle']} · MVRV {x['mvrv']:.3f}"
            if has and x["price"]: info += f" · {fmt_price(x['price'])}"
            row(f"  {x['date']} {x['type']}", info)
        lx = crossovers[-1]
        days_since = (now_dt - lx["dt"]).days
        row("Last crossover", f"{lx['type']} on {lx['date']} ({days_since}d ago)")
    else:
        lines.append("  No MA20/MA50 crossovers detected.")
    bias = "MA20 above MA50 (bullish bias)" if l["ma20"]>l["ma50"] else "MA20 below MA50 (bearish bias)"
    row("Current MA20 vs MA50", bias)

    hr("ZONE ANALYSIS — Days in each MVRV zone per cycle")
    for c in s["cycleData"]:
        lines.append(""); lines.append(f"Cycle {c['cycle']}:")
        d = c["days"]
        row("  Below 1.0",  f"{c['below1']}d ({c['below1']/d*100:.0f}%)")
        mid = c["below1_5"] - c["below1"]
        row("  1.0-1.5",    f"{mid}d ({mid/d*100:.0f}%)")
        mid2 = d - c["above2"] - c["below1_5"]
        row("  1.5-2.0",    f"{mid2}d ({mid2/d*100:.0f}%)")
        mid3 = c["above2"] - c["above3"]
        row("  2.0-3.0",    f"{mid3}d ({mid3/d*100:.0f}%)")
        row("  Above 3.0",  f"{c['above3']}d ({c['above3']/d*100:.0f}%)")
        if has:
            for lo, hi, label in [(0,1,"Below 1.0"),(1,1.5,"1.0-1.5"),
                                   (1.5,2,"1.5-2.0"),(2,3,"2.0-3.0"),(3,9999,"Above 3.0")]:
                zone_pts = [p for p in c["pts"] if lo <= p["mvrv"] < hi and p["price"]]
                if zone_pts:
                    avg = sum(p["price"] for p in zone_pts) / len(zone_pts)
                    row(f"  Avg BTC price in {label}", fmt_price(avg))
    cur_zone = ("Below 1.0" if l["mvrv"]<1 else "1.0-1.5" if l["mvrv"]<1.5
                else "1.5-2.0" if l["mvrv"]<2 else "2.0-3.0" if l["mvrv"]<3 else "Above 3.0")
    lines.append(""); row("Current MVRV zone", f"{cur_zone} (MVRV {l['mvrv']:.3f})")

    if has:
        hr("PRICE PEAK DIVERGENCE — MVRV lead/lag vs BTC price ATH")
        all_peak_diffs = []; all_rem_upsides = []
        for c in s["cycleData"]:
            pts = [d for d in c["pts"] if d["price"]]
            if not pts: continue
            best  = max(pts, key=lambda d: d["price"])
            days_diff = round((best["dt"] - parse_date(c["peakDate"])).days)
            div_pct = (best["mvrv"]-c["peak"])/c["peak"]*100
            price_at_pk = price_map.get(c["peakDate"])
            rem = ((best["price"]-float(price_at_pk))/float(price_at_pk)*100) if price_at_pk else None
            all_peak_diffs.append(days_diff)
            if rem is not None: all_rem_upsides.append(rem)
            lines.append(""); lines.append(f"Cycle {c['cycle']}:")
            row("  BTC ATH",            f"{fmt_price(best['price'])} on {best['date']}")
            row("  MVRV at price ATH",  f"{best['mvrv']:.3f}")
            row("  MVRV own peak",      f"{c['peak']:.3f} on {c['peakDate']}")
            row("  MVRV drawdown at price ATH", f"{div_pct:.1f}%")
            if price_at_pk: row("  Price at MVRV peak", fmt_price(float(price_at_pk)))
            if rem is not None: row("  Remaining upside after MVRV peaked", f"+{rem:.0f}%")
            lag = (f"Price peaked {days_diff}d AFTER MVRV" if days_diff>0
                   else f"Price peaked {-days_diff}d BEFORE MVRV" if days_diff<0 else "Same day")
            row("  Lead/lag", lag)
        if all_peak_diffs:
            lines.append("")
            row("  Median lead-lag (all cycles)", f"{median(all_peak_diffs)}d")
            if all_rem_upsides:
                row("  Median remaining upside after MVRV peaked", f"+{median(all_rem_upsides):.0f}%")

        hr("PRICE BOTTOM DIVERGENCE — MVRV lead/lag vs BTC price low")
        all_bot_diffs = []; all_furt_downsides = []
        for c in s["cycleData"]:
            pts = [d for d in c["pts"] if d["price"]]
            if not pts: continue
            worst = min(pts, key=lambda d: d["price"])
            days_diff = round((worst["dt"] - parse_date(c["troughDate"])).days)
            div_pct = (worst["mvrv"]-c["trough"])/c["trough"]*100
            price_at_tr = price_map.get(c["troughDate"])
            fd = ((worst["price"]-float(price_at_tr))/float(price_at_tr)*100) if price_at_tr else None
            all_bot_diffs.append(days_diff)
            if fd is not None: all_furt_downsides.append(fd)
            lines.append(""); lines.append(f"Cycle {c['cycle']}:")
            row("  BTC price low",           f"{fmt_price(worst['price'])} on {worst['date']}")
            row("  MVRV at price low",       f"{worst['mvrv']:.3f}")
            row("  MVRV own trough",         f"{c['trough']:.3f} on {c['troughDate']}")
            row("  MVRV recovery at price low", f"+{div_pct:.1f}%")
            if price_at_tr: row("  Price at MVRV trough", fmt_price(float(price_at_tr)))
            if fd is not None: row("  Further downside after MVRV troughed", f"{fd:.0f}%")
            lag = (f"Price bottomed {days_diff}d AFTER MVRV" if days_diff>0
                   else f"Price bottomed {-days_diff}d BEFORE MVRV" if days_diff<0 else "Same day")
            row("  Lead/lag", lag)
        if all_bot_diffs:
            lines.append("")
            row("  Median lead-lag (all cycles)", f"{median(all_bot_diffs)}d")
            if all_furt_downsides:
                row("  Median further downside after MVRV troughed", f"{median(all_furt_downsides):.0f}%")

    hr("REGRESSION PROJECTIONS — Cycle peak & trough MVRV")
    for ri in range(1, s["nextCycle"]+2):
        log_p = max(0, s["logR"]["slope"]*math.log(ri)+s["logR"]["intercept"]) if ri>0 else 0
        lin_p = max(0, s["linR"]["slope"]*ri+s["linR"]["intercept"])
        log_t = max(0, s["troughLogR"]["slope"]*math.log(ri)+s["troughLogR"]["intercept"]) if ri>0 else 0
        lin_t = max(0, s["troughLinR"]["slope"]*ri+s["troughLinR"]["intercept"])
        row(f"  C{ri} peak (log/linear)", f"{log_p:.3f} / {lin_p:.3f}")
        row(f"  C{ri} bottom (log/linear)", f"{log_t:.3f} / {lin_t:.3f}")

    if has:
        hr("PRICE PROJECTIONS — Ceiling & Floor consensus (current cycle)")
        cur_result = next((r for r in all_results if r["isCurrent"]), None)
        ceil_keys  = [("m1","MVRV Upside"),("m2","Halving Multiplier"),
                      ("m3","ATH Multiplier"),("m4","MVRV x Realized Cap")]
        floor_keys = [("bm1","MVRV Downside"),("bm2","Halving Floor Ratio"),
                      ("bm3","Bottom Multiplier")]
        if cur_result:
            lines.append("")
            lines.append("  --- CEILING MODELS ---")
            valid_ceil = [cur_result[k] for k,_ in ceil_keys if cur_result[k]]
            for k, name in ceil_keys:
                p = cur_result[k]
                if p is None: continue
                tag = " [outlier — excluded]" if iqr_outlier(p, valid_ceil) else " [included]"
                row(f"  {name}", fmt_price(p) + tag)
            lines.append("")
            clean_ceil = [v for v in valid_ceil if not iqr_outlier(v, valid_ceil)]
            if clean_ceil:
                row("  Ceiling consensus midpoint", fmt_price(median(clean_ceil)))
                row("  Ceiling consensus range",
                    f"{fmt_price(min(clean_ceil))} – {fmt_price(max(clean_ceil))}")
            lines.append("")
            lines.append("  --- FLOOR MODELS ---")
            valid_floor = [cur_result[k] for k,_ in floor_keys if cur_result[k]]
            for k, name in floor_keys:
                p = cur_result[k]
                if p is None: continue
                tag = " [outlier — excluded]" if iqr_outlier(p, valid_floor) else " [included]"
                row(f"  {name}", fmt_price(p) + tag)
            lines.append("")
            clean_floor = [v for v in valid_floor if not iqr_outlier(v, valid_floor)]
            if clean_floor:
                row("  Floor consensus midpoint", fmt_price(median(clean_floor)))
                row("  Floor consensus range",
                    f"{fmt_price(min(clean_floor))} – {fmt_price(max(clean_floor))}")
            if cur_result["halvingPrice"]:
                lines.append("")
                row("  BTC price at current cycle halving", fmt_price(cur_result["halvingPrice"]))
        lines.append("  * Outliers excluded via IQR. Not financial advice.")

        hr("BACKTEST — Ceiling & Floor model accuracy on past cycles")
        lines.append("Each model is re-run using ONLY data available before each cycle began — no lookahead.")
        lines.append("Error = (predicted − actual) / actual × 100.")
        lines.append("  Positive = overshot  |  Negative = undershot  |  Within ±20% = good · ±40% = ok · >40% = poor")
        lines.append("")

        def accuracy_block(keys, actual_key, section_label):
            lines.append(f"--- {section_label} (completed cycles only) ---")
            lines.append("")
            for k, name in keys:
                errs = [((r[k]-r[actual_key])/r[actual_key]*100)
                        for r in completed_results if r[k] and r[actual_key]]
                if not errs:
                    row(f"  {name}", "not enough data"); lines.append(""); continue
                avg_e = sum(errs)/len(errs)
                abs_e = sum(abs(e) for e in errs)/len(errs)
                q = "good" if abs_e<20 else "ok" if abs_e<40 else "poor"
                row(f"  {name}", f"{'+' if avg_e>=0 else ''}{avg_e:.1f}% avg error · {abs_e:.1f}% avg absolute · {q}")
                lines.append("")

        accuracy_block(ceil_keys+[("consensus","Ceiling Consensus")], "actualATH",    "CEILING model accuracy")
        accuracy_block(floor_keys+[("consensusBot","Floor Consensus")], "actualBottom", "FLOOR model accuracy")

        lines.append("--- Per-cycle breakdown ---"); lines.append("")
        for r in all_results:
            label = f"C{r['cycle']}" + (" (current — open)" if r["isCurrent"] else "")
            lines.append(f"  {label}:")
            if r["halvingPrice"]: row("    Price at halving", fmt_price(r["halvingPrice"]))
            lines.append(""); lines.append("    CEILING:")
            row(f"      {'ATH so far' if r['isCurrent'] else 'Actual ATH'}", fmt_price(r["actualATH"]))
            for k, name in ceil_keys:
                p = r[k]
                if p is None: lines.append(f"      {name}: — (insufficient prior data)"); continue
                err = ((p-r["actualATH"])/r["actualATH"]*100) if r["actualATH"] else None
                tag = (" v" if err is not None and abs(err)<20
                       else " ~" if err is not None and abs(err)<40
                       else " x" if err is not None else "")
                live = " (live)" if r["isCurrent"] else ""
                err_s = (f" · {'+' if err>=0 else ''}{err:.1f}%{tag}{live}") if err is not None else ""
                lines.append(f"      {name}: {fmt_price(p)}{err_s}")
            lines.append(""); lines.append("    FLOOR:")
            row(f"      {'Low so far' if r['isCurrent'] else 'Actual low'}", fmt_price(r["actualBottom"]))
            for k, name in floor_keys:
                p = r[k]
                if p is None: lines.append(f"      {name}: — (insufficient prior data)"); continue
                err = ((p-r["actualBottom"])/r["actualBottom"]*100) if r["actualBottom"] else None
                tag = (" v" if err is not None and abs(err)<20
                       else " ~" if err is not None and abs(err)<40
                       else " x" if err is not None else "")
                live = " (live)" if r["isCurrent"] else ""
                err_s = (f" · {'+' if err>=0 else ''}{err:.1f}%{tag}{live}") if err is not None else ""
                lines.append(f"      {name}: {fmt_price(p)}{err_s}")
            lines.append("")
        lines.append("  * No lookahead — only prior cycle data used per projection.")
        lines.append("  * Current cycle errors measured against ATH/low seen so far, not the final confirmed value.")

    hr("HALVING DATES")
    now_dt = datetime.now(timezone.utc)
    for i, h in enumerate(HALVINGS):
        hdt = parse_date(h)
        next_h = parse_date(HALVINGS[i+1]) if i+1 < len(HALVINGS) else None
        is_past    = hdt < now_dt and (not next_h or next_h < now_dt)
        is_current = hdt <= now_dt and next_h and next_h > now_dt
        status = "completed" if is_past else "current cycle" if is_current else "upcoming"
        if is_current and next_h:
            pct = min(100, (now_dt-hdt).days / (next_h-hdt).days * 100)
            extra = f" · {pct:.0f}% elapsed"
        elif not is_past:
            days_away = (hdt-now_dt).days
            extra = f" · {days_away:,}d away"
        else:
            extra = ""
        row(f"  C{i+1} halving", f"{h} [{status}{extra}]")

    lines.append(""); lines.append("="*60)
    lines.append("Built by Sirapob Dangpad — a numbers-obsessed nerd who finds")
    lines.append("beauty in price patterns and on-chain data. Still learning,")
    lines.append("still experimenting. This dashboard is a passion project, not")
    lines.append("professional financial analysis.")
    lines.append(""); lines.append("NOT FINANCIAL ADVICE. Do your own research.")
    lines.append("="*60)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"Generated: {now_str}")
    lines.append("Tip: paste this file into any AI assistant to ask questions")
    lines.append("about Bitcoin MVRV cycles and what the data might mean.")

    return "\n".join(lines)


def main():
    mvrv_path  = os.environ.get("MVRV_PATH",  "mvrv.json")
    price_path = os.environ.get("PRICE_PATH", "btc_daily_price.json")
    out_dir    = os.environ.get("OUT_DIR",    "exports")

    print(f"Loading {mvrv_path}...")
    raw_rows = load_mvrv(mvrv_path)
    print(f"  {len(raw_rows):,} MVRV data points")

    print(f"Loading {price_path}...")
    price_map = load_prices(price_path)
    print(f"  {len(price_map):,} price entries")

    print("Building enriched dataset...")
    data  = build_data(raw_rows, price_map)
    stats = build_stats(data)
    print(f"  {len(data):,} rows · {len(stats['cycleData'])} cycles detected")

    print("Running backtest...")
    all_results, completed_results = run_backtest(data, stats, price_map)

    print("Generating export text...")
    text = build_export(data, stats, price_map, all_results, completed_results)

    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = os.path.join(out_dir, f"mvrv_summary_{today}.txt")
    with open(out_path, "w") as f:
        f.write(text)
    print(f"✓ Written: {out_path}  ({len(text):,} chars)")


if __name__ == "__main__":
    main()
