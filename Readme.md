# Garmin Data Sync — Setup Guide

Pulls your Garmin Connect data (activities, daily health metrics, challenges,
badges) into your own private Postgres database, so it's available for
analysis outside the Garmin app.

**Important: this is per-person.** Each person needs their own copy of this
repo, their own free Neon database, and their own Garmin login token. You
can't share a database or token between two Garmin accounts — set it up
independently for each person.

---

## What you'll need before starting

- A computer with Python 3.12 or newer installed
- Your own Garmin Connect account (email + password, and your phone/email
  handy if you have two-factor/MFA enabled on it)
- A free [Neon](https://neon.tech) account (Postgres database, no credit
  card needed for the free tier)
- `git` installed, to download the code
- (Optional, for automatic daily syncing) A free GitHub account

Setup takes about 15–20 minutes the first time.

---

## Step 1 — Get the code

```bash
git clone <repo-url>
cd my-garmin-connect-data
```

## Step 2 — Set up a Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -r ingestion/requirements.txt
```

## Step 3 — Create your free database

1. Go to [neon.tech](https://neon.tech) and sign up.
2. Create a new project (any name, e.g. "garmin-data").
3. On the project dashboard, copy the **connection string** — it looks like
   `postgresql://user:password@host/dbname?sslmode=require`.

## Step 4 — Save your database connection locally

Create a file called `.env` in the project folder:

```bash
echo 'DATABASE_URL="paste-your-neon-connection-string-here"' > .env
```

Make sure the value is in quotes — connection strings often contain an `&`
character, which breaks things if left unquoted.

**Never share this file or commit it to git** — it contains your database
password. It's already excluded via `.gitignore`, so a normal `git push`
won't include it, but don't paste its contents anywhere public either.

## Step 5 — Create the database tables

```bash
psql "$DATABASE_URL" -f schema/init.sql
```

If `psql` isn't installed: it comes with PostgreSQL. On Mac, `brew install
postgresql`; on Ubuntu/Debian/CachyOS, `sudo pacman -S postgresql` or `sudo
apt install postgresql-client`; on Windows, install via the official
[PostgreSQL installer](https://www.postgresql.org/download/windows/).

## Step 6 — Log in to Garmin and generate your access token

```bash
python bootstrap/generate_token.py
```

- Enter your Garmin email and password when prompted.
- If your account has MFA/two-factor enabled, Garmin will send you a code
  (by email or the Connect app) — enter it when the script asks.
- Your password is **never stored anywhere** after this step — only a
  session token is saved, to `~/.garminconnect/garmin_tokens.json`.

## Step 7 — Push that token to your database

```bash
python bootstrap/load_token_to_db.py
```

This lets future syncs (including ones running unattended in the cloud)
resume your Garmin session without needing your password again.

## Step 8 — Test it: pull your data

```bash
python ingestion/pull.py
```

You should see a summary table showing what was fetched and how many rows
were new. If this works, your setup is complete and functional.

## Step 9 — (Optional) Backfill your full history

Step 8 only pulls the last few days. To pull years of past data:

```bash
python backfill.py
```

This takes a while (it's making thousands of individual API calls, with
deliberate pauses to avoid overloading Garmin's servers) — it's safe to
stop and re-run later, it picks up where it left off. By default it goes
back 2 years for daily health metrics; set `BACKFILL_START_DATE` (format
`YYYY-MM-DD`) as an environment variable first if you want further back.

---

## Optional — automatic daily syncing (no computer needs to stay on)

This uses GitHub Actions to run the sync automatically every day, on
GitHub's servers rather than your own machine.

1. Push this repo to your own GitHub account (make your own copy/fork, not
   a shared one).
2. In your repo: **Settings → Secrets and variables → Actions → New
   repository secret**, and add:
    - `NEON_DATABASE_URL` — same value as your local `.env`'s `DATABASE_URL`
    - `NTFY_TOPIC` *(optional)* — a random, hard-to-guess name (e.g.
      `garmin-sync-a3f91c8e2b04`) if you want a push notification when a
      sync fails. Subscribe to that same name in the free
      [ntfy](https://ntfy.sh) app to receive it.
3. Go to the **Actions** tab → `garmin-sync` → **Run workflow** to trigger
   it manually the first time and confirm it works.
4. After that, it runs automatically on its own schedule (currently daily).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | You forgot to activate the venv, or need `pip install -r ingestion/requirements.txt` again |
| `KeyError: 'DATABASE_URL'` | `.env` isn't set up, or you're running `psql` directly (which doesn't read `.env` — run `set -a; source .env; set +a` first) |
| `relation "..." does not exist` | Re-run `psql "$DATABASE_URL" -f schema/init.sql` |
| `429` / rate limited during login | Wait a few minutes before retrying — Garmin temporarily blocks repeated login attempts |
| `MFA Required` | Your account has two-factor enabled; the script will prompt for the code — just make sure you're ready to receive it before running |

---

## A few honest caveats

- This uses an **unofficial** Python library (`garminconnect`) that mimics
  Garmin's own app, since Garmin's official developer program isn't open
  to individuals. It generally works well but can break if Garmin changes
  something on their end — if a sync suddenly fails, that's the most
  likely cause.
- Keep sync frequency reasonable (this is already set up to run once a
  day) — hammering Garmin's login endpoint risks your account getting
  temporarily flagged.