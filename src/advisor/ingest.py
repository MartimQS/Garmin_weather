"""Idempotent ingestion of Garmin health data and Open-Meteo weather/AQI data.

Every ingestion function upserts by natural key (date, activity id), so
re-running any of them — whether because a scheduled job retried or a
developer ran it manually — never creates duplicate rows.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from .config import AppConfig
from .db import record_ingestion, upsert
from .garmin_client import GarminAuthError, GarminClient
from .weather_client import WeatherClient

logger = logging.getLogger("advisor.ingest")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_garmin_health(conn: sqlite3.Connection, config: AppConfig, days: int = 7) -> bool:
    """Fetch and upsert the trailing ``days`` of Garmin health data.

    Returns True on success, False if Garmin ingestion failed entirely
    (network/auth issue). Callers should continue the rest of the pipeline
    (weather, email) even when this returns False — degrade gracefully
    rather than aborting the whole run.
    """
    try:
        client = GarminClient(config.garmin.username, config.garmin.password)
        client.login()
    except GarminAuthError as exc:
        logger.error("Garmin login failed, skipping Garmin ingestion: %s", exc)
        record_ingestion(conn, "garmin", "failed", str(exc))
        return False

    today = date.today()
    start = today - timedelta(days=days - 1)
    failures = 0

    cur = start
    while cur <= today:
        try:
            metrics = client.fetch_daily_health(cur)
            row = asdict(metrics)
            row["ingested_at"] = _now_iso()
            upsert(conn, "daily_health", ["date"], row)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.error("Failed to ingest Garmin health for %s: %s", cur, exc)
        cur += timedelta(days=1)

    try:
        activities = client.fetch_activities(start, today)
        for act in activities:
            if not act.activity_id:
                continue
            row = asdict(act)
            row["ingested_at"] = _now_iso()
            upsert(conn, "activities", ["activity_id"], row)
    except Exception as exc:  # noqa: BLE001
        failures += 1
        logger.error("Failed to ingest Garmin activities: %s", exc)

    status = "success" if failures == 0 else "partial_failure"
    record_ingestion(conn, "garmin", status, f"{failures} failures over {days} days")
    return failures == 0


def ingest_weather_forecast(conn: sqlite3.Connection, config: AppConfig) -> bool:
    """Fetch and upsert daily + hourly forecast and forward air-quality data."""
    client = WeatherClient(
        config.location.latitude, config.location.longitude, config.location.timezone
    )
    try:
        daily = client.fetch_daily_forecast(days=8)
        for f in daily:
            row = asdict(f)
            row["fetched_at"] = _now_iso()
            upsert(conn, "weather_daily_forecast", ["target_date"], row)

        hourly = client.fetch_hourly_forecast(hours=config.thresholds.forecast_window_hours)
        for f in hourly:
            row = asdict(f)
            row["fetched_at"] = _now_iso()
            upsert(conn, "weather_hourly_forecast", ["target_datetime"], row)

        aq = client.fetch_daily_air_quality(days=8)
        for a in aq:
            row = asdict(a)
            row["fetched_at"] = _now_iso()
            upsert(conn, "air_quality_daily", ["date"], row)

        record_ingestion(conn, "weather_forecast", "success")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to ingest weather forecast: %s", exc)
        record_ingestion(conn, "weather_forecast", "failed", str(exc))
        return False


def ingest_observed_history(conn: sqlite3.Connection, config: AppConfig, days_back: int = 35) -> bool:
    """Backfill observed (historical) pressure/temperature/AQI for the
    trailing ``days_back`` days, used by the monthly correlation report.

    Uses the archive API (small lag for final quality data) plus the
    air-quality API's ``past_days`` parameter.
    """
    client = WeatherClient(
        config.location.latitude, config.location.longitude, config.location.timezone
    )
    today = date.today()
    archive_end = today - timedelta(days=6)  # ERA5 reanalysis has a short lag
    archive_start = today - timedelta(days=days_back)
    if archive_start > archive_end:
        archive_start = archive_end

    combined: dict[str, dict] = {}
    try:
        observed = client.fetch_observed_daily(archive_start.isoformat(), archive_end.isoformat())
        for row in observed:
            combined[row["date"]] = {
                "date": row["date"],
                "pressure_hpa": row.get("pressure_hpa"),
                "temp_mean_c": row.get("temp_mean_c"),
                "european_aqi": None,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch observed archive weather: %s", exc)
        record_ingestion(conn, "weather_observed", "failed", str(exc))
        return False

    try:
        aq_hist = client.fetch_daily_air_quality(days=1, past_days=min(days_back, 92))
        for a in aq_hist:
            if a.date in combined:
                combined[a.date]["european_aqi"] = a.european_aqi
            elif a.date <= archive_end.isoformat():
                combined[a.date] = {
                    "date": a.date,
                    "pressure_hpa": None,
                    "temp_mean_c": None,
                    "european_aqi": a.european_aqi,
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch historical air quality: %s", exc)

    for row in combined.values():
        row["fetched_at"] = _now_iso()
        upsert(conn, "weather_observed_daily", ["date"], row)

    record_ingestion(conn, "weather_observed", "success", f"{len(combined)} days")
    return True


def run_full_ingestion(conn: sqlite3.Connection, config: AppConfig, garmin_days: int = 7) -> dict:
    """Run all ingestion steps, tolerating partial failures. Returns a
    dict summarizing success/failure of each source so callers (e.g. the
    daily digest) can decide how to caveat their output."""
    results = {
        "garmin": ingest_garmin_health(conn, config, days=garmin_days),
        "weather_forecast": ingest_weather_forecast(conn, config),
        "weather_observed": ingest_observed_history(conn, config),
    }
    return results
