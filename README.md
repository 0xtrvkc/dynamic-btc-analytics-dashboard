# MVRV Analytics Dashboard

A single-file Bitcoin on-chain analytics dashboard focused on the **MVRV ratio** (Market Value to Realized Value). No backend, no login, no clutter — just drop your data and analyze.

Live at: **https://0xtrvkc.github.io/dynamic-btc-analytics-dashboard/**

---

## What is MVRV?

MVRV compares Bitcoin's current market cap to its realized cap (the value of all coins at the price they last moved). It's one of the most reliable on-chain signals for identifying cycle tops and bottoms:

- **MVRV > 3.0** → historically overvalued, approaching cycle peak territory
- **MVRV 1.5–3.0** → mid-cycle, neutral to bullish
- **MVRV < 1.0** → historically undervalued, strong accumulation zone

---

## Getting Started

### 1. Get your MVRV data
Go to [blockchain.com/explorer/charts/mvrv](https://www.blockchain.com/explorer/charts/mvrv) → select **ALL** → click **Download JSON**

### 2. Open the dashboard
Open the live link above or open `index.html` locally in any browser.

### 3. Drop your JSON
Drag and drop the downloaded `.json` file onto the upload area. The dashboard loads instantly.

### 4. BTC price data (auto)
Price data is fetched automatically in the background — no upload needed. It updates daily via GitHub Actions. If it loads successfully you'll see a green status below the upload area.

---

## Panels

| Panel | What it shows |
|---|---|
| **Overview** | Current MVRV, Z-score, all-time peak/bottom, MA chart, cycle summary table |
| **Z-Score** | Expanding-window Z-score with historical buy/sell zones |
| **Momentum** | 30d and 90d rate of change |
| **Cycle Overlay** | All cycles aligned on a 0–100% time axis — MVRV and BTC price |
| **Drawdown** | MVRV drawdown from cycle peak, by cycle position |
| **MA Crossovers** | MA20 / MA50 / MA200 with BTC price overlay |
| **Zone Days** | Days spent in each MVRV zone per cycle + avg BTC price per zone |
| **Peak Regression** | Log and linear regression of cycle peak MVRV with future projections |
| **Price Peaks** | BTC all-time high per cycle, MVRV divergence at price peak, lead/lag analysis |

---

## Export Summary

Click **↓ Export Summary** in the header to download a plain-text report with all key stats — current status, cycle summary, zone analysis, divergence, regression projections, and halving dates.

The file is designed to be pasted directly into any AI assistant (Claude, ChatGPT, etc.) for natural language analysis.

---

## Price Data — How It Works

BTC price data comes from the [Kaggle Bitcoin Historical Dataset](https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data/data) (Bitstamp 1-minute data, 2012–present), pre-processed into a daily-close JSON by a GitHub Actions workflow.

**The workflow:**
- Runs automatically every day at **06:00 UTC**
- Downloads the latest Kaggle CSV
- Extracts the last close price of each day
- Commits `btc_daily_price.json` to the repo
- The app fetches it on load — no action needed from you

To trigger a manual update: **Actions → Update Dashboard Data → Run workflow**

### First-time setup (for your own fork)
1. Get a Kaggle API key: kaggle.com → Account → API → Create New Token
2. Add two repository secrets (Settings → Secrets → Actions):
   - `KAGGLE_USERNAME` — your Kaggle username
   - `KAGGLE_KEY` — your Kaggle API key
3. Run the workflow once manually to generate the initial files
4. Enable GitHub Pages (Settings → Pages → Source: main branch, root)

---

## Architecture

| File | Purpose |
|---|---|
| `index.html` | Entire dashboard — single self-contained file |
| `generate_price_json.py` | Local script to generate `btc_daily_price.json` from Kaggle CSV |
| `.github/workflows/update_price_json.yml` | GitHub Actions workflow for daily price updates |
| `btc_daily_price.json` | Auto-generated daily BTC close prices (date → price) |
| `mvrv.json` | Your uploaded MVRV data (committed if you want to pin a version) |

---

## Cycle Reference

| Cycle | Period | Halving date |
|---|---|---|
| C1 | 2012–2016 | 2012-11-28 |
| C2 | 2016–2020 | 2016-07-09 |
| C3 | 2020–2024 | 2020-05-11 |
| C4 | 2024–2028 | 2024-04-20 |
| C5 | 2028– | 2028-03-26 (estimate) |

Cycle boundaries update automatically when new halving dates are added to the `HALVINGS` array in `index.html`.

---

## Notes

- All analysis is based on **Bitstamp** price data — minor differences from other exchanges are expected
- MVRV data from blockchain.com uses their own realized cap methodology; values may differ slightly from other providers
- The dashboard works fully offline after the initial price fetch — price overlays just won't update until reconnected
- Mobile supported; landscape orientation recommended for charts

---

## Data Sources

- **MVRV**: [blockchain.com/explorer/charts/mvrv](https://www.blockchain.com/explorer/charts/mvrv)
- **BTC Price**: [kaggle.com — Bitcoin Historical Data](https://www.kaggle.com/datasets/mczielinski/bitcoin-historical-data/data) via [mczielinski/kaggle-bitcoin](https://github.com/mczielinski/kaggle-bitcoin)
