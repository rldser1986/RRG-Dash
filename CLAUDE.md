# RRG Dashboard — Project Spec for Claude Code

## Project Overview

Open-source, mobile-responsive Relative Rotation Graph (RRG) dashboard built with Python, Streamlit, Plotly, and SQLite. Tracks market rotations across Indices, Sectors, and individual Stocks using public data from yfinance.

---

## Technical Stack

- **Language:** Python 3.10+
- **Data Source:** `yfinance` (weekly interval to minimize noise)
- **Math Engine:** Pandas & NumPy for JdK-style normalization
- **Database:** SQLite (persistent local storage for all computed RRG values — enables historical lookback without recomputation)
- **Frontend:** Streamlit with Plotly for interactive charts
- **Charting:** Plotly Express / Graph Objects (scatter with tails)

---

## Project Structure

```
RRG-Dash/
├── CLAUDE.md              # This file (read by Claude Code at session start)
├── requirements.txt       # yfinance, pandas, numpy, streamlit, plotly
├── app.py                 # Streamlit entry point
├── src/
│   ├── engine.py          # yfinance data fetch + JdK math
│   ├── db.py              # SQLite wrapper (save, query, lookback)
│   └── main.py            # CLI runner: fetch → compute → store → print
├── data/
│   └── rrg.db             # SQLite database (auto-created, gitignored)
└── .streamlit/
    └── config.toml        # Streamlit Cloud config (Sprint 4)
```

---

## Mathematical Core (The Engine)

All values are centered at (100, 100) using Z-Score normalization.

### Step 1: Relative Strength (RS)

```
RS = (Price_Stock / Price_Benchmark) × 100
```

### Step 2: RS-Ratio (The Trend)

Measures whether RS is in an uptrend or downtrend relative to its own 14-week history.

```
RS-Ratio = 100 + ((RS - SMA_14(RS)) / StdDev_14(RS)) × SCALING_FACTOR
```

- `SMA_14` = 14-week Simple Moving Average of RS
- `StdDev_14` = 14-week Standard Deviation of RS
- `SCALING_FACTOR` = configurable parameter, default `1.5` (controls visual spread on the graph; tune after seeing the plot)

### Step 3: RS-Momentum (The Velocity)

Measures the rate of change of RS-Ratio over a 5-week window.

```
RS-Momentum = 100 + (RS-Ratio_current - RS-Ratio_5_weeks_ago)
```

### Quadrant Logic

| Quadrant    | Condition                              | Color  |
|-------------|----------------------------------------|--------|
| Leading     | RS-Ratio > 100 AND RS-Momentum > 100  | Green  |
| Weakening   | RS-Ratio > 100 AND RS-Momentum < 100  | Orange |
| Lagging     | RS-Ratio < 100 AND RS-Momentum < 100  | Red    |
| Improving   | RS-Ratio < 100 AND RS-Momentum > 100  | Blue   |

---

## SQLite Schema (db.py)

Single table, indexed on date for fast lookback queries.

```sql
CREATE TABLE IF NOT EXISTS rrg_data (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    rs REAL,
    rs_ratio REAL,
    rs_momentum REAL,
    quadrant TEXT,
    PRIMARY KEY (date, ticker, benchmark)
);

CREATE INDEX IF NOT EXISTS idx_date ON rrg_data(date);
```

### Required Functions in db.py

- `save_results(df)` — Upsert computed RRG DataFrame into SQLite
- `get_latest(benchmark)` — Return most recent date's data for all tickers
- `get_by_date(date, benchmark)` — Return data for a specific date (lookback)
- `get_tail(ticker, benchmark, n_weeks)` — Return last N weeks for drawing tails

---

## UI/UX Architecture

### Drill-Down Philosophy

- **View 1 — Macro (Indices):** Compare SPY, QQQ, IWM, DIA against each other (benchmark: SPY)
- **View 2 — Sector (XL-Series):** Compare the 11 S&P sector ETFs against SPY
  - XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY
- **View 3 — Micro (Individual):** Compare stocks within a sector (e.g., NVDA, AAPL, MSFT vs XLK)

### Key UI Components

1. **Hero Plot:** Plotly scatter with quadrant background colors and 5–10 week tails (trails showing movement path)
2. **Velocity Sort Table:** Sortable table ranking tickers by speed of movement toward the Leading quadrant — identifies "Rotators" entering uptrends
3. **Lookback Slider:** Date slider that queries SQLite `get_by_date()` to show the RRG at any historical point
4. **Sidebar:** View selector (Indices / Sectors / Individual) + ticker input for custom comparisons
5. **Mobile Layout:** Vertical-stacked layout using `st.columns` with conditional stacking; compact mode toggle

---

## Ticker Lists

```python
INDICES = ['SPY', 'QQQ', 'IWM', 'DIA']

SECTORS = {
    'XLB': 'Materials', 'XLC': 'Communication', 'XLE': 'Energy',
    'XLF': 'Financials', 'XLI': 'Industrials', 'XLK': 'Technology',
    'XLP': 'Consumer Staples', 'XLRE': 'Real Estate', 'XLU': 'Utilities',
    'XLV': 'Health Care', 'XLY': 'Consumer Discretionary'
}
```

---

## Implementation Roadmap

### Sprint 0: Project Scaffold

Set up the project structure, install dependencies, create this CLAUDE.md.

**Prompt:**
```
Read the CLAUDE.md file. Set up the project structure as specified: create requirements.txt with (yfinance, pandas, numpy, streamlit, plotly), create the src/ and data/ directories, and create empty placeholder files for app.py, src/engine.py, src/db.py, and src/main.py. Add data/ to .gitignore. Confirm the structure.
```

---

### Sprint 1: The Engine + Storage

Build the data pipeline: fetch → compute → store.

**Prompt:**
```
Begin Sprint 1 from CLAUDE.md. Create two modules:

1. `src/engine.py`:
   - Use yfinance to fetch 2 years of weekly Adj Close data for a list of tickers and a benchmark (default: SPY).
   - Implement JdK-style normalization:
     - RS = (Stock Price / Benchmark Price) × 100
     - RS-Ratio = 100 + ((RS - SMA_14(RS)) / StdDev_14(RS)) × SCALING_FACTOR
     - RS-Momentum = 100 + (RS-Ratio_current - RS-Ratio_5_weeks_ago)
   - Make SCALING_FACTOR configurable (default 1.5).
   - Handle missing data or tickers that haven't traded for the full 2 years.
   - Assign quadrant labels (Leading, Weakening, Lagging, Improving) based on the logic in CLAUDE.md.

2. `src/db.py`:
   - SQLite wrapper using the schema in CLAUDE.md (table: rrg_data, indexed on date).
   - Functions: save_results(df), get_latest(benchmark), get_by_date(date, benchmark), get_tail(ticker, benchmark, n_weeks).
   - Database file at data/rrg.db.

3. `src/main.py`:
   - Runs engine for ['AAPL', 'NVDA', 'MSFT', 'GOOGL'] vs SPY.
   - Saves results to SQLite.
   - Prints a summary table of the latest RS-Ratio, RS-Momentum, and Quadrant for verification.

Run main.py and show me the output.
```

---

### Sprint 2: The Dashboard

Build the Streamlit UI reading from SQLite.

**Prompt:**
```
Begin Sprint 2 from CLAUDE.md. Build app.py using Streamlit and Plotly:

1. Sidebar with View selector (Indices / Sectors / Individual) using the ticker lists from CLAUDE.md.
2. When a view is selected, run the engine for those tickers, save to SQLite, then load from SQLite for display.
3. Hero Plot: Plotly scatter plot with:
   - Quadrant background colors (Leading=green, Weakening=orange, Lagging=red, Improving=blue) with low opacity.
   - Crosshairs at (100, 100).
   - Ticker labels on each point.
   - 5-week tails using get_tail() — draw lines connecting historical positions.
4. Use st.cache_data on the data fetch/compute step to avoid redundant yfinance calls.
5. Add a Lookback slider that uses get_by_date() to show the RRG at a historical date.
6. Make it runnable with: streamlit run app.py
```

---

### Sprint 3: Velocity Table + Polish

Add the analytical table and mobile optimization.

**Prompt:**
```
Begin Sprint 3 from CLAUDE.md. Add:

1. Velocity Sort Table below the Hero Plot:
   - Calculate velocity as the Euclidean distance moved toward (Leading quadrant) over the last 5 weeks.
   - Rank tickers by velocity descending — highest = fastest rotator.
   - Show columns: Ticker, RS-Ratio, RS-Momentum, Quadrant, Velocity, Direction (toward Leading / away from Leading).
   - Highlight rows where Direction = "toward Leading" in green.

2. Mobile Layout:
   - Detect viewport width using st.columns conditional stacking.
   - Add a "Compact Mode" toggle in the sidebar.
   - In compact mode: stack chart and table vertically, reduce chart height, increase font sizes.

3. Individual View Enhancement:
   - In the "Individual" view, add a text input for custom tickers (comma-separated).
   - Add a benchmark selector dropdown (default: sector ETF, option: SPY).

Test on desktop. Confirm the table sorts correctly.
```

---

### Sprint 4: Deployment

Prepare for Streamlit Community Cloud.

**Prompt:**
```
Begin Sprint 4 from CLAUDE.md. Prepare for Streamlit Community Cloud deployment:

1. Create .streamlit/config.toml with a clean dark theme.
2. Create packages.txt if any system-level dependencies are needed.
3. Ensure data/rrg.db is auto-created on first run (not shipped with the repo).
4. Add a "Last Updated" timestamp to the sidebar showing when data was last fetched.
5. Add a manual "Refresh Data" button that clears cache and re-fetches from yfinance.
6. Verify the app runs cleanly with: streamlit run app.py
7. Create a README.md with setup instructions, screenshots placeholder, and deployment steps.
```

---

## Design Decisions Log

| Decision | Rationale |
|----------|-----------|
| SQLite over Parquet | Single indexed query for lookback vs. loading entire file; scales better on constrained Streamlit Cloud memory |
| Plotly over Matplotlib | Interactive hover, zoom, and tail animation support |
| Configurable scaling factor | JdK uses proprietary smoothing; fixed 1.5 will need visual tuning |
| Weekly data interval | Minimizes noise vs. daily; standard for RRG analysis |
| yfinance Adj Close | Accounts for splits/dividends automatically |
| st.cache_data | Prevents redundant API calls within a session |
