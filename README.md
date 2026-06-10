MVRV Analytics Dashboard
========================
https://0xtrvkc.github.io/dynamic-btc-analytics-dashboard/

Bitcoin on-chain cycle analysis. Entirely client-side.
No backend, no database, no login.


WHAT IT DOES
------------
Loads MVRV data + historical price data, then throws a bunch of
cycle analysis at you:

  - Z-score (rolling 365-day window, not all-time — avoids 2011 anchoring)
  - All halving cycles overlaid on one chart
  - MA20/50/200 with crossover events flagged
  - 30d and 90d rate-of-change momentum
  - Peak drawdown per cycle
  - Price projections via 4 independent models:
      - MVRV Upside        (price at MVRV peak × median remaining upside)
      - Halving Multiplier (halving price × log-decay fitted multiplier)
      - ATH Multiplier     (prev ATH × log-decay ratio)
      - MVRV × Realized Cap
    IQR consensus across those four. Outliers get dropped automatically.
  - Backtest tab — every model re-run with no-lookahead on completed cycles
    so you can see whether any of this actually works historically

Export button spits out a .txt summary you can paste into an LLM
or just keep as a timestamped record.


FILES
-----
index.html                   The whole app. All logic lives here.
btc_daily_price.json         Daily BTC closes. Auto-updated by CI.
mvrv.json                    MVRV data. Auto-updated by CI (blockchain.com scrape).
generate_price_json.py       Price data refresh script (called by Actions).
generate_summary.py          Headless port of the export function. No deps.
exports/                     Auto-exported summaries, one .txt per day.

.github/workflows/
  update_price_json.yml      Daily — downloads Kaggle CSV, regenerates price JSON.
  update-mvrv.yml            Daily — Playwright scrapes blockchain.com for MVRV.
  auto_export_summary.yml    Hourly — runs generate_summary.py, commits to exports/.


HOW DATA GETS IN
----------------
MVRV data:
  The dashboard can load a JSON you manually export from blockchain.com,
  OR it auto-fetches mvrv.json straight from this repo (already there).
  The CI scrape keeps mvrv.json current daily so you don't have to touch it.

Price data:
  btc_daily_price.json is rebuilt daily from the Kaggle BTC 1-min dataset.
  Requires KAGGLE_USERNAME and KAGGLE_KEY in repo secrets.
  Without those secrets the price workflow will fail — everything else still works,
  you just lose the price overlay.


AUTO-EXPORT
-----------
generate_summary.py runs every hour via GitHub Actions.
Reads mvrv.json + btc_daily_price.json, computes the same stats as the
browser export, writes exports/mvrv_summary_YYYY-MM-DD.txt.

Once a day's file exists it won't overwrite it.
No secrets needed. Runtime is ~4 seconds.

To deploy: drop generate_summary.py in repo root and add
auto_export_summary.yml to .github/workflows/. That's it.


CONFIG
------
All the tunable knobs are at the top of index.html:

  ZSCORE_WINDOW: 365          rolling window for z-score (days)
  ZSCORE_CAPITULATION: -1.5   below this = capitulation signal
  ZSCORE_CAUTION: 1.0         above this = caution signal
  ROC_SHORT: 30               short momentum window (days)
  ROC_LONG: 90                long momentum window (days)
  AVG_CYCLE_DAYS: 1422        used to estimate % progress in current cycle

HALVINGS array is also in index.html — update it if a new halving gets added
or you want to adjust the estimated future dates.


STACK
-----
Vanilla JS. Chart.js 4.4. 98.css for the UI chrome.
Python 3.11 for the CI scripts (stdlib only — no pip install for generate_summary.py).
GitHub Actions for all automation.

No build step. No node_modules. index.html just works.


NOT FINANCIAL ADVICE.
