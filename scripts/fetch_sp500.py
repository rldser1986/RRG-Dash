"""
Fetch S&P 500 constituents from Wikipedia and save to data/sp500_tickers.csv.

Usage:
    python scripts/fetch_sp500.py

Output columns: Symbol, Company, GICS Sector, GICS Sub-Industry
Benchmark ETFs are prepended at the top of the file.
"""

import os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "sp500_tickers.csv")

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

BENCHMARKS = [
    ("SPY", "SPDR S&P 500 ETF", "Benchmark", "S&P 500"),
    ("QQQ", "Invesco QQQ Trust", "Benchmark", "Nasdaq-100"),
    ("IWM", "iShares Russell 2000 ETF", "Benchmark", "Russell 2000"),
    ("RSP", "Invesco S&P 500 Equal Weight ETF", "Benchmark", "Equal-Weight S&P 500"),
    ("VTV", "Vanguard Value ETF", "Benchmark", "Value Stocks"),
    ("VUG", "Vanguard Growth ETF", "Benchmark", "Growth Stocks"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", "Benchmark", "Dow 30"),
    ("EFA", "iShares MSCI EAFE ETF", "Benchmark", "International Developed"),
    ("EEM", "iShares MSCI Emerging Markets ETF", "Benchmark", "Emerging Markets"),
]

COLUMNS = ["Symbol", "Company", "GICS Sector", "GICS Sub-Industry"]


def fetch_sp500() -> pd.DataFrame:
    """Scrape the S&P 500 table from Wikipedia and return a clean DataFrame."""
    tables = pd.read_html(WIKI_URL)
    df = tables[0][["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"]].copy()
    df.columns = COLUMNS
    df["Symbol"] = df["Symbol"].str.strip()
    df = df.sort_values("Symbol").reset_index(drop=True)
    return df


def build_csv() -> str:
    """Fetch S&P 500 data, prepend benchmarks, and write to CSV. Returns output path."""
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    bench_df = pd.DataFrame(BENCHMARKS, columns=COLUMNS)
    sp500_df = fetch_sp500()
    final = pd.concat([bench_df, sp500_df], ignore_index=True)
    final.to_csv(OUTPUT_PATH, index=False)

    print(f"Wrote {len(final)} rows to {OUTPUT_PATH}")
    print(f"  {len(bench_df)} benchmarks + {len(sp500_df)} S&P 500 components")
    return OUTPUT_PATH


if __name__ == "__main__":
    build_csv()
