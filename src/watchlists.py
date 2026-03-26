"""
Supabase-backed watchlist persistence for the RRG Dashboard.

Requires st.secrets["supabase"]["url"] and st.secrets["supabase"]["key"]
to be configured in .streamlit/secrets.toml (local) or Streamlit Cloud secrets.

Table schema (v2 — requires migration, see SECURITY-AUDIT-2.md Finding #1):
    CREATE TABLE watchlists (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        tickers JSONB NOT NULL,
        benchmark TEXT NOT NULL DEFAULT 'SPY',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- RLS policy: users can only see/modify their own watchlists
    ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;
    CREATE POLICY "users_own_watchlists" ON watchlists
        FOR ALL USING (user_id = current_setting('request.headers', true)::json->>'x-user-id');
"""

import logging
import re
import uuid

import streamlit as st

logger = logging.getLogger(__name__)

MAX_WATCHLISTS = 20


# ── Anonymous user identity (stable per browser session) ─────────────────────

def _get_user_id() -> str:
    """Return a stable anonymous user ID for the current browser session.

    The ID is a UUID generated once per Streamlit session (i.e. per browser
    tab) and stored in session_state.  This scopes watchlists to the
    browser tab that created them, preventing cross-user access.
    """
    if "_anon_user_id" not in st.session_state:
        st.session_state["_anon_user_id"] = str(uuid.uuid4())
    return st.session_state["_anon_user_id"]


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
    """Return the current user's watchlists (up to MAX_WATCHLISTS), newest-first."""
    client = get_supabase_client()
    if client is None:
        return []
    user_id = _get_user_id()
    try:
        resp = (
            client.table("watchlists")
            .select("id, name, tickers, benchmark, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(MAX_WATCHLISTS)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("Failed to list watchlists: %s", exc)
        return []


MAX_NAME_LENGTH = 50


def _sanitize_name(name: str) -> str | None:
    """Sanitize a watchlist name. Returns None if invalid after cleaning."""
    name = re.sub(r"<[^>]+>", "", name)  # strip HTML tags
    name = name.strip()
    if not name:
        return None
    return name[:MAX_NAME_LENGTH]


def save_watchlist(name: str, tickers: list[str], benchmark: str) -> dict | None:
    """Insert a new watchlist row. Enforces a per-user FIFO cap.

    Inserts first, then trims overflow — so a failed insert never causes
    data loss (see SECURITY-AUDIT-2.md Finding #2).
    """
    name = _sanitize_name(name)
    if name is None:
        return None
    client = get_supabase_client()
    if client is None:
        return None
    user_id = _get_user_id()
    try:
        # Insert first (safe: if this fails, nothing is deleted)
        resp = (
            client.table("watchlists")
            .insert({
                "user_id": user_id,
                "name": name,
                "tickers": tickers,
                "benchmark": benchmark,
            })
            .execute()
        )
        data = resp.data or []
        if not data:
            return None

        # Trim overflow: delete oldest rows beyond the cap
        _trim_overflow(client, user_id)

        return data[0]
    except Exception as exc:
        logger.warning("Failed to save watchlist: %s", exc)
        return None


def _trim_overflow(client, user_id: str) -> None:
    """Delete the oldest watchlists for this user if they exceed MAX_WATCHLISTS."""
    try:
        existing = (
            client.table("watchlists")
            .select("id, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = existing.data or []
        if len(rows) > MAX_WATCHLISTS:
            overflow_ids = [r["id"] for r in rows[MAX_WATCHLISTS:]]
            for oid in overflow_ids:
                client.table("watchlists").delete().eq("id", oid).eq("user_id", user_id).execute()
    except Exception as exc:
        logger.warning("Failed to trim overflow watchlists: %s", exc)


def delete_watchlist(watchlist_id: str) -> bool:
    """Delete a single watchlist by ID, scoped to the current user.

    Both ID and user_id must match — prevents IDOR (see SECURITY-AUDIT-2.md Finding #1).
    """
    client = get_supabase_client()
    if client is None:
        return False
    user_id = _get_user_id()
    try:
        client.table("watchlists").delete().eq("id", watchlist_id).eq("user_id", user_id).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to delete watchlist %s: %s", watchlist_id, exc)
        return False


def get_next_default_name(watchlists: list[dict] | None = None) -> str:
    """Return 'Watchlist N+1' based on the highest existing numbered name.

    If *watchlists* is provided, derives the name from them without an
    extra Supabase round-trip (see SECURITY-AUDIT-2.md Finding #7).
    """
    if watchlists is None:
        watchlists = list_watchlists()

    pattern = re.compile(r"^Watchlist\s+(\d+)$", re.IGNORECASE)
    max_num = 0
    for wl in watchlists:
        m = pattern.match(wl.get("name", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))

    return f"Watchlist {max_num + 1}"
