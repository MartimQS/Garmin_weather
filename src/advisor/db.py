"""SQLite storage layer.

SQLite is committed to the repo as ``data/advisor.db`` so that state
survives across ephemeral GitHub Actions runners without needing any
external warehouse account. All writes are upserts keyed by natural keys
(date, activity id, report period) so re-running a job never duplicates
rows.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_health (
    date TEXT PRIMARY KEY,
    steps INTEGER,
    activity_minutes REAL,
    sleep_score INTEGER,
    sleep_duration_min REAL,
    deep_sleep_min REAL,
    light_sleep_min REAL,
    rem_sleep_min REAL,
    awake_min REAL,
    hrv REAL,
    resting_hr INTEGER,
    body_battery_max INTEGER,
    body_battery_min INTEGER,
    body_battery_charged INTEGER,
    training_load REAL,
    stress_avg REAL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    activity_type TEXT,
    duration_min REAL,
    distance_m REAL,
    calories REAL,
    start_time TEXT,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);

CREATE TABLE IF NOT EXISTS weather_daily_forecast (
    target_date TEXT PRIMARY KEY,
    temp_max_c REAL,
    temp_min_c REAL,
    precip_prob_max REAL,
    wind_speed_max_kmh REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_hourly_forecast (
    target_datetime TEXT PRIMARY KEY,
    temp_c REAL,
    precip_prob REAL,
    wind_speed_kmh REAL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hourly_forecast_dt ON weather_hourly_forecast(target_datetime);

CREATE TABLE IF NOT EXISTS air_quality_daily (
    date TEXT PRIMARY KEY,
    european_aqi REAL,
    pm2_5 REAL,
    pm10 REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_observed_daily (
    date TEXT PRIMARY KEY,
    pressure_hpa REAL,
    temp_mean_c REAL,
    european_aqi REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports_log (
    report_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    PRIMARY KEY (report_type, period_key)
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    source TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def get_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert(conn: sqlite3.Connection, table: str, key_columns: list[str], row: dict) -> None:
    """Generic idempotent upsert keyed on ``key_columns``."""
    columns = list(row.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in columns if c not in key_columns)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({', '.join(key_columns)}) DO UPDATE SET {update_clause}"
    )
    conn.execute(sql, row)


def was_report_sent(conn: sqlite3.Connection, report_type: str, period_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reports_log WHERE report_type = ? AND period_key = ? AND status = 'sent'",
        (report_type, period_key),
    ).fetchone()
    return row is not None


def record_report(
    conn: sqlite3.Connection, report_type: str, period_key: str, status: str, detail: str = ""
) -> None:
    from datetime import datetime, timezone

    upsert(
        conn,
        "reports_log",
        ["report_type", "period_key"],
        {
            "report_type": report_type,
            "period_key": period_key,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "detail": detail,
        },
    )


def record_ingestion(conn: sqlite3.Connection, source: str, status: str, detail: str = "") -> None:
    from datetime import datetime, timezone

    conn.execute(
        "INSERT INTO ingestion_log (source, run_at, status, detail) VALUES (?, ?, ?, ?)",
        (source, datetime.now(timezone.utc).isoformat(), status, detail),
    )
