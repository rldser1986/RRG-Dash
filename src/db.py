"""RRG Database — SQLite wrapper (save, query, lookback)."""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "rrg.db")


def _get_conn() -> sqlite3.Connection:
    """Get a connection to the SQLite database, creating it if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


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

    conn = _get_conn()
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
    conn.close()
    return len(rows)


def get_latest(benchmark: str = "SPY") -> pd.DataFrame:
    """Return the most recent date's data for all tickers against a benchmark."""
    conn = _get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM rrg_data
        WHERE benchmark = ? AND date = (
            SELECT MAX(date) FROM rrg_data WHERE benchmark = ?
        )
        ORDER BY ticker
    """, conn, params=(benchmark, benchmark))
    conn.close()
    return df


def get_by_date(date: str, benchmark: str = "SPY") -> pd.DataFrame:
    """Return data for a specific date and benchmark."""
    conn = _get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM rrg_data
        WHERE date = ? AND benchmark = ?
        ORDER BY ticker
    """, conn, params=(date, benchmark))
    conn.close()
    return df


def get_tail(ticker: str, benchmark: str = "SPY", n_weeks: int = 5,
             up_to_date: str | None = None) -> pd.DataFrame:
    """Return the last N weeks of data for a ticker (for drawing tails).

    If *up_to_date* is given, only rows on or before that date are considered
    (used in lookback mode so the tail ends at the selected date).
    """
    conn = _get_conn()
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
    conn.close()
    return df.sort_values("date").reset_index(drop=True)


def get_available_dates(benchmark: str = "SPY") -> list[str]:
    """Return all distinct dates in the database for a benchmark."""
    conn = _get_conn()
    cursor = conn.execute("""
        SELECT DISTINCT date FROM rrg_data
        WHERE benchmark = ?
        ORDER BY date
    """, (benchmark,))
    dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    return dates
