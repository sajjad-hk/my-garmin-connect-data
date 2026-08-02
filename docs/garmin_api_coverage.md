# Garmin Connect API coverage

Audit of every public method on `garminconnect.Garmin` (v0.3.6, the version
pinned in `ingestion/requirements.txt`), tracking what this project pulls
into Postgres versus what's still untapped.

This file didn't exist before the training/wellness/body-composition
expansion — it was created from scratch by listing `dir(garminconnect.Garmin)`
(136 public methods) and cross-checking against `ingestion/pull.py` and
`backfill.py`. Keep it in sync going forward: when you wire in a new
method, move it out of "Not used yet" and into "Currently ingested".

## Currently ingested

Every field name below was confirmed against a live API response before
being written into `schema/init.sql` — see the git history for the probe
sessions if a shape ever needs re-checking against a live account.

| Method | Stored as |
|---|---|
| `get_activities_by_date` | `activities` (upsert by `activityId`) |
| `get_available_badge_challenges` | `challenges` (upsert by `uuid`) |
| `get_earned_badges` | `earned_badges` (upsert by `badgeId`) |
| `get_available_badges` | `available_badges` (upsert by `badgeId`) |
| `get_stats` | `daily_metrics.stats` |
| `get_sleep_data` | `daily_metrics.sleep` |
| `get_all_day_stress` | `daily_metrics.stress` |
| `get_hrv_data` | `daily_metrics.hrv` |
| `get_max_metrics` | `daily_metrics.max_metrics` |
| `get_respiration_data` | `daily_metrics.respiration` |
| `get_spo2_data` | `daily_metrics.spo2` |
| `get_body_battery` | `daily_metrics.body_battery` — one range call per sync window, fanned out per date via the response's `date` field (not looped per-date) |
| `get_body_battery_events` | `daily_metrics.body_battery_events` |
| `get_intensity_minutes_data` | `daily_metrics.intensity_minutes` |
| `get_floors` | `daily_metrics.floors` — 15-minute interval data, not a duplicate of `stats.floorsAscended` (a daily total) |
| `get_steps_data` | `daily_metrics.steps_intraday` — 15-minute interval data, not a duplicate of `stats.totalSteps` |
| `get_heart_rates` | `daily_metrics.heart_rates` — ~2-minute interval time series, richer than `stats`' HR summary fields |
| `get_all_day_events` | `daily_metrics.day_events` |
| `get_weigh_ins` | `daily_metrics.weigh_in` — one range call per sync window, fanned out per date via `dailyWeightSummaries[].summaryDate`; null on days with no scale reading (expected, not a gap) |
| `get_training_status` | `training_insight.training_status` |
| `get_training_readiness` | `training_insight.training_readiness` |
| `get_morning_training_readiness` | `training_insight.morning_training_readiness` — kept separate from `training_readiness` even though it likely overlaps one entry in that list (by `inputContext=AFTER_WAKEUP_RESET`); direct query is simpler than parsing the list for it |
| `get_endurance_score` | `training_insight.endurance_score` — called with a single date (not a range); the range form returns a coarser multi-day rollup that's harder to key cleanly per day |
| `get_hill_score` | `training_insight.hill_score` — same single-date reasoning as `get_endurance_score` |
| `get_fitnessage_data` | `training_insight.fitness_age` |
| `get_running_tolerance` | `training_insight.running_tolerance` — called with `startdate == enddate`, `aggregation="daily"`; empty on this account/device, but confirmed to not error |
| `get_race_predictions` | `performance_snapshots` (`metric_name = 'race_predictions'`) — called with no arguments, which the library treats as "predictions as of today"; there's no history to loop over |
| `get_cycling_ftp` | `performance_snapshots` (`metric_name = 'cycling_ftp'`) — "most recent known value", not per-date |
| `get_lactate_threshold` | `performance_snapshots` (`metric_name = 'lactate_threshold'`) — called with `latest=True` (the default) |
| `get_personal_record` | `personal_records` (upsert by `id`, verified live) |
| `get_goals` | `goals` — **no verified id field** (this account has zero goals in any status, so the response shape's natural key couldn't be confirmed against real data). Stored via delete-then-insert per status (`active`/`future`/`past`) with a surrogate `bigserial` id, instead of guessing a primary key to upsert on. If you later see real goal data with a stable id field, switch this to an upsert like `personal_records`. |

## Investigated, deliberately not used (duplicates)

These were checked live and found to be lower-resolution or exact
duplicates of data already captured above — skipped per the "don't add
redundant columns" convention.

| Method | Why skipped |
|---|---|
| `get_daily_steps` | Range call returning `calendarDate, totalSteps, totalDistance, stepGoal` per day — identical fields to what `stats.totalSteps`/`totalDistanceMeters`/`dailyStepGoal` already provide. `get_steps_data` (kept) provides the genuinely new 15-minute granularity. |
| `get_rhr_day` | Returns the same `restingHeartRate` value already in `stats`, just wrapped in a `metricsMap` structure. No additional information. |
| `get_daily_weigh_ins` | Same underlying weigh-in data as `get_weigh_ins`, but scoped to a single day's `totalAverage` — a strict subset. |
| `get_body_composition` | Confirmed live (range including a known weigh-in date) to return the exact same `dateWeightList` entries as `get_weigh_ins`' `allWeightMetrics`, just without `get_weigh_ins`' per-day summary grouping (`minWeight`/`maxWeight`/`numOfWeightEntries`). |
| `get_weekly_stress` | Weekly-rollup average stress keyed by week-end date — lower resolution than the daily `stress` data already pulled, and the weekly grain doesn't fit the `metric_date` primary key used everywhere else. |
| `get_weekly_intensity_minutes` | Same reasoning as `get_weekly_stress` — `intensity_minutes_data` already carries `weeklyModerate`/`weeklyVigorous`/`weeklyTotal` per day, so this weekly-grain endpoint adds no new information at daily resolution. |

## Not used yet

Everything else on the client. Grouped by theme; not exhaustive on every
possible use case, just enough to orient a future pass.

**Activity detail** (would need the three-tier fetch-if-missing pattern
described in this project's task notes, since it's one call per activity,
not per date): `get_activity`, `get_activity_details`, `get_activity_splits`,
`get_activity_split_summaries`, `get_activity_typed_splits`,
`get_activity_weather`, `get_activity_hr_in_timezones`,
`get_activity_power_in_timezones`, `get_activity_exercise_sets`,
`get_activity_gear`, `get_activities`, `get_activities_fordate`,
`get_last_activity`, `count_activities`, `download_activity`, `download`.

**Gear**: `get_gear`, `get_gear_activities`, `get_gear_defaults`,
`get_gear_stats`.

**Workouts / training plans**: `get_workouts`, `get_workout_by_id`,
`get_scheduled_workouts`, `get_scheduled_workout_by_id`,
`get_training_plans`, `get_training_plan_by_id`,
`get_adaptive_training_plan_by_id`, `schedule_workout`,
`unschedule_workout`, `upload_workout`, `upload_cycling_workout`,
`upload_hiking_workout`, `upload_running_workout`,
`upload_swimming_workout`, `upload_walking_workout`, `download_workout`.

**Device management**: `get_devices`, `get_device_settings`,
`get_device_alarms`, `get_device_last_used`, `get_device_solar_data`,
`get_primary_training_device`.

**Health tracking outside this project's scope**: `get_blood_pressure`,
`set_blood_pressure`, `delete_blood_pressure`, `get_hydration_data`,
`add_hydration_data`, `get_menstrual_calendar_data`,
`get_menstrual_data_for_date`, `get_pregnancy_summary`,
`get_lifestyle_logging_data`.

**Nutrition**: `get_nutrition_daily_food_log`, `get_nutrition_daily_meals`,
`get_nutrition_daily_settings`.

**Golf**: `get_golf_scorecard`, `get_golf_summary`, `get_golf_shot_data`.

**Challenges (partial coverage)**: `get_adhoc_challenges`,
`get_badge_challenges`, `get_non_completed_badge_challenges`,
`get_in_progress_badges`, `get_inprogress_virtual_challenges` — only
`get_available_badge_challenges` is currently pulled.

**Account / profile / misc**: `get_user_profile`, `get_full_name`,
`get_unit_system`, `get_userprofile_settings`, `get_progress_summary_between_dates`,
`get_stats_and_body`, `get_stress_data`, `get_weekly_steps`,
`query_garmin_graphql`, `request_reload`.

**Write operations** (out of scope — this project is read-only against
Garmin): `add_weigh_in`, `add_weigh_in_with_timestamps`, `delete_weigh_in`,
`delete_weigh_ins`, `add_body_composition`, `add_gear_to_activity`,
`remove_gear_from_activity`, `set_gear_default`, `create_manual_activity`,
`create_manual_activity_from_json`, `delete_activity`, `delete_workout`,
`import_activity`, `upload_activity`, `set_activity_name`,
`set_activity_type`, `set_activity_description`,
`set_activity_exercise_sets`.

**Auth / low-level plumbing** (used internally by the library, not
something this project calls directly): `login`, `logout`, `resume_login`,
`connectapi`, `connectwebproxy`.
