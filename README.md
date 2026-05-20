# MVRV Analytics — BTC Dashboard

> Client-side Bitcoin cycle analysis tool. Drop a JSON file, get instant on-chain insights. No backend, no tracking, no BS.

🔗 **[Live Demo](https://0xtrvkc.github.io/dynamic-btc-analytics-dashboard/)**

---

## What it does

Upload your MVRV data exported from blockchain.com and the dashboard computes:

- **Z-Score** — rolling 365-day normalized MVRV with capitulation / caution thresholds
- **Cycle Overlay** — all four Bitcoin halving cycles overlaid on the same axis
- **Momentum** — 30-day vs 90-day rate-of-change signals
- **Drawdown & MA Crossovers** — peak drawdown tracking and moving average crossover signals
- **Projections** — four independent price target models (MVRV Upside, Halving Multiplier, ATH Multiplier, MVRV × Realized Cap) with IQR consensus
- **Backtest** — no-lookahead validation of every model across completed cycles, with error heatmap and per-model accuracy cards

---

## Architecture

| File | Role |
|---|---|
| `index.html` | Entire client app — parsing, state, charts |
| `btc_daily_price.json` | Daily BTC closes — auto-updated by CI |
| `generate_price_json.py` | Script run by GitHub Actions to refresh price data |
| `.github/workflows/` | Daily CRON pipeline config |

**Price data** is updated automatically every day via GitHub Actions — no manual intervention needed.  
**MVRV data** is loaded client-side from a JSON you export manually (stays in your browser, never uploaded anywhere).

---

## Usage

**Get your MVRV data:**

1. Go to [blockchain.com/explorer/charts/mvrv](https://www.blockchain.com/explorer/charts/mvrv)
2. Set timeframe to **ALL** → **Download JSON**

**Run the dashboard:**

1. Open the [live site](https://0xtrvkc.github.io/dynamic-btc-analytics-dashboard/) (or `index.html` locally)
2. Drop the downloaded JSON onto the upload zone
3. Explore the 12 analysis tabs

---

## Projection Models

| Model | Method |
|---|---|
| MVRV Upside | Price at MVRV peak × median remaining upside from prior cycles |
| Halving Multiplier | Price at halving × log-decay projected multiplier |
| ATH Multiplier | Previous ATH × log-decay ATH ratio |
| MVRV × Realized Cap | Cycle-start price ÷ MVRV × projected peak MVRV |
| **Consensus** | IQR-trimmed median of the four above |

Backtesting uses only data available *before* each cycle began — no lookahead bias.

---

## Stack

Vanilla JS · [Chart.js 4.4](https://www.chartjs.org/) · [98.css](https://jdan.github.io/98.css/) · GitHub Actions

---

## Config

```js
const CONFIG = {
  ZSCORE_WINDOW: 365,
  ZSCORE_CAPITULATION: -1.5,
  ZSCORE_CAUTION: 1.0,
  ROC_SHORT: 30,
  ROC_LONG: 90,
};
```

---

Not financial advice.
