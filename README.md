# Dynamic BTC Analytics Dashboard

A responsive, client-side Bitcoin tracking workspace explicitly optimized for identifying cyclical asset macro extensions via the **MVRV Ratio** (Market Value to Realized Value) and Rolling Volatility Distributions.

Live Deployment: **https://0xtrvkc.github.io/dynamic-btc-analytics-dashboard/**

---

## Architectural Layout Data Streams

This platform uses a decoupled file architecture to process on-chain models securely with zero tracking overhead:
1. **Automated Price Database Updates (Daily CRON Pipeline)**: A GitHub Actions workflow runs systematically daily to grab standard closing data vectors using `generate_price_json.py`. This automatically refreshes and commits updates directly into `btc_daily_price.json`.
2. **On-Chain Metric Parsing (Manual Client Import)**: MVRV matrix data points are handled on-demand locally in browser memory. Uploaded files stay isolated within the application run cycle context.

---

## Operational Guide

### 1. Extract Target Data Model
Navigate to the public charting directory at [blockchain.com/explorer/charts/mvrv](https://www.blockchain.com/explorer/charts/mvrv). Set your tracking boundary configuration to **ALL**, and select **Download JSON** from the sub-menu tracking bar.

### 2. Upload and Run Dashboard
Open your local deployment url or your production GitHub Pages endpoint. Drop your file asset inside the configuration window to parse elements automatically.

---

## Repository Cleanliness Manifest

| File System Target | Operational Focus Status |
| :--- | :--- |
| `index.html` | Client Interface. Handles context loops, memory lifecycle mapping, and chart creation. |
| `generate_price_json.py` | Executed via GitHub runner to build current day indexes. |
| `btc_daily_price.json` | Parsed array matrix tracking closing valuations over time. |
| `.github/workflows/` | GitHub Action configuration files controlling pipeline automation properties. |
