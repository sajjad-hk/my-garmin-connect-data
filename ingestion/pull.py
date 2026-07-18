"""
Runs on every scheduled GitHub Actions execution.
Assumes a Garmin token was already generated once via bootstrap/generate_token.py
and pushed to the auth_tokens table via bootstrap/load_token_to_db.py.

Each run:
  1. Pulls the current token from Postgres, writes it to the expected local path.
  2. Logs in to Garmin using that token (no password needed — resumes session).
  3. Pulls activities and daily metrics for a lookback window (not just "today"),
     so a missed run doesn't leave a permanent gap. Also refreshes challenges
     and the full badges list.
  4. Upserts everything into the normalized tables.
  5. Reads back the (possibly refreshed) token files and saves them to Postgres,
     so the next ephemeral runner picks up the latest one.

For pulling FULL history (years of past data), use backfill.py instead —
this script is deliberately a small, cheap, incremental sync.
"""

import os
import json
import pathlib
import time
from datetime import date, timedelta

import psycopg
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()  # reads .env in the current directory into os.environ, if present

TOKEN_DIR = pathlib.Path.home() / ".garminconnect"
DB_URL = os.environ["DATABASE_URL"]

# How many days back to re-check on every run. Covers gaps if a scheduled
# run is skipped (e.g. runner outage) without re-pulling everything.
LOOKBACK_DAYS = 5


def load_token_from_db(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "select payload from auth_tokens where provider = 'garmin'"
    ).fetchone()
    if not row:
        raise RuntimeError(
            "No stored Garmin token found. Run bootstrap/generate_token.py "
            "and bootstrap/load_token_to_db.py once before the first sync."
        )
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in row[0].items():
        (TOKEN_DIR / filename).write_text(content)


def save_token_to_db(conn: psycopg.Connection) -> None:
    payload = {f.name: f.read_text() for f in TOKEN_DIR.glob("*.json")}
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


def table_count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"select count(*) from {table}").fetchone()[0]  # noqa: S608 (fixed table names, not user input)


def write_step_summary(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    text = "\n".join(lines) + "\n"
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(text)
    else:
        print(text)  # local run — no GITHUB_STEP_SUMMARY file, just print instead
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


def upsert_challenges(conn: psycopg.Connection, challenges: list[dict]) -> None:
    for c in challenges:
        conn.execute(
            """
            insert into challenges (challenge_id, raw, updated_at)
            values (%s, %s, now())
                on conflict (challenge_id) do update set raw = excluded.raw, updated_at = now()
            """,
            (c["uuid"], json.dumps(c)),
        )
    conn.commit()


def upsert_earned_badges(conn: psycopg.Connection, badges: list[dict]) -> None:
    # NOTE: assumes the id field is "badgeId" — same caveat as before, not yet
    # verified against a live response. If this throws, print badges[0].keys()
    # and fix the key name here.
    for b in badges:
        conn.execute(
            """
            insert into earned_badges (badge_id, raw, updated_at)
            values (%s, %s, now())
                on conflict (badge_id) do update set raw = excluded.raw, updated_at = now()
            """,
            (b["badgeId"], json.dumps(b)),
        )
    conn.commit()


def upsert_available_badges(conn: psycopg.Connection, badges: list[dict]) -> None:
    # Same field-name caveat as upsert_earned_badges.
    for b in badges:
        conn.execute(
            """
            insert into available_badges (badge_id, raw, updated_at)
            values (%s, %s, now())
                on conflict (badge_id) do update set raw = excluded.raw, updated_at = now()
            """,
            (b["badgeId"], json.dumps(b)),
        )
    conn.commit()


def upsert_daily_metrics(conn: psycopg.Connection, d: date, stats, sleep, stress, hrv, max_metrics) -> None:
    conn.execute(
        """
        insert into daily_metrics (metric_date, stats, sleep, stress, hrv, max_metrics, updated_at)
        values (%s, %s, %s, %s, %s, %s, now())
            on conflict (metric_date) do update set
            stats = excluded.stats,
                                             sleep = excluded.sleep,
                                             stress = excluded.stress,
                                             hrv = excluded.hrv,
                                             max_metrics = excluded.max_metrics,
                                             updated_at = now()
        """,
        (d, json.dumps(stats), json.dumps(sleep), json.dumps(stress), json.dumps(hrv), json.dumps(max_metrics)),
    )
    conn.commit()


def main() -> None:
    with psycopg.connect(DB_URL) as conn:
        load_token_from_db(conn)

        client = Garmin()
        client.login(tokenstore=str(TOKEN_DIR))

        today = date.today()
        tables = ["activities", "challenges", "earned_badges", "available_badges", "daily_metrics"]
        before = {t: table_count(conn, t) for t in tables}

        window_start = today - timedelta(days=LOOKBACK_DAYS)

        # Activities: date-range pagination, not offset-based — offset-based
        # (start=0, limit=N) only ever returns the N most recent, which is
        # what silently dropped history before.
        activities = client.get_activities_by_date(
            window_start.isoformat(), today.isoformat(), sortorder="asc"
        )
        upsert_activities(conn, activities)

        challenges = client.get_available_badge_challenges(1, 100)
        upsert_challenges(conn, challenges)

        earned_badges = client.get_earned_badges()
        upsert_earned_badges(conn, earned_badges)

        available_badges = client.get_available_badges()
        upsert_available_badges(conn, available_badges)

        # Daily metrics are per-date endpoints — loop the lookback window.
        for offset in range(LOOKBACK_DAYS + 1):
            d = window_start + timedelta(days=offset)
            iso = d.isoformat()
            stats = client.get_stats(iso)
            sleep = client.get_sleep_data(iso)
            stress = client.get_all_day_stress(iso)
            hrv = client.get_hrv_data(iso)
            max_metrics = client.get_max_metrics(iso)
            upsert_daily_metrics(conn, d, stats, sleep, stress, hrv, max_metrics)
            time.sleep(1)  # be gentle — several calls per day, several days

        save_token_to_db(conn)

        after = {t: table_count(conn, t) for t in tables}

    api_counts = {
        "activities": len(activities),
        "challenges": len(challenges),
        "earned_badges": len(earned_badges),
        "available_badges": len(available_badges),
    }

    summary = ["### Garmin sync summary", "", "| Table | New rows | Fetched from API | Total in DB |", "|---|---|---|---|"]
    for t in tables:
        new_rows = after[t] - before[t]
        fetched = api_counts.get(t, "—")
        summary.append(f"| {t} | +{new_rows} | {fetched} | {after[t]} |")

    total_new = sum(after[t] - before[t] for t in tables)
    if total_new == 0:
        summary.append("")
        summary.append(
            "_No new rows this run — normal if nothing changed on Garmin's side "
            "since the last sync (e.g. a rest day). If you expected new activity "
            "data and see 0 here, that's worth investigating._"
        )

    write_step_summary(summary)


if __name__ == "__main__":
    main()