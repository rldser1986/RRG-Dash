#!/usr/bin/env python3
"""Seed the Supabase 'tickers' table from sp500_tickers.csv.

Run once to populate the registry:
    python scripts/seed_tickers.py

Requires SUPABASE_URL and SUPABASE_KEY environment variables, or
.streamlit/secrets.toml with [supabase] url and key.
"""

import os
import sys

# Add project root to path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd


def main():
    # Try to load secrets from .streamlit/secrets.toml via environment
    # or fall back to env vars
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not url or not key:
        # Try to read from .streamlit/secrets.toml
        import tomllib

        secrets_path = os.path.join(
            os.path.dirname(__file__), "..", ".streamlit", "secrets.toml"
        )
        if os.path.exists(secrets_path):
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
            url = secrets.get("supabase", {}).get("url")
            # Prefer service_key for write access; fall back to anon key
            key = (
                secrets.get("supabase", {}).get("service_key")
                or secrets.get("supabase", {}).get("key")
            )

    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars,")
        print("       or configure .streamlit/secrets.toml with service_key")
        sys.exit(1)

    from supabase import create_client

    client = create_client(url, key)

    # Load CSV
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "sp500_tickers.csv")
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} tickers from CSV")

    rows = [
        {
            "symbol": row["Symbol"],
            "company": row.get("Company", ""),
            "sector": row.get("GICS Sector", ""),
            "industry": row.get("GICS Sub-Industry", ""),
        }
        for _, row in df.iterrows()
    ]

    # Upsert in batches
    batch_size = 100
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        client.table("tickers").upsert(batch).execute()
        total += len(batch)
        print(f"  Upserted {total}/{len(rows)}")

    print(f"Done! {total} tickers seeded.")


if __name__ == "__main__":
    main()
