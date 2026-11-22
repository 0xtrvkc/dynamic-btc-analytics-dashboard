"""
generate_summary.py
Headless port of the dashboard's analysis in index.html (enrichData, computeStats,
modelSet, runBacktest). Keep the two in sync when changing either.
Reads mvrv.json + btc_daily_price.json already in the repo,
computes the same stats, writes exports/mvrv_summary_YYYY-MM-DD.txt
WITHOUT touching any other files.
"""

import json, math, os, sys, urllib.request
from datetime import datetime, timezone, date, timedelta

# ── constants (mirror index.html) ─────────────────────────────────────────────
HALVING_EVENTS = [
    {"date": "2012-11-28", "confirmed": True},
    {"date": "2016-07-09", "confirmed": True},
    {"date": "2020-05-11", "confirmed": True},
    {"date": "2024-04-20", "confirmed": True},
    {"date": "2028-03-26", "confirmed": False},
    {"date": "2032-02-15", "confirmed": False},
    {"date": "2036-01-10", "confirmed": False},
]
HALVING_INTERVAL = 210000
# UTC block times of the halving blocks (mempool.space and Blockstream agree).
KNOWN_HALVING_TIMES = {1: "15:24:38", 2: "16:46:13", 3: "19:23:43", 4: "00:09:27"}
EXPLORER_APIS = ("https://mempool.space/api", "https://blockstream.info/api")
HALVINGS = [e["date"] for e in HALVING_EVENTS]
HALVING_DTS = []
CYCLE_LABELS = {}

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

def refresh_halving_dates():
    HALVINGS[:] = [e["date"] for e in HALVING_EVENTS]
    HALVING_DTS[:] = [parse_date(h) for h in HALVINGS]
    CYCLE_LABELS.clear()
    for i, e in enumerate(HALVING_EVENTS):
        nxt = HALVING_EVENTS[i+1] if i+1 < len(HALVING_EVENTS) else None
        CYCLE_LABELS[i+1] = f"{e['date'][:4]}–{nxt['date'][:4] if nxt else '?'}" + (
            " (est.)" if not e["confirmed"] or not (nxt and nxt["confirmed"]) else ""
        )

def explorer_get(base, path):
    req = urllib.request.Request(base + path, headers={"User-Agent": "BTC-Cycle-Analytics/1.0"})
    with urllib.request.urlopen(req, timeout=6) as res:
        return res.read().decode().strip()

def extend_estimated_halvings(latest_date):
    # Match the browser: keep two estimated boundaries beyond the latest data.
    while latest_date >= HALVING_EVENTS[-2]["date"] and len(HALVING_EVENTS) < 128:
        previous = parse_date(HALVING_EVENTS[-1]["date"])
        try:
            upcoming = previous.replace(year=previous.year + 4)
        except ValueError:  # 29 February in a non-leap year
            upcoming = previous.replace(year=previous.year + 4, month=3, day=1)
        HALVING_EVENTS.append({"date": upcoming.date().isoformat(), "confirmed": False})
    refresh_halving_dates()

def verify_future_halvings():
    """Confirm a new cycle only after two explorers agree and six later blocks exist."""
    for i in range(4, len(HALVING_EVENTS)):
        height = (i + 1) * HALVING_INTERVAL
        try:
            tips = [int(explorer_get(base, "/blocks/tip/height")) for base in EXPLORER_APIS]
            if any(t < height + 6 for t in tips):
                break
            blocks = []
            for base in EXPLORER_APIS:
                block_hash = explorer_get(base, f"/block-height/{height}")
                if len(block_hash) != 64 or any(x not in "0123456789abcdef" for x in block_hash):
                    raise ValueError("invalid block hash")
                block = json.loads(explorer_get(base, f"/block/{block_hash}"))
                if block.get("id") != block_hash or block.get("height") != height:
                    raise ValueError("block height/hash mismatch")
                blocks.append(block)
            if blocks[0]["id"] != blocks[1]["id"] or blocks[0]["timestamp"] != blocks[1]["timestamp"]:
                raise ValueError("explorers disagree")
            stamp = datetime.fromtimestamp(blocks[0]["timestamp"], tz=timezone.utc)
            if stamp > datetime.now(timezone.utc):
                raise ValueError("future block timestamp")
            actual = stamp.date().isoformat()
            old_date = parse_date(HALVING_EVENTS[i]["date"])
            shift = (parse_date(actual) - old_date).days
            HALVING_EVENTS[i] = {"date": actual, "time": stamp.strftime("%H:%M:%S"), "confirmed": True, "blockHash": blocks[0]["id"]}
            for later in HALVING_EVENTS[i+1:]:
                if not later["confirmed"]:
                    later["date"] = (parse_date(later["date"]) + timedelta(days=shift)).date().isoformat()
            print(f"Verified C{i+1} at block {height:,} ({actual} UTC)")
        except (OSError, ValueError, KeyError, TypeError, OverflowError, json.JSONDecodeError) as exc:
            print(f"C{i+1} remains an estimate: {exc}")
            break
    refresh_halving_dates()

refresh_halving_dates()

DAY = timedelta(days=1)

def assign_cycle(dt):
    c = 0
    for i, h in enumerate(HALVING_DTS):
        if HALVING_EVENTS[i]["confirmed"] and dt >= h:
            c = i + 1
    return c

def cycle_pct(dt, c):
    if c == 0 or c > len(HALVING_DTS):
        return None
    start = HALVING_DTS[c-1]
    end = HALVING_DTS[c] if c < len(HALVING_DTS) else start + timedelta(days=AVG_CYCLE_DAYS)
    return (dt - start) / (end - start) * 100

def finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v)

def median(arr):
    a = sorted(v for v in arr if finite(v))
    if not a: return None
    m = len(a) // 2
    return a[m] if len(a) % 2 else (a[m-1] + a[m]) / 2

def linreg(xs, ys):
    """Least squares. Returns (slope, intercept) or None when it cannot be fitted."""
    pts = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    n = len(pts)
    if n < 2: return None
    mx = sum(p[0] for p in pts) / n; my = sum(p[1] for p in pts) / n
    den = sum((x-mx)**2 for x, _ in pts)
    if not den > 0: return None
    slope = sum((x-mx)*(y-my) for x, y in pts) / den
    return slope, my - slope*mx

def logreg(xs, ys):
    return linreg([math.log(x) if x > 0 else float("nan") for x in xs], ys)

def positive(v):
    return v if finite(v) and v > 0 else None

def projected(reg, x, is_log=True):
    if not reg: return None
    slope, ic = reg
    return positive(slope * (math.log(x) if is_log else x) + ic)

def power_estimate(points, cycle):
    """Power-law fit ln(value) = a*ln(cycle) + b — always positive, like the dashboard."""
    a = [(c, v) for c, v in points if finite(v) and v > 0]
    if len(a) < 2: return None, len(a)
    reg = linreg([math.log(c) for c, _ in a], [math.log(v) for _, v in a])
    if not reg: return None, len(a)
    return positive(math.exp(reg[0]*math.log(cycle) + reg[1])), len(a)

CYCLE_TOP_WINDOW_DAYS = 730

def cycle_high_low(rows, key):
    """Halving-anchored extremes (same rule as the dashboard's Spiral tab):
    high = highest value within two years after the halving (the cycle top);
    low  = lowest value AFTER that high, up to the next halving (the bear-market low)."""
    r = [d for d in rows if finite(d.get(key)) and d[key] > 0]
    if not r: return None
    c = r[0]["cycle"]
    start = HALVING_DTS[c-1] if c and c <= len(HALVING_DTS) else r[0]["dt"]
    limit = start + timedelta(days=CYCLE_TOP_WINDOW_DAYS)
    hi = 0
    for i in range(1, len(r)):
        if r[i]["dt"] > limit: break
        if r[i][key] > r[hi][key]: hi = i
    lo = hi
    for i in range(hi+1, len(r)):
        if r[i][key] < r[lo][key]: lo = i
    return r[hi], r[lo]

# ── load data ─────────────────────────────────────────────────────────────────
def load_mvrv(path="mvrv.json"):
    with open(path) as f:
        raw = json.load(f)
    arr = raw.get("mvrv") or raw.get("values") or []
    daily = {}
    for p in arr:
        try:
            x = float(p["x"]); y = float(p.get("y"))
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y) and y > 0): continue
        if abs(x) < 1e11: x *= 1000
        dt = datetime.fromtimestamp(x/1000, tz=timezone.utc)
        day = dt.strftime("%Y-%m-%d")
        prev = daily.get(day)
        if prev is None or x >= prev[0]:
            daily[day] = (x, y)
    return [{"dt": parse_date(day), "date": day, "mvrv": y} for day, (_, y) in sorted(daily.items())]

def load_prices(path="btc_daily_price.json"):
    if not os.path.exists(path): return {}
    with open(path) as f:
        raw = json.load(f)
    out = {}
    for k, v in raw.items():
        try:
            p = float(v); parse_date(k)
        except (TypeError, ValueError):
            continue
        if math.isfinite(p) and p > 0: out[k] = p
    return out

def price_at_halving(price_map, halving_dt):
    """Close of the UTC day BEFORE the halving (the halving-day close already includes post-halving trading)."""
    if halving_dt is None: return None
    for back in range(1, HALVING_TOL_DAYS + 2):
        p = price_map.get((halving_dt - timedelta(days=back)).strftime("%Y-%m-%d"))
        if p: return p
    return None

# ── cycle signals (mirrors computeSignals() in index.html, tab "Cycle signals") ──
# Threshold = the mildest extreme seen across past cycles (lowest reading in each past bear market
# for buy-zone signals, highest in each past bull run for sell-zone signals). MVRV < 1 is a fixed rule.
SIG_TIME_NEAR_DAYS = 60
SIGNAL_DEFS = [
    # side, id, key, dir, label, fmt, near, fixed, window
    ("buy",  "b_mvrv",  "mvrv",       -1, "MVRV below 1",                       "f2",  ("rel", .1), 1.0,  False),
    ("buy",  "b_z",     "z",          -1, "Rolling MVRV z deeply negative",     "f2",  ("abs", .3), None, False),
    ("buy",  "b_w200",  "w200",       -1, "Price vs 200-week average",          "x",   ("rel", .1), None, False),
    ("buy",  "b_mayer", "mayer",      -1, "Mayer multiple",                     "x",   ("rel", .1), None, False),
    ("buy",  "b_dd",    "dd",         -1, "Drop from cycle top",                "pct", ("abs", 10), None, False),
    ("buy",  "b_ttop",  "daysTop",     0, "Days since cycle top",               "d",   None,        None, True),
    ("buy",  "b_thalv", "daysHalv",    0, "Days since halving (bottom timing)", "d",   None,        None, True),
    ("sell", "s_mvrv",  "mvrv",        1, "MVRV high",                          "f2",  ("rel", .1), None, False),
    ("sell", "s_z",     "z",           1, "Rolling MVRV z high",                "f2",  ("abs", .3), None, False),
    ("sell", "s_w200",  "w200",        1, "Price vs 200-week average",          "x",   ("rel", .1), None, False),
    ("sell", "s_mayer", "mayer",       1, "Mayer multiple",                     "x",   ("rel", .1), None, False),
    ("sell", "s_thalv", "daysHalv",    0, "Days since halving (top timing)",    "d",   None,        None, True),
    ("sell", "s_tbot",  "daysBottom",  0, "Days since last bear low",           "d",   None,        None, True),
]
SIG_BADGE = {"hit": "HIT", "near": "NEAR", "no": "NOT YET", "passed": "WINDOW PASSED", "na": "NO DATA"}

def sig_fmt(kind, v):
    if not finite(v): return "—"
    return {"f2": f"{v:.2f}", "x": f"{v:.2f}×", "pct": f"{v:.0f}%", "d": f"{round(v)} d"}[kind]

def signal_series(data, price_map):
    dates = sorted(price_map); px = [price_map[d] for d in dates]; pos = {d: i for i, d in enumerate(dates)}
    def roll(w):
        out = [None] * len(px); acc = 0.0; gap = 0
        for i in range(len(px)):
            acc += px[i]
            if i >= w: acc -= px[i-w]
            if i and parse_date(dates[i]) - parse_date(dates[i-1]) != DAY: gap = i
            if i >= w-1 and gap <= i-w+1: out[i] = acc / w
        return out
    ma200, ma1400 = roll(200), roll(1400)
    by_cycle = {}
    for d in data: by_cycle.setdefault(d["cycle"], []).append(d)
    lows = {}
    def prev_low(c):
        if c < 2: return None
        if c-1 not in lows:
            r = [d for d in by_cycle.get(c-1, []) if finite(d.get("price"))]
            hl = cycle_high_low(r, "price") if r else None
            lows[c-1] = hl[1] if hl else None
        return lows[c-1]
    out = []; cur = -1; hi = None
    for d in data:
        c = d["cycle"]; h = HALVING_DTS[c-1] if c >= 1 else None
        p = d["price"] if finite(d.get("price")) else None; i = pos.get(d["date"])
        if c != cur: cur = c; hi = None
        if p and h and d["dt"] <= h + timedelta(days=CYCLE_TOP_WINDOW_DAYS) and (hi is None or p > hi[0]): hi = (p, d["dt"])
        low = prev_low(c)
        days = lambda t: round((d["dt"] - t).total_seconds() / 86400)
        out.append({"dt": d["dt"], "date": d["date"], "cycle": c, "price": p, "mvrv": d["mvrv"],
                    "z": d["zscore"] if d["zReady"] and finite(d.get("zscore")) else None,
                    "mayer": p / ma200[i] if p and i is not None and ma200[i] else None,
                    "w200": p / ma1400[i] if p and i is not None and ma1400[i] else None,
                    "dd": (p / hi[0] - 1) * 100 if p and hi else None,
                    "daysTop": days(hi[1]) if p and hi else None,
                    "daysHalv": days(h) if h else None,
                    "daysBottom": days(low["dt"]) if low else None})
    return out

def signal_calibration(rows):
    last = rows[-1]["dt"]; out = {"sell": [], "buy": []}
    def ext(a, k, f):
        v = [r[k] for r in a if finite(r.get(k))]
        return f(v) if v and len(v) >= .9 * len(a) else None   # skip a cycle when the measure covers <90% of the phase
    for c in range(1, len(HALVING_DTS) + 1):
        h = HALVING_DTS[c-1]
        if not HALVING_EVENTS[c-1]["confirmed"]: continue
        cr = [r for r in rows if r["cycle"] == c and r["price"]]
        if len(cr) < 30: continue
        hl = cycle_high_low(cr, "price")
        if not hl: continue
        top, bot = hl
        end = h + timedelta(days=CYCLE_TOP_WINDOW_DAYS)
        if last >= end:
            w = [r for r in cr if r["dt"] <= end]
            out["sell"].append({"cycle": c, "date": top["date"], "price": top["price"], "mvrv": ext(w, "mvrv", max), "z": ext(w, "z", max),
                                "w200": ext(w, "w200", max), "mayer": ext(w, "mayer", max), "daysHalv": top["daysHalv"], "daysBottom": top["daysBottom"]})
        if c < len(HALVING_DTS) and HALVING_EVENTS[c]["confirmed"] and last >= HALVING_DTS[c]:
            w = [r for r in cr if r["dt"] >= top["dt"]]
            out["buy"].append({"cycle": c, "date": bot["date"], "price": bot["price"], "mvrv": ext(w, "mvrv", min), "z": ext(w, "z", min),
                               "w200": ext(w, "w200", min), "mayer": ext(w, "mayer", min), "dd": (bot["price"] / top["price"] - 1) * 100,
                               "daysTop": round((bot["dt"] - top["dt"]).total_seconds() / 86400), "daysHalv": bot["daysHalv"]})
    return out

def signal_status(rule, v):
    if not rule["ready"] or not finite(v): return "na"
    if rule["window"]:
        a, b = rule["range"]
        return "hit" if a <= v <= b else "passed" if v > b else "near" if v >= a - SIG_TIME_NEAR_DAYS else "no"
    if rule["dir"] * (v - rule["th"]) >= 0: return "hit"
    kind, amt = rule["near"]; gap = abs(v - rule["th"])
    return "near" if (gap <= amt if kind == "abs" else gap <= abs(rule["th"]) * amt) else "no"

def compute_signals(data, price_map):
    rows = signal_series(data, price_map); cal = signal_calibration(rows); now = rows[-1]; items = []
    for side, sid, key, dr, label, fmt, near, fixed, window in SIGNAL_DEFS:
        past = [(c["cycle"], c[key]) for c in cal[side] if finite(c.get(key))]; vals = [v for _, v in past]
        rule = {"side": side, "id": sid, "key": key, "dir": dr, "label": label, "fmt": fmt, "near": near,
                "fixed": fixed, "window": window, "past": past, "th": None, "range": None}
        if window:
            if len(vals) >= 2: rule["range"] = (min(vals), max(vals))
        elif fixed is not None: rule["th"] = fixed
        elif len(vals) >= 2: rule["th"] = max(vals) if dr < 0 else min(vals)
        rule["ready"] = rule["range"] is not None if window else rule["th"] is not None
        rule["value"] = now[key]; rule["status"] = signal_status(rule, now[key])
        items.append(rule)
    def side_sum(k):
        s = [i for i in items if i["side"] == k]; u = [i for i in s if i["status"] != "na"]
        return {"items": s, "total": len(u), "hit": sum(i["status"] == "hit" for i in u), "near": sum(i["status"] == "near" for i in u)}
    return {"now": now, "cal": cal, "items": items, "buy": side_sum("buy"), "sell": side_sum("sell")}

def signal_lean(S):
    sc = lambda s: (s["hit"] + .5 * s["near"]) / s["total"] if s["total"] else 0
    b, s = sc(S["buy"]), sc(S["sell"])
    if b >= .5 and b > s: return "Many bottom-like conditions"
    if s >= .5 and s > b: return "Many top-like conditions"
    if b > s + .2: return "Leaning toward bottom-like"
    if s > b + .2: return "Leaning toward top-like"
    return "Mixed / mid-cycle"

def signal_export_lines(S):
    L = []
    L.append(f"Buy-zone signals (like past bottoms): {S['buy']['hit']}/{S['buy']['total']} hit, {S['buy']['near']} near")
    L.append(f"Sell-zone signals (like past tops): {S['sell']['hit']}/{S['sell']['total']} hit, {S['sell']['near']} near")
    L.append(f"Reading: {signal_lean(S)}")
    for side, title, pastword in (("buy", "BUY-ZONE", "Lowest in past bear markets"), ("sell", "SELL-ZONE", "Highest in past bull runs")):
        L.append(""); L.append(f"  --- {title} ---")
        for i in S[side]["items"]:
            if i["window"]: rule = f"window {sig_fmt(i['fmt'], i['range'][0])} – {sig_fmt(i['fmt'], i['range'][1])}" if i["range"] else "needs 2+ completed cycles"
            elif i["th"] is not None: rule = ("≤ " if i["dir"] < 0 else "≥ ") + sig_fmt(i["fmt"], i["th"]) + (" (fixed rule)" if i["fixed"] is not None else " (mildest past cycle)")
            else: rule = "needs 2+ completed cycles"
            past = " · ".join(f"C{c} {sig_fmt(i['fmt'], v)}" for c, v in i["past"]) or "—"
            L.append(f"  [{SIG_BADGE[i['status']]}] {i['label']}: {sig_fmt(i['fmt'], i['value'])} · {rule}")
            L.append(f"      {('At past ' + ('bottoms' if side == 'buy' else 'tops')) if i['window'] else pastword}: {past}")
    L.append("  * Threshold = the mildest extreme across past cycles; few cycles exist, so treat as context. Descriptive only, not investment advice.")
    return L

# ── enrich rows (mirrors enrichData() in index.html) ──────────────────────────
def build_data(raw_rows, price_map):
    data = []
    mvrvs = [r["mvrv"] for r in raw_rows]
    by_date = {}
    prefix = [0.0]
    for v in mvrvs: prefix.append(prefix[-1] + v)
    last_gap = -1
    left = 0
    running_peak = {}
    cycle_peak = {}
    for r in raw_rows:
        c = assign_cycle(r["dt"]); cycle_peak[c] = max(cycle_peak.get(c, 0), r["mvrv"])
    for i, r in enumerate(raw_rows):
        dt = r["dt"]
        if i and dt - raw_rows[i-1]["dt"] != DAY: last_gap = i
        # rolling window: observations with date in (dt-365d, dt]
        while left < i and raw_rows[left]["dt"] <= dt - timedelta(days=ZSCORE_WINDOW): left += 1
        win = mvrvs[left:i+1]
        mean = sum(win) / len(win)
        std = math.sqrt(sum((v-mean)**2 for v in win) / len(win)) if len(win) > 1 else 0
        z = (r["mvrv"] - mean) / std if std > 1e-12 else None

        def ma(w):
            if i >= w-1 and last_gap <= i-w+1:
                return (prefix[i+1] - prefix[i+1-w]) / w
            return None
        def roc(w):
            j = by_date.get(dt - timedelta(days=w))
            return (r["mvrv"] / mvrvs[j] - 1) * 100 if j is not None else None
        by_date[dt] = i

        c = assign_cycle(dt)
        running_peak[c] = max(running_peak.get(c, 0), r["mvrv"])
        data.append({
            "dt": dt, "date": r["date"], "mvrv": r["mvrv"], "cycle": c, "cyclePct": cycle_pct(dt, c),
            "zscore": z, "zReady": len(win) == ZSCORE_WINDOW,
            "ma20": ma(20), "ma50": ma(50), "ma200": ma(200), "roc30": roc(ROC_SHORT), "roc90": roc(ROC_LONG),
            "price": price_map.get(r["date"]),
            "drawdown": (r["mvrv"] / running_peak[c] - 1) * 100 if c else None,
        })
    return data

def build_stats(data):
    last = data[-1]
    groups = {}
    for d in data: groups.setdefault(d["cycle"], []).append(d)
    cycles = sorted(c for c in groups if c > 0)
    cycle_data = []
    for c in cycles:
        pts = groups[c]
        pk, tr = cycle_high_low(pts, "mvrv")
        start = HALVING_DTS[c-1]
        end = HALVING_DTS[c] if c < len(HALVING_DTS) else None
        confirmed = HALVING_EVENTS[c-1]["confirmed"] and c < len(HALVING_EVENTS) and HALVING_EVENTS[c]["confirmed"]
        complete = bool(end and confirmed and last["dt"] >= end)
        expected = round((end - start).days) if end else None
        coverage = len(pts) / expected if expected else None
        usable = bool(complete and coverage >= .95 and pts[0]["dt"] - start <= timedelta(days=3)
                      and end - pts[-1]["dt"] <= timedelta(days=3))
        cycle_data.append({
            "cycle": c, "days": len(pts), "pts": pts,
            "peak": pk["mvrv"], "peakDate": pk["date"], "trough": tr["mvrv"], "troughDate": tr["date"],
            "below1": sum(1 for d in pts if d["mvrv"] < 1), "below1_5": sum(1 for d in pts if d["mvrv"] < 1.5),
            "above2": sum(1 for d in pts if d["mvrv"] >= 2), "above3": sum(1 for d in pts if d["mvrv"] >= 3),
            "complete": complete, "usable": usable, "boundariesConfirmed": bool(confirmed),
        })
    training = [cd for cd in cycle_data if cd["usable"]]
    xs = [cd["cycle"] for cd in training]
    return {
        "last": last, "mean": sum(d["mvrv"] for d in data) / len(data),
        "peakRow": max(data, key=lambda d: d["mvrv"]), "botRow": min(data, key=lambda d: d["mvrv"]),
        "cycleData": cycle_data, "byCycle": groups, "training": xs,
        "logR": logreg(xs, [cd["peak"] for cd in training]), "linR": linreg(xs, [cd["peak"] for cd in training]),
        "troughLogR": logreg(xs, [cd["trough"] for cd in training]), "troughLinR": linreg(xs, [cd["trough"] for cd in training]),
        "hasPrice": any(d["price"] for d in data), "nextCycle": max(1, last["cycle"] + 1),
    }

# ── price models (mirror cycleModelData() / modelSet() / runBacktest()) ───────
def cycle_model_data(stats, price_map, before_cycle):
    out = []
    for cd in stats["cycleData"]:
        if not (cd["usable"] and cd["cycle"] < before_cycle): continue
        rows = cd["pts"]
        priced = [d for d in rows if d["price"]]
        if not rows or len(priced) / len(rows) < .95: continue
        high, low = cycle_high_low(priced, "price")
        at_peak = price_map.get(cd["peakDate"]); at_trough = price_map.get(cd["troughDate"])
        after_pk = [d["price"] for d in priced if d["date"] >= cd["peakDate"]]
        after_tr = [d["price"] for d in priced if d["date"] >= cd["troughDate"]]
        out.append({**cd, "high": high["price"], "low": low["price"],
                    "halving": price_at_halving(price_map, HALVING_DTS[cd["cycle"]-1]),
                    "upside": max(after_pk) / at_peak - 1 if at_peak and after_pk else None,
                    "downside": min(after_tr) / at_trough - 1 if at_trough and after_tr else None})
    return out

MODEL_NAMES = {"m1": "MVRV Upside", "m2": "Halving Multiplier", "m3": "ATH Multiplier", "m4": "MVRV x Realized Price",
               "bm1": "MVRV Downside", "bm2": "Halving Floor Ratio", "bm3": "Bottom Multiplier", "bm4": "MVRV Trough x Realized Price",
               "consensus": "Ceiling ensemble", "consensusBot": "Floor ensemble"}

def model_set(data, stats, price_map, target, origin, live=False):
    prior = cycle_model_data(stats, price_map, target)
    h_price = price_at_halving(price_map, HALVING_DTS[target-1])
    mult, mult_n = power_estimate([(c["cycle"], c["high"]/c["halving"]) for c in prior if c["halving"]], target)
    floor, floor_n = power_estimate([(c["cycle"], c["low"]/c["halving"]) for c in prior if c["halving"]], target)
    consecutive = [(a, b) for a, b in zip(prior, prior[1:]) if b["cycle"] == a["cycle"] + 1]
    ath, ath_n = power_estimate([(b["cycle"], b["high"]/a["high"]) for a, b in consecutive], target)
    bottom, bottom_n = power_estimate([(b["cycle"], b["low"]/a["low"]) for a, b in consecutive], target)
    previous = next((c for c in prior if c["cycle"] == target - 1), None)
    peak = projected(logreg([c["cycle"] for c in prior], [c["peak"] for c in prior]), target)
    trough = projected(logreg([c["cycle"] for c in prior], [c["trough"] for c in prior]), target)
    visible = [d for d in data if d["dt"] <= origin]
    anchor = visible[-1] if visible else None
    realized = anchor["price"] / anchor["mvrv"] if anchor and anchor["price"] and origin - anchor["dt"] <= timedelta(days=3) else None
    current = [d for d in visible if d["cycle"] == target]
    hl = cycle_high_low(current, "mvrv")
    pk, tr = hl if hl else (None, None)
    ups = [c["upside"] for c in prior if finite(c["upside"])]
    downs = [c["downside"] for c in prior if finite(c["downside"])]
    r = {
        "m1": positive(pk["price"] * (1 + median(ups))) if live and pk and pk["price"] and len(ups) >= 2 else None,
        "bm1": positive(tr["price"] * (1 + median(downs))) if live and tr and tr["price"] and len(downs) >= 2 else None,
        "m2": positive(h_price * mult) if h_price and mult else None,
        "m3": positive(previous["high"] * ath) if previous and ath else None,
        "m4": positive(realized * peak) if realized and peak else None,
        "bm2": positive(h_price * floor) if h_price and floor else None,
        "bm3": positive(previous["low"] * bottom) if previous and bottom else None,
        "bm4": positive(realized * trough) if realized and trough else None,
        "halvingPrice": h_price, "origin": origin.strftime("%Y-%m-%d"), "training": [c["cycle"] for c in prior],
        "n": {"m1": len(ups), "bm1": len(downs), "m2": mult_n, "m3": ath_n, "m4": len(prior),
              "bm2": floor_n, "bm3": bottom_n, "bm4": len(prior)},
    }
    if not live and not HALVING_EVENTS[target-1]["confirmed"]:
        for k in ("m1", "m2", "m3", "m4", "bm1", "bm2", "bm3", "bm4"): r[k] = None
    ceil = [r[k] for k in ("m2", "m3", "m4") if r[k]]
    flo = [r[k] for k in ("bm2", "bm3") if r[k]]
    r["consensus"] = median(ceil); r["consensusBot"] = median(flo)
    r["ceilingRange"] = (min(ceil), max(ceil)) if ceil else None
    r["floorRange"] = (min(flo), max(flo)) if flo else None
    return r

def run_backtest(data, stats, price_map):
    results = []
    for cd in stats["cycleData"]:
        c = cd["cycle"]
        if c < 2: continue
        # Forecast origin = close of the UTC day before the halving: no post-halving data.
        origin = HALVING_DTS[c-1] - DAY
        m = model_set(data, stats, price_map, c, origin, live=False)
        priced = [d for d in cd["pts"] if d["price"]]
        hl = cycle_high_low(priced, "price")
        cov = len(priced) / (len(cd["pts"]) or 1)
        results.append({**m, "cycle": c, "isCurrent": c == stats["last"]["cycle"],
                        "actualATH": hl[0]["price"] if hl else None, "actualBottom": hl[1]["price"] if hl else None,
                        "evaluable": cd["usable"] and cov >= .95})
    completed = [r for r in results if r["evaluable"] and not r["isCurrent"]]
    return results, completed

def error_stats(results, key, actual_key):
    e = [(r[key] / r[actual_key] - 1) * 100 for r in results if r.get(key) and r.get(actual_key)]
    if not e: return {"n": 0}
    return {"n": len(e), "bias": sum(e)/len(e), "mape": sum(abs(x) for x in e)/len(e), "medianAPE": median([abs(x) for x in e])}

def ma_crossovers(data):
    last_sign = 0; found = []
    for d in data:
        if d["ma20"] is None or d["ma50"] is None:
            last_sign = 0; continue
        diff = d["ma20"] - d["ma50"]
        sign = 0 if abs(diff) < 1e-12 else (1 if diff > 0 else -1)
        if sign and last_sign and sign != last_sign:
            found.append({**d, "type": "Golden cross" if sign > 0 else "Death cross"})
        if sign: last_sign = sign
    return found

# ── format helpers ────────────────────────────────────────────────────────────
def fmt_price(p):
    return f"${round(p):,}" if finite(p) and p > 0 else "—"

def fmt_num(v, digits=3):
    return f"{v:.{digits}f}" if finite(v) else "—"

def rolling_state(d):
    if not d["zReady"] or d["zscore"] is None: return "Insufficient history"
    z = d["zscore"]
    return ("Far below 1y mean" if z < ZSCORE_CAPIT else "Below 1y mean" if z < 0
            else "Near / above 1y mean" if z < ZSCORE_CAUTION else "Elevated vs 1y mean")

def ma_state(d):
    a, b, c = d["ma20"], d["ma50"], d["ma200"]
    if None in (a, b, c): return "Insufficient history"
    return "MA20 > MA50 > MA200" if a > b > c else "MA20 < MA50 < MA200" if a < b < c else "Mixed / equal averages"

def signed(v, digits=1):
    return f"{'+' if v >= 0 else ''}{v:.{digits}f}%" if finite(v) else "—"

# ── main export writer ────────────────────────────────────────────────────────
def build_export(data, stats, price_map, all_results, completed_results):
    s = stats; l = s["last"]; has = s["hasPrice"]
    lines = []
    def hr(title): lines.extend(["", f"=== {title} ==="])
    def row(label, val): lines.append(f"{label}: {val}")
    training = set(s["training"])

    hr("CURRENT STATUS")
    row("MVRV date", l["date"])
    if price_map: row("Latest BTC price date", max(price_map))
    row("MVRV", f"{l['mvrv']:.3f}")
    row("Rolling MVRV z (365d)", fmt_num(l["zscore"]) + ("" if l["zReady"] else " (partial window)"))
    row("Rolling z position", rolling_state(l))
    lines.append("  Note: rolling z = (MVRV - trailing 365d mean) / population std of MVRV. This is NOT the")
    lines.append("  conventional 'MVRV Z-Score' ((market cap - realized cap) / std of market cap).")
    row("MA20", fmt_num(l["ma20"])); row("MA50", fmt_num(l["ma50"])); row("MA200", fmt_num(l["ma200"]))
    row("MA alignment", ma_state(l))
    row("MVRV ROC 30d", f"{l['roc30']:.1f}%" if l["roc30"] is not None else "—")
    row("MVRV ROC 90d", f"{l['roc90']:.1f}%" if l["roc90"] is not None else "—")
    if has and l["price"]: row("BTC price on MVRV date", fmt_price(l["price"]))
    row("Dataset MVRV peak", f"{s['peakRow']['mvrv']:.3f} on {s['peakRow']['date']}")
    row("Dataset MVRV low", f"{s['botRow']['mvrv']:.3f} on {s['botRow']['date']}")
    row("Dataset mean MVRV", f"{s['mean']:.3f}")
    row("Data range", f"{data[0]['date']} to {data[-1]['date']}")
    row("Daily observations", f"{len(data):,}")
    row("Completed cycles used for fitting", ", ".join(f"C{c}" for c in s["training"]) or "none")

    hr("CURRENT CYCLE POSITION")
    cc = l["cycle"]
    cd = next((c for c in s["cycleData"] if c["cycle"] == cc), None)
    row("Current cycle", f"C{cc}" + (f" ({CYCLE_LABELS[cc]})" if cc in CYCLE_LABELS else ""))
    row("Cycle position", f"{l['cyclePct']:.1f}%" if l["cyclePct"] is not None else "unknown")
    if cd:
        row("Cycle MVRV peak so far", f"{cd['peak']:.3f} on {cd['peakDate']}")
        row("Current MVRV vs cycle peak", f"{l['mvrv']/cd['peak']*100:.0f}% of cycle peak")
        row("Days in current cycle", cd["days"])
        row("Current drawdown from cycle MVRV peak", f"{(l['mvrv']-cd['peak'])/cd['peak']*100:.1f}%")

    hr("CYCLE SUMMARY  (peak = highest MVRV within 2y of the halving; trough = lowest MVRV after that peak)")
    for c in s["cycleData"]:
        lines.append("")
        lines.append(f"Cycle {c['cycle']}" + (f" ({CYCLE_LABELS[c['cycle']]})" if c["cycle"] in CYCLE_LABELS else "")
                     + ("" if c["complete"] else " — open, values provisional") + ":")
        row("  Peak MVRV", f"{c['peak']:.3f} on {c['peakDate']}")
        row("  Trough MVRV", f"{c['trough']:.3f} on {c['troughDate']}")
        row("  Peak-to-trough range", f"{(c['peak']-c['trough'])/c['peak']*100:.0f}% compression")
        row("  Days of data", c["days"])
        if has:
            pp = price_map.get(c["peakDate"]); tp = price_map.get(c["troughDate"])
            if pp: row("  BTC price at MVRV peak", fmt_price(pp))
            if tp: row("  BTC price at MVRV trough", fmt_price(tp))

    hr("DRAWDOWN — Max MVRV drawdown from running cycle peak")
    for c in s["cycleData"]:
        pts = [d for d in c["pts"] if d["drawdown"] is not None]
        if not pts: continue
        worst = min(pts, key=lambda d: d["drawdown"])
        lines.append(""); lines.append(f"Cycle {c['cycle']}:")
        row("  Max drawdown", f"{worst['drawdown']:.1f}% on {worst['date']}")
        if has and worst["price"]: row("  BTC price at worst drawdown", fmt_price(worst["price"]))

    hr("MA CROSSOVERS — MA20 vs MA50 of MVRV (full windows only)")
    crossovers = ma_crossovers(data)
    if crossovers:
        for x in crossovers:
            info = f"C{x['cycle']} · MVRV {x['mvrv']:.3f}"
            if has and x["price"]: info += f" · {fmt_price(x['price'])}"
            row(f"  {x['date']} {x['type']}", info)
        lx = crossovers[-1]
        row("Last crossover", f"{lx['type']} on {lx['date']} ({(l['dt']-lx['dt']).days}d before latest data)")
    else:
        lines.append("  No MA20/MA50 crossovers detected.")
    if l["ma20"] is not None and l["ma50"] is not None:
        row("Current MA20 vs MA50", "MA20 above MA50" if l["ma20"] > l["ma50"] else "MA20 below MA50")

    hr("ZONE ANALYSIS — Days in each MVRV zone per cycle")
    for c in s["cycleData"]:
        lines.append(""); lines.append(f"Cycle {c['cycle']}:")
        d = c["days"]
        bands = [("Below 1.0", c["below1"]), ("1.0-1.5", c["below1_5"]-c["below1"]),
                 ("1.5-2.0", d-c["above2"]-c["below1_5"]), ("2.0-3.0", c["above2"]-c["above3"]), ("Above 3.0", c["above3"])]
        for label, n in bands: row(f"  {label}", f"{n}d ({n/d*100:.0f}%)")
        if has:
            for lo, hi, label in [(0,1,"Below 1.0"),(1,1.5,"1.0-1.5"),(1.5,2,"1.5-2.0"),(2,3,"2.0-3.0"),(3,9999,"Above 3.0")]:
                zp = [p["price"] for p in c["pts"] if lo <= p["mvrv"] < hi and p["price"]]
                if zp: row(f"  Avg BTC price in {label}", fmt_price(sum(zp)/len(zp)))
    m = l["mvrv"]
    cur_zone = "Below 1.0" if m < 1 else "1.0-1.5" if m < 1.5 else "1.5-2.0" if m < 2 else "2.0-3.0" if m < 3 else "Above 3.0"
    lines.append(""); row("Current MVRV zone", f"{cur_zone} (MVRV {m:.3f})")

    if has:
        hr("PRICE PEAK DIVERGENCE — MVRV peak vs BTC price top (highest close within 2y of the halving)")
        diffs, ups = [], []
        for c in s["cycleData"]:
            pts = [d for d in c["pts"] if d["price"]]
            if not pts: continue
            best = cycle_high_low(pts, "price")[0]
            days_diff = (best["dt"] - parse_date(c["peakDate"])).days
            at_pk = price_map.get(c["peakDate"])
            after = [d["price"] for d in pts if d["date"] >= c["peakDate"]]
            rem = (max(after)/at_pk - 1)*100 if at_pk and after else None
            if c["cycle"] in training:
                diffs.append(days_diff)
                if rem is not None: ups.append(rem)
            lines.append(""); lines.append(f"Cycle {c['cycle']}" + ("" if c["complete"] else " (open — provisional)") + ":")
            row("  BTC price high", f"{fmt_price(best['price'])} on {best['date']}")
            row("  MVRV at price high", f"{best['mvrv']:.3f}")
            row("  MVRV own peak", f"{c['peak']:.3f} on {c['peakDate']}")
            if at_pk: row("  Price at MVRV peak", fmt_price(at_pk))
            if rem is not None: row("  Further upside after MVRV peaked", f"+{rem:.0f}%")
            row("  Lead/lag", f"Price peaked {days_diff}d AFTER MVRV" if days_diff > 0
                else f"Price peaked {-days_diff}d BEFORE MVRV" if days_diff < 0 else "Same day")
        if diffs:
            lines.append("")
            row(f"  Median lead/lag (completed cycles, n={len(diffs)})", f"{median(diffs):.0f}d")
            if ups: row(f"  Median further upside after MVRV peaked (n={len(ups)})", f"+{median(ups):.0f}%")

        hr("PRICE BOTTOM DIVERGENCE — MVRV trough vs BTC price low (lowest close after the cycle's price top)")
        diffs, downs = [], []
        for c in s["cycleData"]:
            pts = [d for d in c["pts"] if d["price"]]
            if not pts: continue
            worst = cycle_high_low(pts, "price")[1]
            days_diff = (worst["dt"] - parse_date(c["troughDate"])).days
            at_tr = price_map.get(c["troughDate"])
            after = [d["price"] for d in pts if d["date"] >= c["troughDate"]]
            fd = (min(after)/at_tr - 1)*100 if at_tr and after else None
            if c["cycle"] in training:
                diffs.append(days_diff)
                if fd is not None: downs.append(fd)
            lines.append(""); lines.append(f"Cycle {c['cycle']}" + ("" if c["complete"] else " (open — provisional)") + ":")
            row("  BTC price low", f"{fmt_price(worst['price'])} on {worst['date']}")
            row("  MVRV at price low", f"{worst['mvrv']:.3f}")
            row("  MVRV own trough", f"{c['trough']:.3f} on {c['troughDate']}")
            if at_tr: row("  Price at MVRV trough", fmt_price(at_tr))
            if fd is not None: row("  Further downside after MVRV troughed", f"{fd:.0f}%")
            row("  Lead/lag", f"Price bottomed {days_diff}d AFTER MVRV" if days_diff > 0
                else f"Price bottomed {-days_diff}d BEFORE MVRV" if days_diff < 0 else "Same day")
        if diffs:
            lines.append("")
            row(f"  Median lead/lag (completed cycles, n={len(diffs)})", f"{median(diffs):.0f}d")
            if downs: row(f"  Median further downside after MVRV troughed (n={len(downs)})", f"{median(downs):.0f}%")

    hr(f"REGRESSION PROJECTIONS — Cycle peak & trough MVRV (fitted on {len(s['training'])} completed cycles)")
    for ri in range(1, s["nextCycle"] + 2):
        row(f"  C{ri} peak (log/linear)", f"{fmt_num(projected(s['logR'], ri))} / {fmt_num(projected(s['linR'], ri, False))}")
        row(f"  C{ri} trough (log/linear)", f"{fmt_num(projected(s['troughLogR'], ri))} / {fmt_num(projected(s['troughLinR'], ri, False))}")
    lines.append("  * '—' = the fit extrapolates to zero or below. Few data points: treat as illustration only.")

    if has:
        cur = model_set(data, s, price_map, l["cycle"], l["dt"], live=True) if l["cycle"] > 0 else None
        hr(f"PRICE SCENARIOS — current cycle, as of {l['date']}")
        if cur:
            for title, keys, ens, rng in [("CEILING", ("m1","m2","m3","m4"), "consensus", "ceilingRange"),
                                          ("FLOOR", ("bm1","bm2","bm3","bm4"), "consensusBot", "floorRange")]:
                lines.append(""); lines.append(f"  --- {title} MODELS ---")
                for k in keys:
                    role = ("conditional, not in ensemble" if k in ("m1","bm1")
                            else "extra scenario, not in ensemble" if k == "bm4" else "in ensemble")
                    row(f"  {MODEL_NAMES[k]}", f"{fmt_price(cur[k])}  [n={cur['n'][k]} · {role}]")
                lines.append("")
                row(f"  {MODEL_NAMES[ens]} (median)", fmt_price(cur[ens]))
                if cur[rng]: row(f"  {title.title()} model spread", f"{fmt_price(cur[rng][0])} – {fmt_price(cur[rng][1])}  (not a probability interval)")
            if cur["halvingPrice"]:
                lines.append(""); row("  BTC pre-halving close (current cycle)", fmt_price(cur["halvingPrice"]))
        lines.append("  * Ensembles are the plain median of the eligible models; nothing is trimmed. Not financial advice.")

        hr("BACKTEST — model accuracy on completed cycles")
        lines.append("Each forecast is frozen at the close of the UTC day before that cycle's halving, using only")
        lines.append("cycles completed before it. MVRV Upside/Downside need a future turning point, so they are not scored.")
        lines.append("Cycle high = highest close within 2y of the halving; low = lowest close AFTER that high. Error = (predicted / actual - 1) x 100.")
        lines.append("Quality labels (good <20% · ok <40% · poor) are shown only when n >= 3.")
        lines.append("")
        for title, keys, actual in [("CEILING", ("m2","m3","m4","consensus"), "actualATH"),
                                    ("FLOOR", ("bm2","bm3","consensusBot"), "actualBottom")]:
            lines.append(f"--- {title} accuracy ---")
            for k in keys:
                st = error_stats(completed_results, k, actual)
                if not st["n"]:
                    row(f"  {MODEL_NAMES[k]}", "no scored forecasts yet"); continue
                q = ("good" if st["mape"] < 20 else "ok" if st["mape"] < 40 else "poor") if st["n"] >= 3 else "too few cycles to grade"
                row(f"  {MODEL_NAMES[k]}", f"n={st['n']} · bias {signed(st['bias'])} · mean abs {st['mape']:.1f}% · {q}")
            lines.append("")
        lines.append("--- Per-cycle breakdown ---")
        for r in all_results:
            lines.append("")
            lines.append(f"  C{r['cycle']}" + (" (open — errors vs values so far)" if r["isCurrent"] else
                                              "" if r["evaluable"] else " (incomplete coverage — not scored)")
                         + f" · forecast origin {r['origin']}:")
            if r["halvingPrice"]: row("    Pre-halving close", fmt_price(r["halvingPrice"]))
            for label, keys, actual in [("High", ("m2","m3","m4","consensus"), "actualATH"),
                                        ("Low", ("bm2","bm3","consensusBot"), "actualBottom")]:
                row(f"    {'Actual ' + label.lower() if not r['isCurrent'] else label + ' so far'}", fmt_price(r[actual]))
                for k in keys:
                    p = r[k]
                    if not p: lines.append(f"      {MODEL_NAMES[k]}: — (insufficient prior cycles)"); continue
                    err = (p / r[actual] - 1) * 100 if r[actual] else None
                    lines.append(f"      {MODEL_NAMES[k]}: {fmt_price(p)} · {signed(err)}")

    if has:
        hr(f"CYCLE SIGNALS — buy-zone (past bottoms) & sell-zone (past tops), as of {l['date']}")
        lines.extend(signal_export_lines(compute_signals(data, price_map)))

    hr("HALVING DATES")
    now_dt = l["dt"]
    for i, h in enumerate(HALVINGS):
        hdt = parse_date(h)
        next_h = parse_date(HALVINGS[i+1]) if i+1 < len(HALVINGS) else None
        next_confirmed = i+1 < len(HALVING_EVENTS) and HALVING_EVENTS[i+1]["confirmed"]
        is_past = bool(next_h and next_h <= now_dt and HALVING_EVENTS[i]["confirmed"] and next_confirmed)
        is_current = HALVING_EVENTS[i]["confirmed"] and hdt <= now_dt and (not next_h or not next_confirmed or next_h > now_dt)
        status = ("completed" if is_past else "latest observed cycle" if is_current else
                  "confirmed boundary" if HALVING_EVENTS[i]["confirmed"] else "estimated boundary — unconfirmed")
        if is_current and next_h:
            pct = min(100, (now_dt-hdt).days / (next_h-hdt).days * 100)
            extra = f" · {pct:.0f}% of {'confirmed' if next_confirmed else 'estimated'} interval"
            if now_dt > next_h: extra += " · estimate passed"
        elif not is_past:
            days_away = (hdt-now_dt).days
            extra = f" · {days_away:,}d from latest data" if days_away >= 0 else " · estimate passed"
        else:
            extra = ""
        height = (i+1)*HALVING_INTERVAL
        t = HALVING_EVENTS[i].get("time") or KNOWN_HALVING_TIMES.get(i+1)
        when = f"{h} {t} UTC" if HALVING_EVENTS[i]["confirmed"] and t else (h if HALVING_EVENTS[i]["confirmed"] else f"~{h} (estimate)")
        row(f"  C{i+1} halving", f"{when} · block {height:,} [{status}{extra}]")
        if HALVING_EVENTS[i]["confirmed"]:
            lines.append(f"      source: https://mempool.space/block/{height} · https://blockstream.info/block-height/{height}")
    lines.append("  Sources: halving block timestamps from mempool.space and Blockstream (cross-checked).")
    lines.append("  Future dates are estimates, not on-chain facts, until the block is mined and both explorers agree.")

    lines.append(""); lines.append("="*60)
    lines.append("Built by Sirapob Dangpad — a numbers-obsessed nerd who finds")
    lines.append("beauty in price patterns and on-chain data. Still learning,")
    lines.append("still experimenting. This dashboard is a passion project, not")
    lines.append("professional financial analysis.")
    lines.append(""); lines.append("NOT FINANCIAL ADVICE. Do your own research.")
    lines.append("="*60)
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
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
    extend_estimated_halvings(raw_rows[-1]["date"])
    if os.environ.get("SKIP_CHAIN_CHECK") != "1":
        verify_future_halvings()

    print(f"Loading {price_path}...")
    price_map = load_prices(price_path)
    print(f"  {len(price_map):,} price entries")

    data  = build_data(raw_rows, price_map)
    stats = build_stats(data)
    print(f"  {len(data):,} rows · {len(stats['cycleData'])} cycles detected")
    all_results, completed_results = run_backtest(data, stats, price_map)
    text = build_export(data, stats, price_map, all_results, completed_results)

    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = os.path.join(out_dir, f"mvrv_summary_{today}.txt")
    with open(out_path, "w") as f:
        f.write(text)
    print(f"✓ Written: {out_path}  ({len(text):,} chars)")

    # Keep only the latest export in the working tree; older days remain in git history.
    for fname in os.listdir(out_dir):
        if fname.startswith("mvrv_summary_") and fname.endswith(".txt") and fname != os.path.basename(out_path):
            os.remove(os.path.join(out_dir, fname))
            print(f"  Removed old export: {fname}")


if __name__ == "__main__":
    main()
