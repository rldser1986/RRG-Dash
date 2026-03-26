# RRG Dashboard — Code Review Fix Prompts

Ordered from most severe to least severe. Each prompt is self-contained and can be executed independently.

Generated: 2026-03-25

---

## 1. Add input sanitization to watchlist name field

**Severity:** Medium-High

The watchlist name from `st.text_input` is passed directly into the Supabase insert without sanitization. While Supabase's client library parameterizes queries (preventing SQL injection), the name field accepts arbitrary strings including HTML/script tags that could cause rendering issues if ever displayed in a non-Streamlit context. Additionally, there is no length limit enforced.

**Prompt:**

In `src/watchlists.py`, add input sanitization to `save_watchlist()`:

1. Strip the name to a max of 50 characters.
2. Strip leading/trailing whitespace.
3. Reject empty names after stripping (return None).
4. Remove any HTML tags using a simple regex (`re.sub(r"<[^>]+>", "", name)`).

In `app.py`, add `max_chars=50` to the `wl_name_input` text_input widget so the UI enforces the same limit.

---

## 2. Add a spinner around yfinance validation during preset/watchlist load

**Severity:** Medium

When a Quick Pick preset or saved watchlist contains tickers not yet in the Supabase registry, `validate_symbols()` calls yfinance sequentially for each unknown ticker. With 8-ticker presets where several are unknown, this can block the Streamlit rerun for 10–20 seconds. During this time, no widgets have rendered yet — the user sees a blank page with no feedback.

**Prompt:**

In `app.py`, wrap the two validation blocks (preset load around lines 178–196 and watchlist load around lines 155–175) with `st.spinner("Validating new tickers…")`. Both blocks share the same pattern:

```python
if _unknown:
    with st.spinner("Validating new tickers…"):
        _valid, _invalid = validate_symbols(_unknown)
```

Apply this to both the `_pending_preset` block and the `_pending_wl_tickers` block.

---

## 3. Extract duplicated symbol-resolution logic into a helper

**Severity:** Medium

The watchlist-load block (lines 155–175) and the preset-load block (lines 178–196) in `app.py` contain nearly identical logic: pop pending → split known/unknown → `validate_symbols()` → store `_invalid_tickers` → reload options → rebuild `_known`. This is ~40 lines of copy-pasted code that will drift over time.

**Prompt:**

In `app.py`, extract a helper function:

```python
def _resolve_symbols(syms: list[str], ticker_options: list[str]) -tuple[list[str], list[str]]:
    """Resolve a list of raw symbols into multiselect-formatted options.
    Returns (known_options, reloaded_ticker_options).
    Validates unknown symbols via yfinance, stores invalid ones in
    st.session_state["_invalid_tickers"], and reloads ticker_options
    if any new tickers were registered."""
```

Then replace both the `_pending_wl_tickers` block and the `_pending_preset` block with calls to this helper. The watchlist block also sets the benchmark, so keep that part inline.

---

## 4. Log a warning when service_role client silently falls back to anon

**Severity:** Low-Medium

In `src/ticker_registry.py`, `_get_service_client()` falls back to the anon client if `service_key` is missing from secrets. This is intentional for local dev, but in production it means writes to the tickers table will silently fail (blocked by RLS) with no visible error. The existing `logger.warning` only fires on exceptions, not on the empty-key fallback path.

**Prompt:**

In `src/ticker_registry.py` `_get_service_client()`, add a `logger.warning` on the empty-key fallback path:

```python
if not key:
    logger.warning("service_key not configured — ticker writes will use anon client (may fail under RLS)")
    return _get_client()
```

This way, operators checking logs can immediately see why new tickers aren't persisting.

---

## 5. Update README to document Supabase secrets requirement

**Severity:** Low-Medium

`README.md` line 59 says "No secrets or environment variables are required." This was true before the Supabase integration (Phases 3B/5) but is now incorrect. Watchlists and the ticker registry require `supabase.url`, `supabase.key`, and optionally `supabase.service_key` in `.streamlit/secrets.toml`.

**Prompt:**

Update `README.md`:

1. Replace the "No secrets or environment variables are required" line with a section explaining the Supabase configuration.
2. Add a "Secrets" subsection under Setup with:
   - Instructions to create `.streamlit/secrets.toml`
   - The three keys: `supabase.url`, `supabase.key` (anon), `supabase.service_key` (optional, for ticker writes)
   - A note that the app works without Supabase (watchlists disabled, CSV fallback for tickers)
3. Update the project structure tree to include `watchlists.py` and `ticker_registry.py` under `src/`.
4. Under the Deployment section, mention configuring secrets in Streamlit Cloud settings.

---

## 6. Remove dead import: validate_and_register in app.py

**Severity:** Low

`app.py` imports `validate_and_register` from `src.ticker_registry` (line 18) but never calls it directly. Only `validate_symbols()` is used, which internally calls `validate_and_register`. This is a dead import that adds confusion about the public API surface.

**Prompt:**

In `app.py` line 18, remove `validate_and_register` from the import statement:

Change:
```python
from src.ticker_registry import (
    get_ticker_options, get_ticker_df, validate_symbols, validate_and_register,
)
```

To:
```python
from src.ticker_registry import (
    get_ticker_options, get_ticker_df, validate_symbols,
)
```

---

## 7. Remove dead wrapper functions: load_ticker_csv and load_ticker_options

**Severity:** Low

`app.py` defines `load_ticker_csv()` (line 104) and `load_ticker_options()` (line 109) as single-line pass-through wrappers around `get_ticker_df()` and `get_ticker_options()`. They add no caching, no transformation, and no error handling beyond what the underlying functions provide.

**Prompt:**

In `app.py`:

1. Delete the `load_ticker_csv()` function (lines 104–106).
2. Delete the `load_ticker_options()` function (lines 109–111).
3. Replace all calls to `load_ticker_csv()` with `get_ticker_df()` (there is 1 call, around line 130).
4. Replace all calls to `load_ticker_options()` with `get_ticker_options()` (there are ~3 calls).

The imports at the top already include `get_ticker_df` and `get_ticker_options`.

---

## 8. Replace print() with logging in engine.py

**Severity:** Low

`src/engine.py` uses `print()` for status messages (lines 59, 66, 120–123) while all other modules (`watchlists.py`, `ticker_registry.py`) use the `logging` module. This inconsistency makes it harder to filter or suppress output in production.

**Prompt:**

In `src/engine.py`:

1. Add at the top (after existing imports):
   ```python
   import logging
   logger = logging.getLogger(__name__)
   ```
2. Replace the three `print()` calls in `run()` (lines 120, 122, 124) with `logger.info()`.
3. Replace the two `print()` calls with `[WARN]` prefix (lines 59, 66) with `logger.warning()`, removing the manual `[WARN]` prefix.

Keep the same message content, just switch the output mechanism.

---

## 9. Cache schema initialization in db.py

**Severity:** Trivial

Every function in `src/db.py` calls `_get_conn()` which runs `_init_schema()` (CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS) on every single database call. While SQLite handles this idempotently, it is unnecessary overhead on every query.

**Prompt:**

In `src/db.py`, add a module-level flag to skip repeated schema init:

1. Add a module-level variable: `_schema_initialized = False`
2. In `_get_conn()`, check the flag before calling `_init_schema()`:
   ```python
   global _schema_initialized
   if not _schema_initialized:
       _init_schema(conn)
       _schema_initialized = True
   ```

This ensures the schema is created on first access but skipped on subsequent calls within the same process.
