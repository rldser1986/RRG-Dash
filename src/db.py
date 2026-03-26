"""RRG Database — SQLite wrapper (save, query, lookback)."""

import sqlite3
import os
from contextlib import contextmanager

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "rrg.db")

_schema_initialized = False


@contextmanager
def _get_conn():
    """Yield a connection to the SQLite database, auto-closing on exit.

    Uses a context manager to prevent connection leaks on exceptions
    (see SECURITY-AUDIT-2.md Finding #5).
    """
    global _schema_initialized
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    if not _schema_initialized:
        _init_schema(conn)
        _schema_initialized = True
    try:
        yield conn
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create the rrg_data table and index if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rrg_data (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            benchmark TEXT NOT NULL,
            rs REAL,
            rs_ratio REAL,
            rs_momentum REAL,
            quadrant TEXT,
            PRIMARY KEY (date, ticker, benchmark)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON rrg_data(date)")
    conn.commit()


def save_results(df: pd.DataFrame) -> int:
    """Upsert computed RRG DataFrame into SQLite. Returns rows written."""
    if df.empty:
        return 0

    with _get_conn() as conn:
        rows = df[["date", "ticker", "benchmark", "rs", "rs_ratio",
                    "rs_momentum", "quadrant"]].values.tolist()

        conn.executemany("""
            INSERT INTO rrg_data (date, ticker, benchmark, rs, rs_ratio, rs_momentum, quadrant)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, ticker, benchmark)
            DO UPDATE SET rs=excluded.rs, rs_ratio=excluded.rs_ratio,
                          rs_momentum=excluded.rs_momentum, quadrant=excluded.quadrant
        """, rows)
        conn.commit()
        return len(rows)


def get_latest(benchmark: str = "SPY") -> pd.DataFrame:
    """Return the most recent date's data for all tickers against a benchmark."""
    with _get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT * FROM rrg_data
            WHERE benchmark = ? AND date = (
                SELECT MAX(date) FROM rrg_data WHERE benchmark = ?
            )
            ORDER BY ticker
        """, conn, params=(benchmark, benchmark))
    return df


def get_by_date(date: str, benchmark: str = "SPY") -> pd.DataFrame:
    """Return data for a specific date and benchmark."""
    with _get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT * FROM rrg_data
            WHERE date = ? AND benchmark = ?
            ORDER BY ticker
        """, conn, params=(date, benchmark))
    return df


def get_tail(ticker: str, benchmark: str = "SPY", n_weeks: int = 5,
             up_to_date: str | None = None) -> pd.DataFrame:
    """Return the last N weeks of data for a ticker (for drawing tails).

    If *up_to_date* is given, only rows on or before that date are considered
    (used in lookback mode so the tail ends at the selected date).
    """
    with _get_conn() as conn:
        if up_to_date:
            df = pd.read_sql_query("""
                SELECT * FROM rrg_data
                WHERE ticker = ? AND benchmark = ? AND date <= ?
                ORDER BY date DESC
                LIMIT ?
            """, conn, params=(ticker, benchmark, up_to_date, n_weeks))
        else:
            df = pd.read_sql_query("""
                SELECT * FROM rrg_data
                WHERE ticker = ? AND benchmark = ?
                ORDER BY date DESC
                LIMIT ?
            """, conn, params=(ticker, benchmark, n_weeks))
    return df.sort_values("date").reset_index(drop=True)


def get_tails_batch(
    tickers: list[str], benchmark: str = "SPY", n_weeks: int = 5,
    up_to_date: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Return tail data for multiple tickers in a single query.

    Replaces N individual get_tail() calls with one query using
    ROW_NUMBER() window function (see SECURITY-AUDIT-2.md Finding #6).
    """
    if not tickers:
        return {}

    placeholders = ",".join("?" * len(tickers))

    with _get_conn() as conn:
        if up_to_date:
            query = f"""
                SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY ticker ORDER BY date DESC
                    ) AS rn
                    FROM rrg_data
                    WHERE ticker IN ({placeholders}) AND benchmark = ? AND date <= ?
                ) sub
                WHERE rn <= ?
                ORDER BY ticker, date
            """
            params = tickers + [benchmark, up_to_date, n_weeks]
        else:
            query = f"""
                SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY ticker ORDER BY date DESC
                    ) AS rn
                    FROM rrg_data
                    WHERE ticker IN ({placeholders}) AND benchmark = ?
                ) sub
                WHERE rn <= ?
                ORDER BY ticker, date
            """
            params = tickers + [benchmark, n_weeks]

        df = pd.read_sql_query(query, conn, params=params)

    # Split into per-ticker DataFrames; provide empty DF for missing tickers
    result: dict[str, pd.DataFrame] = {}
    if not df.empty:
        df = df.drop(columns=["rn"], errors="ignore")
        for t, group in df.groupby("ticker"):
            result[str(t)] = group.reset_index(drop=True)

    # Ensure every requested ticker has an entry
    empty = pd.DataFrame(columns=["date", "ticker", "benchmark", "rs",
                                   "rs_ratio", "rs_momentum", "quadrant"])
    for t in tickers:
        if t not in result:
            result[t] = empty.copy()

    return result


def get_available_dates(benchmark: str = "SPY") -> list[str]:
    """Return all distinct dates in the database for a benchmark."""
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT DISTINCT date FROM rrg_data
            WHERE benchmark = ?
            ORDER BY date
        """, (benchmark,))
        dates = [row[0] for row in cursor.fetchall()]
    return dates
