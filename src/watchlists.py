"""
Supabase-backed watchlist persistence for the RRG Dashboard.

Requires st.secrets["supabase"]["url"] and st.secrets["supabase"]["key"]
to be configured in .streamlit/secrets.toml (local) or Streamlit Cloud secrets.

Table schema (already created in Supabase):
    CREATE TABLE watchlists (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        tickers JSONB NOT NULL,
        benchmark TEXT NOT NULL DEFAULT 'SPY',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""

import logging
import re

import streamlit as st

logger = logging.getLogger(__name__)

MAX_WATCHLISTS = 20


# ── Supabase client (cached once per session) ────────────────────────────────

@st.cache_resource
def get_supabase_client():
    """Return a cached Supabase client, or None if secrets are missing."""
    try:
        from supabase import create_client

        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as exc:
        logger.warning("Supabase unavailable — watchlists disabled: %s", exc)
        return None


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def list_watchlists() -> list[dict]:
    """Return the most recent 20 watchlists, ordered newest-first."""
    client = get_supabase_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("watchlists")
            .select("id, name, tickers, benchmark, created_at")
            .order("created_at", desc=True)
            .limit(MAX_WATCHLISTS)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("Failed to list watchlists: %s", exc)
        return []


def save_watchlist(name: str, tickers: list[str], benchmark: str) -> dict | None:
    """Insert a new watchlist row. Enforces a FIFO cap of 20 rows."""
    client = get_supabase_client()
    if client is None:
        return None
    try:
        # Enforce FIFO cap: delete oldest if at the limit
        existing = (
            client.table("watchlists")
            .select("id, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        rows = existing.data or []
        if len(rows) >= MAX_WATCHLISTS:
            oldest_id = rows[-1]["id"]
            client.table("watchlists").delete().eq("id", oldest_id).execute()

        # Insert the new watchlist
        resp = (
            client.table("watchlists")
            .insert({
                "name": name,
                "tickers": tickers,
                "benchmark": benchmark,
            })
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("Failed to save watchlist: %s", exc)
        return None


def delete_watchlist(watchlist_id: int) -> bool:
    """Delete a single watchlist by ID. Returns True on success."""
    client = get_supabase_client()
    if client is None:
        return False
    try:
        client.table("watchlists").delete().eq("id", watchlist_id).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to delete watchlist %s: %s", watchlist_id, exc)
        return False


def get_next_default_name() -> str:
    """Return 'Watchlist N+1' based on the highest existing numbered name."""
    client = get_supabase_client()
    if client is None:
        return "Watchlist 1"
    try:
        resp = (
            client.table("watchlists")
            .select("name")
            .execute()
        )
        names = [row["name"] for row in (resp.data or [])]

        # Extract the highest N from names matching "Watchlist N"
        pattern = re.compile(r"^Watchlist\s+(\d+)$", re.IGNORECASE)
        max_num = 0
        for n in names:
            m = pattern.match(n)
            if m:
                max_num = max(max_num, int(m.group(1)))

        return f"Watchlist {max_num + 1}"
    except Exception as exc:
        logger.warning("Failed to query watchlist names: %s", exc)
        return "Watchlist 1"
