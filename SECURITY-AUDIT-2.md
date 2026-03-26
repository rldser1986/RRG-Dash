# RRG Dashboard — Security & Code Quality Audit (Pass 2)

**Date:** 2026-03-25
**Scope:** Full codebase second-pass audit. Assumes all 9 fixes from Pass 1 are applied.
**Files audited:** app.py, src/watchlists.py, src/ticker_registry.py, src/engine.py, src/db.py, src/main.py, scripts/fetch_sp500.py, scripts/seed_tickers.py, requirements.txt, .gitignore, .streamlit/

---

## Finding 1 — IDOR: Any Client Can Delete Any Watchlist

**Severity: HIGH | Confidence: HIGH**

`delete_watchlist()` accepts an integer ID and issues `.delete().eq("id", watchlist_id)` with no ownership check. The watchlists table uses sequential integer primary keys (`SERIAL`), making IDs trivially guessable. Combined with the anon key being available server-side (and extractable from network traffic on Streamlit Cloud), an attacker can enumerate and mass-delete every watchlist by iterating IDs 1..N directly against the Supabase REST API.

`list_watchlists()` also returns ALL watchlists globally (not scoped to a user), enabling full enumeration of names, tickers, and benchmarks.

**Root cause:** No `user_id` column, no RLS policy scoping rows to the authenticated user.

**Prompt:**
```
Harden the watchlists table against IDOR attacks:

1. Add a `user_id` column to the watchlists table (TEXT, nullable for now).
2. Generate a stable anonymous user ID per browser session (hash of a random UUID stored
   in st.session_state, persisted via a cookie or local-storage workaround). Store it on
   every insert.
3. In list_watchlists() and delete_watchlist(), filter by user_id so users only see/delete
   their own rows.
4. Add a Supabase RLS policy:
     CREATE POLICY "users_own_watchlists" ON watchlists
       USING (user_id = current_setting('request.headers')::json->>'x-user-id')
       WITH CHECK (user_id = current_setting('request.headers')::json->>'x-user-id');
   (Or use Supabase Auth if/when real auth is added.)
5. As an immediate stopgap before full auth: switch from SERIAL to UUID primary keys
   (gen_random_uuid()) so IDs are not guessable.
```

---

## Finding 2 — FIFO Cap Race Condition: Delete Without Insert Atomicity

**Severity: HIGH | Confidence: HIGH**

In `save_watchlist()` (watchlists.py L84-111), the FIFO cap logic runs two separate operations: (1) delete the oldest row, (2) insert the new row. These are not wrapped in a transaction. If the insert fails after the delete succeeds, the user permanently loses a watchlist with nothing to show for it. Additionally, two concurrent saves can both delete the same oldest row, then both insert — exceeding the 20-row cap.

**Prompt:**
```
Fix the FIFO cap atomicity in save_watchlist():

1. Reverse the operation order: INSERT first, THEN delete overflow rows. This way a failed
   insert doesn't cause data loss.
2. After insert, query the count, and if > MAX_WATCHLISTS, delete the oldest
   (len - MAX_WATCHLISTS) rows in a single DELETE ... WHERE id IN (SELECT id ... ORDER BY
   created_at ASC LIMIT N).
3. Wrap both operations in a Supabase RPC function (a PostgreSQL stored procedure) to get
   true atomicity, or at minimum add error handling that skips the delete if the insert
   failed:

   try:
       resp = client.table("watchlists").insert({...}).execute()
       if not resp.data:
           return None
       # Only NOW trim overflow
       _trim_overflow(client)
       return resp.data[0]
   except Exception as exc:
       logger.warning("Save failed: %s", exc)
       return None
```

---

## Finding 3 — Stored XSS Vector via yfinance shortName → unsafe_allow_html

**Severity: MEDIUM | Confidence: MID**

`validate_and_register()` stores `info.get("shortName")` from yfinance directly into the Supabase `tickers` table as `company`. This value is never HTML-escaped. While Streamlit's `multiselect` widget escapes labels, the quadrant summary cards (app.py L467-473) use `st.markdown(..., unsafe_allow_html=True)`. Currently, only ticker *symbols* (not company names) flow into those HTML strings, but any future change that adds company names to the cards would create a stored XSS path. The ticker symbols themselves come from DataFrame columns and are not explicitly escaped before HTML injection.

If Yahoo Finance were compromised or returned a crafted `shortName` like `<img src=x onerror=alert(1)>`, it would be stored and could render in any future `unsafe_allow_html` context.

**Prompt:**
```
Mitigate the stored XSS vector:

1. In ticker_registry.py validate_and_register(), sanitize the company name the same way
   watchlist names are sanitized — strip HTML tags and limit length:

   from src.watchlists import _sanitize_name
   name = _sanitize_name(name) or symbol  # fall back to symbol if name is empty/malicious

2. In app.py, HTML-escape any dynamic content before inserting into unsafe_allow_html
   strings. Add a helper:

   from html import escape as html_escape

   Then in the quadrant summary cards (L466):
   _ticker_str = html_escape(", ".join(sorted(_tickers))) if _tickers else "—"

3. Add a symbol format validation regex in validate_and_register():
   if not re.match(r'^[A-Z0-9.^=-]{1,12}$', symbol):
       return None
   This prevents garbage/adversarial strings from reaching yfinance or Supabase.
```

---

## Finding 4 — No Rate Limiting on yfinance Validation

**Severity: MEDIUM | Confidence: HIGH**

Any user can trigger unlimited `yf.Ticker(symbol).info` calls by entering arbitrary symbols in the Individual view text input or by loading a watchlist with unknown tickers. Each unknown symbol triggers a synchronous HTTP call to Yahoo Finance. An attacker (or an innocent user pasting a long list) could flood Yahoo's API, getting the deployment IP rate-limited or banned. This also creates a DoS vector against the Streamlit app itself since `yf.Ticker().info` blocks the event loop.

**Prompt:**
```
Add rate limiting and input caps to yfinance validation:

1. In validate_symbols(), cap the number of unknown symbols validated per call:
   MAX_UNKNOWN_VALIDATIONS = 5
   unknown = unknown[:MAX_UNKNOWN_VALIDATIONS]
   if len(original_unknown) > MAX_UNKNOWN_VALIDATIONS:
       invalid.extend(original_unknown[MAX_UNKNOWN_VALIDATIONS:])
       st.warning(f"Too many unknown tickers — only validating first {MAX_UNKNOWN_VALIDATIONS}")

2. Add a session-level rate limit using st.session_state:
   if "_yf_calls_this_session" not in st.session_state:
       st.session_state["_yf_calls_this_session"] = 0
   if st.session_state["_yf_calls_this_session"] >= 20:
       logger.warning("yfinance rate limit hit for session")
       return None
   st.session_state["_yf_calls_this_session"] += 1

3. Add the symbol regex from Finding 3 as a pre-filter so obviously invalid strings
   never reach yfinance.
```

---

## Finding 5 — SQLite Connection Leaks on Exception

**Severity: MEDIUM | Confidence: HIGH**

In `db.py`, every function calls `_get_conn()` and later `conn.close()`. But if any operation between those two lines throws an exception, the connection is never closed. For example, if `pd.read_sql_query` raises in `get_latest()`, the connection leaks. Over time in a long-running Streamlit process, this can exhaust SQLite's connection limit or leave WAL locks held.

**Prompt:**
```
Refactor db.py to use context managers for all connections:

Replace the pattern:
    conn = _get_conn()
    df = pd.read_sql_query(...)
    conn.close()
    return df

With:
    conn = _get_conn()
    try:
        df = pd.read_sql_query(...)
        return df
    finally:
        conn.close()

Or better, make _get_conn() work as a context manager:

    from contextlib import contextmanager

    @contextmanager
    def _get_conn():
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        ...
        try:
            yield conn
        finally:
            conn.close()

Then use as:
    with _get_conn() as conn:
        df = pd.read_sql_query(...)
    return df

Apply this pattern to all 5 functions: save_results, get_latest, get_by_date, get_tail,
get_available_dates.
```

---

## Finding 6 — get_tail() N+1 Query Problem

**Severity: MEDIUM | Confidence: HIGH**

In app.py L432-434, `get_tail()` is called once per ticker in a loop. For a view with 11 sector ETFs, that's 11 separate SQLite queries. In Individual view with custom tickers, it could be 20+. This is a classic N+1 query problem.

**Prompt:**
```
Add a batched tail query to db.py and use it in app.py:

1. In db.py, add get_tails_batch():

   def get_tails_batch(tickers: list[str], benchmark: str, n_weeks: int = 5,
                        up_to_date: str | None = None) -> dict[str, pd.DataFrame]:
       conn = _get_conn()
       try:
           placeholders = ",".join("?" * len(tickers))
           if up_to_date:
               query = f"""
                   SELECT * FROM (
                       SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                       FROM rrg_data
                       WHERE ticker IN ({placeholders}) AND benchmark = ? AND date <= ?
                   ) WHERE rn <= ?
                   ORDER BY ticker, date
               """
               params = tickers + [benchmark, up_to_date, n_weeks]
           else:
               query = f"""
                   SELECT * FROM (
                       SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                       FROM rrg_data
                       WHERE ticker IN ({placeholders}) AND benchmark = ?
                   ) WHERE rn <= ?
                   ORDER BY ticker, date
               """
               params = tickers + [benchmark, n_weeks]
           df = pd.read_sql_query(query, conn, params=params)
           return {t: g.reset_index(drop=True) for t, g in df.groupby("ticker")}
       finally:
           conn.close()

2. In app.py, replace the loop (L432-434) with:
   tails = get_tails_batch(list(snapshot["ticker"]), benchmark, tail_weeks,
                           up_to_date=_tail_cutoff)
```

---

## Finding 7 — Redundant Supabase Query: get_next_default_name()

**Severity: LOW | Confidence: HIGH**

On every Individual view page load, `get_next_default_name()` makes a separate Supabase query to fetch all watchlist names. But `list_watchlists()` (called a few lines later) already fetches the same data including names. This is a wasted round-trip (~100-200ms).

**Prompt:**
```
Eliminate the redundant get_next_default_name() Supabase call:

1. In app.py, move the list_watchlists() call earlier and compute the default name from
   the already-fetched data:

   _watchlists = list_watchlists()

   # Compute default name from fetched data (no extra Supabase call)
   import re
   _wl_names = [wl["name"] for wl in _watchlists]
   _pattern = re.compile(r"^Watchlist\s+(\d+)$", re.IGNORECASE)
   _max_num = max((int(m.group(1)) for n in _wl_names if (m := _pattern.match(n))),
                  default=0)
   _default_wl_name = f"Watchlist {_max_num + 1}"

2. Remove the get_next_default_name() call on L249.

3. Reuse _watchlists for the saved watchlists display section below (L279) instead of
   calling list_watchlists() a second time.
```

---

## Finding 8 — Global Cache Clear Affects All Users

**Severity: LOW | Confidence: HIGH**

The "Refresh Data" button (app.py L345) calls `st.cache_data.clear()` which clears ALL `@st.cache_data` caches across the entire Streamlit process — including `load_all_tickers()` (5-minute TTL), `fetch_and_store()`, and any other user's cached data on Streamlit Cloud. In a multi-user deployment, one user's refresh invalidates everyone's cache, triggering redundant yfinance + Supabase calls for all concurrent sessions.

**Prompt:**
```
Scope cache invalidation to the current view's data only:

1. Replace the global st.cache_data.clear() with targeted invalidation:
   fetch_and_store.clear()  # Only clear the RRG pipeline cache

2. Do NOT clear load_all_tickers — it has its own 5-minute TTL and doesn't need manual
   invalidation on refresh.

3. If the user truly needs a full reset, add a separate "Hard Reset" button behind an
   expander with a warning about the multi-user impact.
```

---

## Finding 9 — unsafe_allow_html Without Escaping Dynamic Content

**Severity: LOW | Confidence: HIGH**

Two `st.markdown(..., unsafe_allow_html=True)` calls exist in app.py. The compact-mode CSS (L418-424) is hardcoded and safe. The quadrant summary cards (L467-473) inject `_ticker_str` (derived from `snapshot["ticker"]` values) into raw HTML. While ticker symbols are constrained by yfinance (mostly uppercase alphanumeric), there is no explicit `html.escape()` call, creating an injection surface if the data pipeline is ever modified.

**Prompt:**
```
Add explicit HTML escaping to all dynamic content in unsafe_allow_html blocks:

In app.py, at the top:
    from html import escape as html_escape

In the quadrant summary card section (around L466):
    _ticker_str = html_escape(", ".join(sorted(_tickers))) if _tickers else "—"

This is a defense-in-depth measure — even though current ticker values are safe, the
escaping prevents future regressions.
```

---

## Finding 10 — Broad except Exception Swallows Diagnostic Info

**Severity: LOW | Confidence: HIGH**

Every Supabase function in `watchlists.py` and `ticker_registry.py` catches bare `Exception` and logs a warning. This makes debugging production issues difficult — a 401 (auth expired), 403 (RLS violation), 409 (conflict), or network timeout all produce the same "Failed to X" log message. Users see only "Save failed" with no actionable information.

**Prompt:**
```
Improve error handling granularity in Supabase calls:

1. In watchlists.py and ticker_registry.py, catch specific exception types:

   from postgrest.exceptions import APIError

   try:
       ...
   except APIError as exc:
       logger.warning("Supabase API error in X: status=%s message=%s", exc.code, exc.message)
       if exc.code == "401":
           st.error("Supabase authentication expired. Check your API keys.")
       return fallback_value
   except ConnectionError as exc:
       logger.warning("Network error in X: %s", exc)
       return fallback_value
   except Exception as exc:
       logger.error("Unexpected error in X: %s", exc, exc_info=True)
       return fallback_value

2. In the UI, surface more specific error messages when save_watchlist returns None:
   - "Auth error" vs "Network error" vs "Unknown error"
```

---

## Finding 11 — No Symbol Input Validation Regex

**Severity: LOW | Confidence: HIGH**

`validate_and_register()` only does `.strip().upper()` on the symbol. It does not reject obviously invalid strings like empty-after-strip, very long strings, or strings with special characters. While yfinance won't return valid data for garbage input, the HTTP request is still made, wasting time and potentially triggering Yahoo rate limits.

**Prompt:**
```
Add a symbol format pre-validation in ticker_registry.py validate_and_register():

After symbol = symbol.strip().upper(), add:

    # Reject obviously invalid symbols before hitting yfinance
    if not re.match(r'^[A-Z0-9.^=-]{1,12}$', symbol):
        logger.debug("Rejected invalid symbol format: %s", symbol)
        return None

Also add the same check in validate_symbols() before the loop to fail fast on malformed
input.
```

---

## Finding 12 — Dependencies: All Pinned, No Known CVEs

**Severity: INFO | Confidence: MID**

All 7 dependencies in requirements.txt are pinned with `==`. No known CVEs were found for the specified versions as of March 2026 (checked via Snyk). `streamlit-autorefresh==1.0.1` is a small third-party package with limited security scrutiny — it injects JavaScript for auto-refresh, which is inherently a trust surface.

**Recommendation:** Add a `pip-audit` or `safety` check to CI when a CI pipeline exists. Consider adding `dependabot` or `renovate` for automated version bump PRs.

---

## Summary Table

| # | Finding | Severity | Confidence | Category |
|---|---------|----------|------------|----------|
| 1 | IDOR on watchlist delete (guessable IDs, no user scoping) | HIGH | HIGH | Supabase |
| 2 | FIFO cap delete-before-insert can lose data | HIGH | HIGH | Error Handling |
| 3 | Stored XSS vector via yfinance shortName | MEDIUM | MID | yfinance / XSS |
| 4 | No rate limit on yfinance validation calls | MEDIUM | HIGH | DoS |
| 5 | SQLite connection leaks on exception | MEDIUM | HIGH | Error Handling |
| 6 | N+1 query on get_tail() per ticker | MEDIUM | HIGH | Performance |
| 7 | Redundant Supabase round-trip for default watchlist name | LOW | HIGH | Performance |
| 8 | Global cache clear affects all users | LOW | HIGH | Performance |
| 9 | unsafe_allow_html without html.escape() on dynamic content | LOW | HIGH | XSS |
| 10 | Broad except Exception swallows diagnostics | LOW | HIGH | Error Handling |
| 11 | No symbol format validation regex | LOW | HIGH | Input Validation |
| 12 | Dependencies pinned, no CVEs found | INFO | MID | Dependencies |
