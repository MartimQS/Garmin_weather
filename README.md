# Personal Performance & Environment Advisor

A fully automated personal analytics pipeline that combines your Garmin
Connect health data with live weather and air-quality data to produce
daily and monthly recommendations, delivered by email, running entirely
on GitHub Actions' free tier with no server and no manual intervention
after setup.

## What it does

Every day it:

1. Pulls your last 7 days of Garmin health data (steps, sleep, HRV,
   resting heart rate, body battery, training load, logged activities).
2. Pulls the weather and air-quality forecast for your configured
   location from Open-Meteo.
3. Computes three analyses and emails you a **daily digest**:
   - **Activity Nudge** — flags an inactivity streak and, if you're
     inactive, points at a specific upcoming window of good outdoor
     weather.
   - **Readiness Score** — a 0-100 composite of sleep, HRV, resting HR
     trend, and body battery, with a hard/easy/rest-day recommendation.
   - **Outdoor Comfort Ranking** — ranks the next 7 days by how pleasant
     they'll be for outdoor activity (temperature, rain, wind, air
     quality).

Once a month it additionally runs the **Monthly Correlation Report**,
which looks for relationships between environmental variables (pressure,
temperature, air quality) and health metrics (sleep score, HRV, resting
HR) over the trailing 30 days, and emails a summary.

## Architecture

```
GitHub Actions (cron)
    │
    ├── daily.yml  ──► python -m advisor.cli run-daily   ──► ingest Garmin + weather
    │                                                          │
    │                                                          ▼
    │                                                    SQLite (data/advisor.db)
    │                                                          │
    │                                                          ▼
    │                                                  compute analyses, email digest
    │                                                          │
    │                                                          ▼
    │                                              commit updated .db back to the repo
    │
    └── monthly.yml ──► python -m advisor.cli run-monthly ──► same DB, correlation report
```

- **Language/runtime**: Python 3.11, standard library + `requests` +
  `garminconnect`. No web framework, no scheduler daemon.
- **Storage**: a single SQLite file, `data/advisor.db`, **committed to
  the git repository** by the workflow after each run. This is the key
  design decision that makes the whole thing work on GitHub Actions'
  free, ephemeral runners with zero external accounts: each run checks
  out the repo (and therefore the database with all prior history),
  appends/upserts new rows, and pushes the updated file back. Git handles
  versioning and durability for free; a `.db` diff is opaque binary, but
  at personal-project scale (~100KB/year) this is a non-issue, and the
  full history is always recoverable from git log if ever needed.
- **Transformations**: plain Python functions/dataclasses in
  `src/advisor/analyses/`, unit-tested directly (no SQL transformation
  layer, no dbt).
- **Scheduling**: GitHub Actions `schedule:` triggers (cron), running on
  the hosted `ubuntu-latest` runner. Free for a personal repo.
- **Delivery**: SMTP (Gmail) via Python's stdlib `smtplib`/`email`.

### Why this stack, and not Snowflake + dbt

The prompt asked me to explicitly evaluate both directions.

**Snowflake + dbt** is the more "enterprise-realistic" choice and would
be the right call if this pipeline needed to scale to many users, many
sources, or needed dbt's testing/lineage/documentation tooling at team
scale. For a single person's data, though, it adds friction that doesn't
buy anything here:

- A trial Snowflake account expires and requires managing yet another
  credential set (account name, user, password/key-pair, warehouse,
  role) purely for a project whose entire dataset is a few thousand rows
  a year.
- Snowflake can't reach the public internet on its own — pulling from
  Garmin and Open-Meteo from *inside* Snowflake requires External Access
  Integrations, network rules, and a secrets object, which is
  meaningfully more setup than "set five GitHub secrets."
  Realistically you'd still run the ingestion in Python/GitHub Actions
  and only *load* into Snowflake, at which point Snowflake is pure
  storage overhead with no transformation benefit for a dataset this
  small.
- dbt's value (declarative, testable, documented SQL models; incremental
  materializations; lineage graphs) pays off with many models and
  many contributors. Four analyses over three tables don't need it —
  the "transformation logic" here is threshold/scoring logic
  (weighted composites, contiguous-window search, Pearson correlation)
  that reads far more clearly as typed Python functions than as SQL
  window-function gymnastics, and it's the part of this project the
  spec explicitly wants unit-tested — trivial in pytest, awkward in
  dbt's test framework.
- Ongoing maintenance/cost risk: trial credits run out; a forgotten
  warehouse can rack up compute cost. A SQLite file committed to git
  costs nothing and never expires.

**What I chose instead**: Python + SQLite, orchestrated entirely inside
one GitHub Actions job, with the SQLite file committed back to the repo
as durable storage. This satisfies "reliability running unattended,"
"low ongoing maintenance," and "free" simultaneously, without conceding
good engineering practice — the ingestion is idempotent, the scoring
logic is unit tested, and data quality checks run every day.
I did reject the absolute-simplest alternative (recomputing everything
from scratch every run, no persistence) because the Monthly Correlation
Report and the Activity Nudge's "inactivity streak" both need history
that spans further back than any single API call conveniently provides
— hence a real (if small) database rather than "simplicity for its own
sake."

## Repository structure

```
src/advisor/
  config.py              # env var loading & validation
  db.py                  # SQLite schema + idempotent upsert helpers
  garmin_client.py        # defensive wrapper around python-garminconnect
  weather_client.py       # Open-Meteo forecast/air-quality/archive client
  ingest.py               # idempotent ingestion orchestration
  dq_checks.py             # freshness / not-null / range data quality checks
  email_report.py         # HTML+text email builders and SMTP sender
  cli.py                   # command-line entry points used by GH Actions
  analyses/
    activity_nudge.py
    readiness_score.py
    outdoor_comfort.py
    correlation_report.py
tests/                     # pytest suite (41+ tests) for all analyses + dq checks
.github/workflows/
  ci.yml                   # run tests on every push/PR
  daily.yml                # scheduled: ingest + daily digest, commits db
  monthly.yml               # scheduled: correlation report, commits db
data/advisor.db            # committed SQLite database (schema only until first run)
```

## Prerequisites

1. **A Garmin Connect account** with health tracking data (steps, sleep,
   HRV, body battery, etc. — these come from a Garmin wearable synced to
   the app). This project authenticates with your normal Garmin Connect
   username/password via the unofficial `python-garminconnect` library —
   no Garmin developer account or API key is needed (Garmin's official
   Health API is a business product with an approval process; this
   project intentionally does not use it — see the note on unofficial
   API risk below).
2. **Your location's latitude/longitude.** Easiest way: search your
   address on [OpenStreetMap](https://www.openstreetmap.org), right
   click the pin, and choose "Show address" — the coordinates are shown
   in the URL/sidebar. Precision to ~2 decimal places is plenty.
3. **A Gmail account with an App Password** (or any other SMTP provider).
   Gmail App Passwords require 2-Step Verification to be enabled on the
   account:
   - Go to <https://myaccount.google.com/security>.
   - Enable **2-Step Verification** if it isn't already.
   - Go to <https://myaccount.google.com/apppasswords>, create an app
     password (any name, e.g. "advisor"), and copy the 16-character
     password. Use this, not your normal Gmail password, as
     `SMTP_PASSWORD`.
4. **A GitHub account** and a fork/clone of this repository under your
   own account (Actions run against your repo, using your secrets).

No warehouse account, no API keys for weather (Open-Meteo is free and
keyless), no Garmin developer account.

## Setup

### 1. Configure GitHub Actions secrets

In your GitHub repository: **Settings → Secrets and variables → Actions
→ New repository secret**. Add each of the following:

| Secret | Required | Example | Notes |
|---|---|---|---|
| `GARMIN_USERNAME` | yes | `you@example.com` | Your Garmin Connect login email |
| `GARMIN_PASSWORD` | yes | `••••••••` | Your Garmin Connect password |
| `LOCATION_LATITUDE` | yes | `38.7223` | Decimal degrees |
| `LOCATION_LONGITUDE` | yes | `-9.1393` | Decimal degrees |
| `LOCATION_TIMEZONE` | no | `Europe/Lisbon` | IANA tz name, or `auto` (default) to infer from lat/long |
| `SMTP_HOST` | no | `smtp.gmail.com` | Defaults to Gmail's SMTP host |
| `SMTP_PORT` | no | `587` | Defaults to 587 (STARTTLS) |
| `SMTP_USERNAME` | yes | `you@gmail.com` | Your Gmail address |
| `SMTP_PASSWORD` | yes | `xxxxxxxxxxxxxxxx` | The 16-char Gmail **App Password**, not your login password |
| `EMAIL_FROM` | yes | `you@gmail.com` | Usually the same as `SMTP_USERNAME` |
| `EMAIL_TO` | yes | `you@gmail.com` | Where the reports are delivered — can be the same address |

Threshold overrides (all optional — see "Customizing thresholds" below)
can also be added as secrets or left at their defaults, which are baked
into the code:

| Secret | Default | Meaning |
|---|---|---|
| `THRESHOLD_INACTIVITY_DAYS` | `3` | Days without a logged activity before the Activity Nudge fires |
| `THRESHOLD_OUTDOOR_TEMP_MIN_C` / `_MAX_C` | `10` / `27` | "Comfortable" outdoor temperature band |
| `THRESHOLD_OUTDOOR_PRECIP_PROB_MAX` | `30` | Max acceptable precipitation probability (%) |
| `THRESHOLD_OUTDOOR_WIND_MAX_KMH` | `25` | Max acceptable wind speed |
| `THRESHOLD_FORECAST_WINDOW_HOURS` | `48` | How far ahead the Activity Nudge looks for a window |
| `THRESHOLD_AQI_GOOD_MAX` / `_MODERATE_MAX` | `50` / `100` | European AQI breakpoints |

These threshold values are read from environment variables at runtime;
if you don't add them as secrets, the workflow simply won't set the
corresponding env var and the built-in default is used — you don't need
to add all of them, only the ones you want to change.

### 2. Enable the workflows

The workflows in `.github/workflows/` are scheduled (`daily.yml` at
06:30 UTC, `monthly.yml` at 07:00 UTC on the 1st) and also support manual
runs via **Actions → (workflow name) → Run workflow** — use that to test
before waiting for the schedule. GitHub Actions schedules only run on
the repository's default branch, so once you're happy with this branch,
merge it to your default branch (or change the default branch) for the
schedule to fire.

Both workflows need `permissions: contents: write` (already set in the
workflow files) so the job can commit the updated `data/advisor.db` back
to the repo — this is how state persists between ephemeral runs.

### 3. Verify the first run

- Go to **Actions → Daily Advisor Digest → Run workflow** and trigger it
  manually.
- Watch the run logs. A healthy run logs `Garmin login succeeded`,
  ingestion summaries, `[DQ]` check lines, and ends with `Sent email ...`.
- Check your inbox for "Daily Advisor Digest — <date> — Readiness: ...".
- Check that the run committed a change to `data/advisor.db` (visible as
  a new commit on the branch, authored by `advisor-bot`).
- If it's your very first run, several analyses will be sparse: the
  Readiness Score's HRV/RHR components need ~2+ days of history for a
  baseline (they degrade gracefully to a neutral midpoint until then),
  and the Monthly Correlation Report needs real history to say anything
  meaningful — this is expected and self-corrects after the pipeline has
  run for a while.

## Running and testing locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then fill in your real values
export $(grep -v '^#' .env | xargs)   # or use direnv / python-dotenv of your choice

# Run the unit test suite (no credentials needed — these are pure logic tests)
pytest -q

# Ingest data only
PYTHONPATH=src python -m advisor.cli ingest

# Run data quality checks
PYTHONPATH=src python -m advisor.cli dq-check

# Preview the daily digest without sending an email
PYTHONPATH=src python -m advisor.cli daily-digest --dry-run

# Preview the monthly report without sending an email
PYTHONPATH=src python -m advisor.cli monthly-report --dry-run

# Actually send (uses real SMTP credentials)
PYTHONPATH=src python -m advisor.cli run-daily
PYTHONPATH=src python -m advisor.cli run-monthly
```

`--dry-run` prints the report to stdout instead of emailing it, and skips
the "already sent today/this month" de-duplication check — safe to run
repeatedly while developing. Real sends are recorded in the `reports_log`
table so `run-daily`/`run-monthly` won't double-email if a scheduled run
is retried the same day/month (pass `--force` to resend deliberately).

## Customizing thresholds and location

All thresholds live in `src/advisor/config.py` as environment-variable
defaults (see the table in Setup above). To change one, either export it
locally before running, or add/update the corresponding GitHub Actions
secret — no code changes needed. Location (`LOCATION_LATITUDE` /
`LOCATION_LONGITUDE`) works the same way.

If you want to change the *scoring weights* (e.g. weight sleep more
heavily than HRV in the Readiness Score, or change how strongly air
quality affects the Outdoor Comfort Ranking), those are the `WEIGHTS`
dictionaries at the top of `src/advisor/analyses/readiness_score.py` and
`src/advisor/analyses/outdoor_comfort.py` — deliberately kept as simple,
documented constants rather than more env variables, since they're a
judgment call you'd only revisit occasionally, by reading the code.

## Assumptions made

Documented here per the instructions, so you know what to revisit:

- **Readiness Score weights**: sleep 35%, HRV 25%, resting HR trend 20%,
  body battery 20%. HRV and resting HR are scored relative to your own
  trailing ~30-37 day baseline (z-score based), not absolute values,
  since "good" HRV/RHR varies hugely by individual. When a component is
  missing (e.g. no HRV sensor data that day), the score re-normalizes
  over whatever components are available rather than penalizing you for
  missing data.
- **Outdoor Comfort weights**: temperature 35%, precipitation 30%, wind
  15%, air quality 20%. Temperature scores peak within your configured
  "comfortable" band and fall off linearly outside it; air quality uses
  the European AQI scale from Open-Meteo.
- **"Meaningful logged activity"** for the Activity Nudge means a Garmin
  *activity* (a run, ride, walk you started tracking, etc.), not just
  raw step count — the idea is to flag "you haven't exercised," not
  "you didn't walk today."
- **Correlation Report** requires at least 8 paired days of data for a
  given (environmental, health) variable combination before reporting a
  coefficient; below that it's reported as "insufficient data" rather
  than a misleadingly precise number from a handful of points. "Notable"
  correlations shown up front are |r| ≥ 0.3.
- **Historical weather** for the correlation report comes from
  Open-Meteo's ERA5-based archive API, which has roughly a 5-6 day
  processing lag — the code queries up to 6 days back to avoid holes.
- **Database-in-git**: chosen deliberately (see Architecture) over a
  hosted database, given the personal, low-volume nature of this
  project. It does mean the repo's size grows slowly over time and that
  two workflow runs writing at the exact same moment could race on the
  push — mitigated with `concurrency: group: advisor-db` in both
  workflows (only one runs at a time) plus a rebase-and-retry loop on
  push.

## Troubleshooting

**Garmin login fails / `GarminAuthError`**
`python-garminconnect` logs into the same undocumented endpoints as the
Garmin Connect mobile/web app. Common causes:
- Wrong username/password in secrets (note: Garmin accounts created via
  "Sign in with Google/Facebook/Apple" don't have a separate Garmin
  password — you'd need to set one in Garmin Connect account settings).
- Garmin temporarily requiring a CAPTCHA or MFA challenge after several
  failed/unusual logins (e.g. from a new IP, which every GitHub Actions
  run technically is) — if this happens, log into
  garmin.com/connect in a browser once, complete any challenge, wait a
  bit, and re-run the workflow.
- The library is unofficial (see below) and can simply break when Garmin
  changes something. Check for a `garminconnect` package update
  (`pip install -U garminconnect`) if failures are new and persistent.
The pipeline is designed to keep going even when this happens: the
Garmin ingestion step logs the failure and returns, weather ingestion
and the email still run, and the digest email explicitly notes "Garmin
data unavailable this run" rather than silently sending stale/wrong
numbers.

**Email send failures**
- Double check `SMTP_PASSWORD` is an **App Password**, not your regular
  Gmail password (regular passwords are rejected by Gmail for SMTP once
  2-Step Verification is on, which App Passwords require).
- If using a non-Gmail provider, confirm `SMTP_HOST`/`SMTP_PORT` and
  whether it expects STARTTLS (`SMTP_USE_TLS=true`, the default) or
  implicit TLS on a different port.
- The workflow logs the SMTP exception; sends are retried 3x with
  backoff before the job is marked failed.

**API rate limits / transient network errors**
- Both the Garmin and Open-Meteo clients retry (4 attempts, exponential
  backoff starting at 2s) before giving up, and log each attempt.
- Open-Meteo's free tier is generous for a single-location personal
  project (well under its documented limits at one call/day), so
  persistent 429s likely mean a bug (e.g. a tight retry loop) rather than
  real usage — check the Actions log for repeated calls.

**Data quality check failures**
`dq-check` logs warnings (not hard failures) for staleness, missing
critical fields, or out-of-range values, so a bad data day doesn't block
the digest — but it's worth reading the Action log occasionally, since a
consistently-failing check usually means an upstream field name changed
(see the unofficial-library note below) or your wearable stopped
syncing.

## A note on `python-garminconnect`

This project deliberately uses the unofficial, reverse-engineered
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library, authenticating with your **personal Garmin Connect
credentials** — not Garmin's official Connect Developer/Health API,
which is a paid, approval-gated B2B product not accessible to individual
hobbyists for a project like this. That trade-off means:

- It is **not officially supported by Garmin** and can break without
  warning if Garmin changes their internal web/app API.
- Logging in from an automated context (like a GitHub Actions runner)
  occasionally triggers Garmin's bot/abuse defenses (see
  Troubleshooting above).
- Your Garmin password is stored as a GitHub Actions secret. GitHub
  encrypts secrets at rest and masks them in logs, but as with any
  automation holding real account credentials, only use this against an
  account you're comfortable delegating to a script, and consider a
  dedicated Garmin login if your primary account matters to you for
  other reasons.

If Garmin's API changes and ingestion starts failing, the fix is almost
always in `src/advisor/garmin_client.py` — the field-extraction helpers
are isolated there specifically so a Garmin-side change requires editing
one file, not the whole pipeline.
