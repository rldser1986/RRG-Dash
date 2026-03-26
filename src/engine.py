"""RRG Engine — yfinance data fetch + JdK-style normalization."""

import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)


SCALING_FACTOR = 1.5
RS_WINDOW = 14       # weeks for SMA / StdDev
MOMENTUM_WINDOW = 5  # weeks for RS-Momentum lookback
FETCH_YEARS = 2


def fetch_prices(tickers: list[str], benchmark: str = "SPY") -> pd.DataFrame:
    """Fetch daily Close prices and resample into rolling 5-day (synthetic weekly) candles.

    Instead of relying on calendar-week candles from yfinance (which only
    complete on Fridays), we fetch daily data and take every 5th trading day
    as a synthetic weekly close.  This means the most recent "week" always
    ends on the latest trading day, so the RRG updates daily rather than
    once per calendar week.
    """
    all_symbols = list(set([benchmark] + tickers))
    end = datetime.today()
    # Fetch enough daily data: ~5 trading days per week × (years + lookback buffer)
    start = end - timedelta(weeks=FETCH_YEARS * 52 + RS_WINDOW + MOMENTUM_WINDOW + 4)

    data = yf.download(all_symbols, start=start, end=end, interval="1d", auto_adjust=True)

    if data.empty:
        raise ValueError("yfinance returned no data")

    # yf.download returns MultiIndex columns (Price, Ticker) when multiple tickers
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].rename(columns={"Close": all_symbols[0]})

    prices = prices.dropna(how="all")

    # Resample: take every 5th trading day (anchored to the most recent day)
    # by reversing, slicing every 5th row, and reversing back.
    prices = prices.iloc[::-5][::-1]

    return prices


def compute_rrg(prices: pd.DataFrame, tickers: list[str],
                benchmark: str = "SPY", scaling_factor: float = SCALING_FACTOR) -> pd.DataFrame:
    """Compute RS, RS-Ratio, RS-Momentum, and quadrant for each ticker."""
    if benchmark not in prices.columns:
        raise ValueError(f"Benchmark '{benchmark}' not found in price data")

    results = []

    for ticker in tickers:
        if ticker not in prices.columns:
            logger.warning("%s not found in price data, skipping", ticker)
            continue
        if ticker == benchmark:
            continue

        pair = prices[[ticker, benchmark]].dropna()
        if len(pair) < RS_WINDOW + MOMENTUM_WINDOW:
            logger.warning("%s has insufficient data (%d rows), skipping", ticker, len(pair))
            continue

        # Step 1: Relative Strength
        rs = (pair[ticker] / pair[benchmark]) * 100

        # Step 2: RS-Ratio (z-score of RS over 14-week window)
        sma = rs.rolling(window=RS_WINDOW).mean()
        std = rs.rolling(window=RS_WINDOW).std()
        rs_ratio = 100 + ((rs - sma) / std) * scaling_factor

        # Step 3: RS-Momentum (change in RS-Ratio over 5 weeks)
        rs_momentum = 100 + (rs_ratio - rs_ratio.shift(MOMENTUM_WINDOW))

        # Build per-ticker dataframe
        df = pd.DataFrame({
            "date": pair.index,
            "ticker": ticker,
            "benchmark": benchmark,
            "rs": rs.values,
            "rs_ratio": rs_ratio.values,
            "rs_momentum": rs_momentum.values,
        })

        df = df.dropna(subset=["rs_ratio", "rs_momentum"])
        df["quadrant"] = df.apply(_assign_quadrant, axis=1)
        results.append(df)

    if not results:
        return pd.DataFrame()

    combined = pd.concat(results, ignore_index=True)
    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")
    return combined


def _assign_quadrant(row: pd.Series) -> str:
    """Assign RRG quadrant based on RS-Ratio and RS-Momentum."""
    ratio = row["rs_ratio"]
    momentum = row["rs_momentum"]

    if ratio >= 100 and momentum >= 100:
        return "Leading"
    elif ratio >= 100 and momentum < 100:
        return "Weakening"
    elif ratio < 100 and momentum < 100:
        return "Lagging"
    else:
        return "Improving"


def run(tickers: list[str], benchmark: str = "SPY",
        scaling_factor: float = SCALING_FACTOR) -> pd.DataFrame:
    """Full pipeline: fetch prices → compute RRG → return DataFrame."""
    logger.info("Fetching prices for %s vs %s", tickers, benchmark)
    prices = fetch_prices(tickers, benchmark)
    logger.info("Got %d weekly rows, computing RRG", len(prices))
    df = compute_rrg(prices, tickers, benchmark, scaling_factor)
    logger.info("Computed %d RRG data points", len(df))
    return df
