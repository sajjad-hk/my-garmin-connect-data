"""
Run this ONCE, locally, to backfill history that pull.py's incremental
lookback window doesn't cover. Safe to re-run — it skips daily_metrics
dates already in the DB, so an interrupted run can just be restarted.

Usage:
    DATABASE_URL="postgresql://..." python backfill.py

Optional env vars:
    BACKFILL_START_DATE   YYYY-MM-DD. Defaults to 2 years ago.
                          Activities always backfill fully regardless of this
                          (Garmin paginates that in one call, it's cheap).
                          This setting only controls how far back the
                          per-day metrics loop (stats/sleep/stress/hrv/VO2max)
                          goes, since that's one API call per metric per day —
                          2 years already means ~3,650 requests.
"""

import os
import json
import pathlib
import time
from datetime import date, timedelta

import psycopg
from garminconnect import Garmin

TOKEN_DIR = pathlib.Path.home() / ".garminconnect"
DB_URL = os.environ["DATABASE_URL"]

DEFAULT_START = (date.today() - timedelta(days=365 * 2)).isoformat()
START_DATE = os.environ.get("BACKFILL_START_DATE", DEFAULT_START)

# Very early date — Garmin accounts don't predate this, so this safely
# captures "everything" without needing to know the real account creation date.
ACTIVITY_HISTORY_START = "2000-01-01"


def load_token_from_db(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "select payload from auth_tokens where provider = 'garmin'"
    ).fetchone()
    if not row:
        raise RuntimeError("No stored Garmin token found. Run the bootstrap scripts first.")
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in row[0].items():
        (TOKEN_DIR / filename).write_text(content)


def save_token_to_db(conn: psycopg.Connection) -> None:
    payload = {f.name: f.read_text() for f in TOKEN_DIR.glob("*.json")}
    conn.execute(
        """
        insert into auth_tokens (provider, payload, updated_at)
        values ('garmin', %s, now())
        on conflict (provider) do update set payload = excluded.payload, updated_at = now()
        """,
        (json.dumps(payload),),
    )
    conn.commit()


def upsert_activities(conn: psycopg.Connection, activities: list[dict]) -> None:
    for a in activities:
        conn.execute(
            """
            insert into activities (activity_id, raw, started_at)
            values (%s, %s, %s)
            on conflict (activity_id) do update set raw = excluded.raw
            """,
            (a["activityId"], json.dumps(a), a.get("startTimeLocal")),
        )
    conn.commit()


def already_have_metrics(conn: psycopg.Connection, d: date) -> bool:
    row = conn.execute(
        "select 1 from daily_metrics where metric_date = %s", (d,)
    ).fetchone()
    return row is not None


def upsert_daily_metrics(conn: psycopg.Connection, d: date, stats, sleep, stress, hrv, max_metrics) -> None:
    conn.execute(
        """
        insert into daily_metrics (metric_date, stats, sleep, stress, hrv, max_metrics, updated_at)
        values (%s, %s, %s, %s, %s, %s, now())
        on conflict (metric_date) do update set
            stats = excluded.stats, sleep = excluded.sleep,
            stress = excluded.stress, hrv = excluded.hrv,
            max_metrics = excluded.max_metrics, updated_at = now()
        """,
        (d, json.dumps(stats), json.dumps(sleep), json.dumps(stress), json.dumps(hrv), json.dumps(max_metrics)),
    )
    conn.commit()


def main() -> None:
    with psycopg.connect(DB_URL) as conn:
        load_token_from_db(conn)

        client = Garmin()
        client.login(tokenstore=str(TOKEN_DIR))

        print(f"Backfilling all activities since {ACTIVITY_HISTORY_START}...")
        activities = client.get_activities_by_date(
            ACTIVITY_HISTORY_START, date.today().isoformat(), sortorder="asc"
        )
        upsert_activities(conn, activities)
        print(f"  -> {len(activities)} activities upserted.")

        start = date.fromisoformat(START_DATE)
        today = date.today()
        total_days = (today - start).days + 1
        print(f"Backfilling daily metrics from {start} to {today} ({total_days} days)...")

        done = 0
        skipped = 0
        for offset in range(total_days):
            d = start + timedelta(days=offset)

            if already_have_metrics(conn, d):
                skipped += 1
                continue

            iso = d.isoformat()
            stats = client.get_stats(iso)
            sleep = client.get_sleep_data(iso)
            stress = client.get_all_day_stress(iso)
            hrv = client.get_hrv_data(iso)
            max_metrics = client.get_max_metrics(iso)
            upsert_daily_metrics(conn, d, stats, sleep, stress, hrv, max_metrics)

            done += 1
            if done % 20 == 0:
                print(f"  ...{done} days pulled, {skipped} already present, at {iso}")
                save_token_to_db(conn)  # checkpoint token periodically on long runs
            time.sleep(1)

        save_token_to_db(conn)
        print(f"Done. {done} days pulled, {skipped} already present.")


if __name__ == "__main__":
    main()
