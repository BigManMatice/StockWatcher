# 📈 StonksBot - Discord Investment Portfolio & Watchlist Tracker

A Discord bot built in Python to track personal stock and ETF portfolios and monitor watchlists with Euro (EUR) pricing that aligns directly with European brokerage apps like **Trade Republic**.

---

## 🚀 Features

- **Euro-Native Accuracy:** Uses native European exchange listings (`.DE`, `.AS`, `.LS`) via `yfinance` to eliminate USD-to-EUR exchange rate distortions and reflect true local exchange performance.
- **Decoupled Ticker Aliasing (`stockName.py`):** Accepts standard user inputs (`AAPL`, `MICROSOFT`, `NVIDIA`, `S&P500`) and silently maps them to underlying European API tickers (`APC.DE`, `MSF.DE`, `NVD.DE`, `SXR8.DE`).
- **Clean Discord Display Labels:** Formats holdings in Discord embeds as `NAME (API_TICKER)` (e.g., `AAPL (APC.DE)`, `S&P500 (SXR8.DE)`).
- **SQLite Snapshot Caching:** Caches daily close prices and FX rates locally in `bot_database.db` to prevent rate-limiting and paywall issues.
- **Multi-Provider Fallback:** Robust data fetching pipeline (`yfinance` → Finnhub → FMP) ensuring high availability for global and European assets.
- **Portfolio & Watchlist Tracking:** Live calculation of profit/loss in Euros, cost basis, current market value, and percentage gain.

---

## 🏗️ How It Works (Architecture)

### 1. Data & Aliasing Flow
When a user runs a command like `!add AAPL 75 309.12` or views `!portfolio`:


```

User Input ("AAPL")
│
▼
[ stockName.py ] ──► Maps "AAPL" to "APC.DE" for API queries
│          ──► Maps "APC.DE" to "AAPL (APC.DE)" for Discord display
▼
[ data.py ]   ──► Queries yfinance for "APC.DE" (EUR quote)
│          ──► Falls back to Finnhub / FMP if necessary
▼
[ SQLite DB ]  ──► Caches close snapshot in bot_database.db
│
▼
[ bot.py ]    ──► Renders formatted Discord Embed

```

### 2. File Overview

- **`bot.py`**: Discord bot command handlers (`!portfolio`, `!watchlist`, `!add`, `!remove`). Handles embed styling and passes tickers through `stockName.py` for formatting.
- **`data.py`**: Core data engine. Handles SQLite connections, FX rate caching, multi-provider quote fetching, and historical price queries.
- **`stockName.py`**: Ticker mapping module containing `API_RENAMES` (for backend queries) and `DISPLAY_NAMES` (for Discord labels).
- **`config.py`**: Stores environment variables, API keys (Finnhub, FMP), and Discord bot tokens.
- **`bot_database.db`**: Local SQLite database storing price snapshots and exchange rates.

---

## 🗄️ Database Schema (`bot_database.db`)

### `prices` Table
Stores daily historical closing prices for assets.
```sql
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT,
    date TEXT,
    close REAL,
    PRIMARY KEY (ticker, date)
);

```

### `fx` Table

Caches daily foreign exchange rates (USD/EUR).

```sql
CREATE TABLE IF NOT EXISTS fx (
    pair TEXT PRIMARY KEY,
    rate REAL NOT NULL,
    fetched_on TEXT NOT NULL
);

```

---

## 🛠️ Setup & Installation

### 1. Prerequisites

* Python 3.10+
* Discord Developer Bot Token

### 2. Install Dependencies

```bash
pip install discord.py pandas requests yfinance

```

### 3. Project Configuration (`config.py`)

Ensure your `config.py` contains valid API keys and bot credentials:

```python
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
FINNHUB_KEY = "YOUR_FINNHUB_API_KEY"
FMP_KEY = "YOUR_FMP_API_KEY"

```

### 4. Run the Bot

```bash
python main.py

```

---

## 💻 Discord Commands

| Command | Usage Example | Description |
| --- | --- | --- |
| `!portfolio` | `!portfolio` | Displays current holdings, current EUR value, and total profit/loss. |
| `!watchlist` | `!watchlist` | Displays tracked assets with clean display labels. |
| `!add` | `!add AAPL 75 309.12` | Adds a position (ticker, total EUR paid, buy price/share). |
| `!remove` | `!remove AAPL` | Removes a position from your portfolio. |

---

## ⚙️ Maintenance SQL Queries

To manually clear today's cached price snapshot from SQLite:

```sql
DELETE FROM prices WHERE date = CURRENT_DATE;

```

```

<FollowUp label="Want to set up the background task in bot.py to monitor watchlist price spikes next?" query="Set up the background task in bot.py to monitor watchlist price spikes and send Discord alerts."/>