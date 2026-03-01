"""RRG CLI Runner — fetch → compute → store → print."""

import sys
import os

# Allow running from project root: python src/main.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engine import run
from src.db import save_results, get_latest


TICKERS = ["AAPL", "NVDA", "MSFT", "GOOGL"]
BENCHMARK = "SPY"


def main():
    # 1. Fetch + compute
    df = run(TICKERS, BENCHMARK)

    if df.empty:
        print("No data computed. Check ticker symbols and network connection.")
        return

    # 2. Save to SQLite
    n = save_results(df)
    print(f"Saved {n} rows to SQLite\n")

    # 3. Print latest summary
    latest = get_latest(BENCHMARK)
    if latest.empty:
        print("No data found in database.")
        return

    print(f"=== Latest RRG Summary ({latest['date'].iloc[0]}) ===")
    print(f"{'Ticker':<8} {'RS-Ratio':>10} {'RS-Momentum':>13} {'Quadrant':<12}")
    print("-" * 45)
    for _, row in latest.iterrows():
        print(f"{row['ticker']:<8} {row['rs_ratio']:>10.2f} {row['rs_momentum']:>13.2f} {row['quadrant']:<12}")


if __name__ == "__main__":
    main()
