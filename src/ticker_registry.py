"""
Supabase-backed ticker registry for the RRG Dashboard.

Provides a persistent, growing list of ticker symbols with company names,
sectors, and industries. Unknown tickers are validated via yfinance and
appended to the registry automatically.

Supabase table schema:
    CREATE TABLE tickers (
        symbol TEXT PRIMARY KEY,
        company TEXT NOT NULL DEFAULT '',
        sector TEXT NOT NULL DEFAULT '',
        industry TEXT NOT NULL DEFAULT ''
    );
"""

import logging
from typing import Optional

import streamlit as st

logger = logging.getLogger(__name__)


# ── Supabase clients ────────────────────────────────────────────────────────

def _get_client():
    """Return the cached anon Supabase client (read-only), or None."""
    try:
        from src.watchlists import get_supabase_client
        return get_supabase_client()
    except Exception:
        return None


@st.cache_resource
def _get_service_client():
    """Return a Supabase client using the service_role key (for writes).
    Falls back to the anon client if service_key is not configured.
    """
    try:
        from supabase import create_client

        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"].get("service_key", "")
        if not key:
            logger.warning("service_key not configured — ticker writes will use anon client (may fail under RLS)")
            return _get_client()
        return create_client(url, key)
    except Exception as exc:
        logger.warning("Service client unavailable, falling back to anon: %s", exc)
        return _get_client()


# ── Read ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_all_tickers() -> list[dict]:
    """Load all tickers from Supabase. Returns list of dicts with
    keys: symbol, company, sector, industry.
    Cached for 5 minutes to avoid hammering Supabase on every rerun.
    """
    client = _get_client()
    if client is None:
        return _fallback_csv()
    try:
        resp = (
            client.table("tickers")
            .select("symbol, company, sector, industry")
            .order("symbol")
            .execute()
        )
        data = resp.data or []
        if not data:
            # Table exists but is empty — fall back to CSV
            return _fallback_csv()
        return data
    except Exception as exc:
        logger.warning("Failed to load tickers from Supabase: %s", exc)
        return _fallback_csv()


def _fallback_csv() -> list[dict]:
    """Fallback: load from local CSV if Supabase is unavailable."""
    import os
    import pandas as pd

    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "sp500_tickers.csv")
    if not os.path.exists(csv_path):
        return []
    df = pd.read_csv(csv_path)
    return [
        {
            "symbol": row.get("Symbol", ""),
            "company": row.get("Company", ""),
            "sector": row.get("GICS Sector", ""),
            "industry": row.get("GICS Sub-Industry", ""),
        }
        for _, row in df.iterrows()
    ]


def get_ticker_options() -> list[str]:
    """Return formatted options for the multiselect: 'TICKER — Company'."""
    tickers = load_all_tickers()
    return [
        f"{t['symbol']} — {t['company']}" if t.get("company") else t["symbol"]
        for t in tickers
    ]


def get_ticker_df():
    """Return tickers as a DataFrame (for Browse by Sector)."""
    import pandas as pd

    tickers = load_all_tickers()
    if not tickers:
        return pd.DataFrame()
    df = pd.DataFrame(tickers)
    # Rename columns to match what app.py expects
    df = df.rename(columns={
        "symbol": "Symbol",
        "company": "Company",
        "sector": "GICS Sector",
        "industry": "GICS Sub-Industry",
    })
    return df


# ── Validate & Register ────────────────────────────────────────────────────

def validate_and_register(symbol: str) -> Optional[dict]:
    """Look up a ticker via yfinance. If valid, add it to Supabase and return
    the ticker dict. If invalid, return None.

    This is called when a user enters a ticker not found in the registry.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None

    # First check if it's already in the registry (avoid duplicate API calls)
    client = _get_client()
    if client is not None:
        try:
            resp = (
                client.table("tickers")
                .select("symbol, company, sector, industry")
                .eq("symbol", symbol)
                .execute()
            )
            if resp.data:
                return resp.data[0]
        except Exception:
            pass

    # Not in registry — validate via yfinance
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info
        # yfinance returns a dict even for invalid tickers, but key fields
        # will be missing or the dict will be nearly empty.
        name = info.get("shortName") or info.get("longName") or ""
        # If there's no name and no market cap, it's likely invalid
        if not name and not info.get("marketCap"):
            return None

        sector = info.get("sector", "")
        industry = info.get("industry", "")

        ticker_data = {
            "symbol": symbol,
            "company": name,
            "sector": sector,
            "industry": industry,
        }

        # Write to Supabase (using service client for write access)
        writer = _get_service_client()
        if writer is not None:
            try:
                writer.table("tickers").upsert(ticker_data).execute()
                # Clear the cache so the new ticker appears immediately
                load_all_tickers.clear()
            except Exception as exc:
                logger.warning("Failed to register ticker %s: %s", symbol, exc)

        return ticker_data

    except Exception as exc:
        logger.warning("yfinance validation failed for %s: %s", symbol, exc)
        return None


def validate_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Validate a list of symbols against the registry + yfinance.

    Returns (valid_symbols, invalid_symbols).
    Valid symbols are also registered in Supabase if they were unknown.
    """
    all_tickers = {t["symbol"] for t in load_all_tickers()}
    valid = []
    invalid = []

    for sym in symbols:
        sym = sym.strip().upper()
        if not sym:
            continue
        if sym in all_tickers:
            valid.append(sym)
        else:
            result = validate_and_register(sym)
            if result:
                valid.append(sym)
                all_tickers.add(sym)  # Update local set
            else:
                invalid.append(sym)

    return valid, invalid


# ── Seed helper ─────────────────────────────────────────────────────────────

def seed_from_csv() -> int:
    """Bulk-insert tickers from sp500_tickers.csv into Supabase.
    Skips existing rows (upsert). Returns count of rows written.
    Uses the service_role client for write access.
    """
    client = _get_service_client()
    if client is None:
        raise RuntimeError("Supabase service client not available")

    rows = _fallback_csv()
    if not rows:
        raise RuntimeError("No CSV data to seed")

    # Upsert in batches of 100
    count = 0
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            client.table("tickers").upsert(batch).execute()
            count += len(batch)
        except Exception as exc:
            logger.warning("Seed batch %d failed: %s", i, exc)

    # Clear cache
    load_all_tickers.clear()
    return count
