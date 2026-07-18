"""
Run this ONCE, locally, right after generate_token.py.
Reads the token files from ~/.garminconnect and pushes them into the
auth_tokens table in Neon, so the GitHub Actions job can pick them up.

Usage:
    DATABASE_URL="postgresql://..." python bootstrap/load_token_to_db.py
"""

import os
import json
import pathlib

import psycopg

TOKEN_DIR = pathlib.Path.home() / ".garminconnect"
DB_URL = os.environ["DATABASE_URL"]


def main() -> None:
    payload = {f.name: f.read_text() for f in TOKEN_DIR.glob("*.json")}
    if not payload:
        raise RuntimeError(f"No token files found in {TOKEN_DIR} — run generate_token.py first.")

    with psycopg.connect(DB_URL) as conn:
        conn.execute(
            """
            create table if not exists auth_tokens (
                provider   text primary key,
                payload    jsonb not null,
                updated_at timestamptz not null default now()
            )
            """
        )
        conn.execute(
            """
            insert into auth_tokens (provider, payload, updated_at)
            values ('garmin', %s, now())
            on conflict (provider)
            do update set payload = excluded.payload, updated_at = now()
            """,
            (json.dumps(payload),),
        )
        conn.commit()

    print("Token pushed to Neon. Ingestion job (pull.py) can now run unattended.")


if __name__ == "__main__":
    main()
