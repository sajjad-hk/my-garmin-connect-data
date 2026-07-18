-- Token storage: lets the ephemeral GitHub Actions runner resume
-- a Garmin session without ever storing a password.
create table if not exists auth_tokens (
    provider   text primary key,
    payload    jsonb not null,
    updated_at timestamptz not null default now()
);

-- Raw activity payloads, keyed by Garmin's own activity id.
create table if not exists activities (
    activity_id bigint primary key,
    raw         jsonb not null,
    started_at  timestamptz
);

-- Raw challenge payloads, refreshed on every sync.
-- Garmin keys challenges by a string uuid, not a numeric id.
create table if not exists challenges (
    challenge_id text primary key,
    raw          jsonb not null,
    updated_at   timestamptz not null default now()
);

-- One row per calendar date, holding whichever daily endpoints we pulled.
-- Columns are nullable because backfill/incremental runs may populate them
-- at different times (e.g. stats today, sleep backfilled later).
create table if not exists daily_metrics (
    metric_date date primary key,
    stats       jsonb,
    sleep       jsonb,
    stress      jsonb,
    hrv         jsonb,
    max_metrics jsonb,
    updated_at  timestamptz not null default now()
);

-- Badges the account has already earned.
create table if not exists earned_badges (
    badge_id   bigint primary key,
    raw        jsonb not null,
    updated_at timestamptz not null default now()
);

-- Full badge catalog — includes badges not yet earned, each carrying
-- badgeProgressValue / badgeTargetValue, which is what tells you
-- how close you are to earning it. This is the table the LLM should
-- query to find "achievable soon" badges.
create table if not exists available_badges (
    badge_id   bigint primary key,
    raw        jsonb not null,
    updated_at timestamptz not null default now()
);

-- Add as needed: goals, personal records, training status
