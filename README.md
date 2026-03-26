# RRG Dashboard

An open-source, mobile-responsive Relative Rotation Graph (RRG) dashboard built with Python, Streamlit, Plotly, and SQLite.

Track market rotations across **Indices**, **Sectors**, and individual **Stocks** using public data from Yahoo Finance.

![RRG Dashboard Screenshot](screenshots/placeholder.png)

## Features

- **Three drill-down views:** Indices (SPY, QQQ, IWM, DIA), S&P Sector ETFs, and custom stock comparisons
- **Interactive RRG chart** with configurable tail lengths and quadrant coloring
- **Velocity Rankings table** sorting tickers by rotation speed toward the Leading quadrant
- **Lookback mode** to view historical RRG snapshots via a date slider
- **Compact Mode** for mobile-friendly layout
- **Dark theme** out of the box
- **SQLite persistence** for historical data without recomputation

## Quadrants

| Quadrant   | Condition                             | Color  |
|------------|---------------------------------------|--------|
| Leading    | RS-Ratio > 100 AND RS-Momentum > 100 | Green  |
| Weakening  | RS-Ratio > 100 AND RS-Momentum < 100 | Orange |
| Lagging    | RS-Ratio < 100 AND RS-Momentum < 100 | Red    |
| Improving  | RS-Ratio < 100 AND RS-Momentum > 100 | Blue   |

## Setup

### Prerequisites

- Python 3.10+

### Install

```bash
git clone https://github.com/YOUR_USERNAME/RRG-Dash.git
cd RRG-Dash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Secrets (optional)

Watchlists and the ticker registry use Supabase for persistence. Create `.streamlit/secrets.toml` with:

```toml
[supabase]
url = "https://YOUR_PROJECT.supabase.co"
key = "your-anon-key"             # public / anon key (read access)
service_key = "your-service-key"  # optional — enables ticker registry writes
```

The app works without Supabase — watchlists will be disabled and the ticker search falls back to the local CSV in `data/sp500_tickers.csv`.

### Run

```bash
streamlit run app.py
```

The database (`data/rrg.db`) is auto-created on first run.

## Deployment (Streamlit Community Cloud)

1. Push the repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account.
3. Select the repo, branch `main`, and main file `app.py`.
4. Click **Deploy**. The app will install dependencies from `requirements.txt` and `packages.txt` automatically.
5. In the app's **Settings → Secrets**, add the `[supabase]` keys listed above.

## Project Structure

```
RRG-Dash/
├── app.py                 # Streamlit entry point
├── src/
│   ├── engine.py          # yfinance data fetch + JdK normalization
│   ├── db.py              # SQLite wrapper
│   ├── ticker_registry.py # Supabase-backed ticker lookup + yfinance validation
│   ├── watchlists.py      # Supabase-backed watchlist persistence
│   └── main.py            # CLI runner for testing
├── data/                  # SQLite database (auto-created, gitignored)
├── .streamlit/
│   └── config.toml        # Dark theme config
├── requirements.txt
├── packages.txt           # System-level deps for Streamlit Cloud
└── CLAUDE.md              # AI development spec
```

## License

MIT
