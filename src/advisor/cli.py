"""Command-line entry points.

Usage (see README for full docs)::

    python -m advisor.cli run-daily
    python -m advisor.cli run-monthly
    python -m advisor.cli ingest
    python -m advisor.cli dq-check
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sqlite3
import sys
from datetime import date, datetime, timedelta

from .analyses.activity_nudge import HourPoint, build_activity_nudge
from .analyses.correlation_report import build_correlation_report, notable_correlations
from .analyses.outdoor_comfort import DayForecastInput, rank_outdoor_days
from .analyses.readiness_score import Baseline, compute_readiness_score
from .config import AppConfig, load_config
from .db import get_connection, record_report, was_report_sent
from .dq_checks import log_results, run_all_checks
from .email_report import build_daily_digest, build_monthly_report, send_email
from .ingest import ingest_observed_history, run_full_ingestion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("advisor.cli")

BASELINE_WINDOW_DAYS = 30


def _baseline_from_db(conn: sqlite3.Connection, as_of: date) -> Baseline:
    start = (as_of - timedelta(days=BASELINE_WINDOW_DAYS + 7)).isoformat()
    end = (as_of - timedelta(days=1)).isoformat()
    rows = conn.execute(
        "SELECT hrv, resting_hr FROM daily_health WHERE date >= ? AND date <= ?",
        (start, end),
    ).fetchall()
    hrvs = [r["hrv"] for r in rows if r["hrv"] is not None]
    rhrs = [r["resting_hr"] for r in rows if r["resting_hr"] is not None]
    return Baseline(
        hrv_mean=statistics.mean(hrvs) if len(hrvs) >= 2 else None,
        hrv_std=statistics.pstdev(hrvs) if len(hrvs) >= 2 else None,
        resting_hr_mean=statistics.mean(rhrs) if len(rhrs) >= 2 else None,
        resting_hr_std=statistics.pstdev(rhrs) if len(rhrs) >= 2 else None,
    )


def _hourly_forecast_from_db(conn: sqlite3.Connection, not_before: date) -> list[HourPoint]:
    """Hourly forecast rows from ``not_before`` onward, oldest first.

    ``weather_hourly_forecast`` accumulates rows across ingestion runs (see
    ``ingest.ingest_weather_forecast``), so without this filter a stale
    window from a previous day — one that happened to satisfy the outdoor
    thresholds — would sort ahead of today's real forecast and get
    recommended as if it were still upcoming.
    """
    rows = conn.execute(
        "SELECT * FROM weather_hourly_forecast WHERE target_datetime >= ? ORDER BY target_datetime ASC",
        (not_before.isoformat(),),
    ).fetchall()
    return [
        HourPoint(
            target_datetime=r["target_datetime"],
            temp_c=r["temp_c"],
            precip_prob=r["precip_prob"],
            wind_speed_kmh=r["wind_speed_kmh"],
        )
        for r in rows
    ]


def _comfort_inputs_from_db(conn: sqlite3.Connection, as_of: date) -> list[DayForecastInput]:
    rows = conn.execute(
        "SELECT * FROM weather_daily_forecast WHERE target_date >= ? ORDER BY target_date ASC LIMIT 7",
        (as_of.isoformat(),),
    ).fetchall()
    aqi_rows = {
        r["date"]: r["european_aqi"]
        for r in conn.execute("SELECT date, european_aqi FROM air_quality_daily").fetchall()
    }
    return [
        DayForecastInput(
            date=r["target_date"],
            temp_max_c=r["temp_max_c"],
            temp_min_c=r["temp_min_c"],
            precip_prob_max=r["precip_prob_max"],
            wind_speed_max_kmh=r["wind_speed_max_kmh"],
            european_aqi=aqi_rows.get(r["target_date"]),
        )
        for r in rows
    ]


def cmd_ingest(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    results = run_full_ingestion(conn, config, garmin_days=args.garmin_days)
    logger.info("Ingestion results: %s", results)
    return 0 if all(results.values()) else 1


def cmd_dq_check(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    results = run_all_checks(conn)
    all_ok = log_results(results)
    if not all_ok:
        logger.warning("One or more data quality checks failed; see warnings above.")
    return 0 if all_ok else 1


def cmd_daily_digest(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    today = date.today()
    period_key = today.isoformat()

    if not args.force and was_report_sent(conn, "daily", period_key):
        logger.info("Daily digest for %s already sent; skipping (use --force to resend).", period_key)
        return 0

    ingestion_notes: list[str] = []

    latest_health = conn.execute(
        "SELECT * FROM daily_health ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if latest_health is None:
        ingestion_notes.append("No Garmin health data is available yet — readiness score cannot be computed.")
        latest_health = {}
        as_of = today
    else:
        latest_health = dict(latest_health)
        as_of = datetime.fromisoformat(latest_health["date"]).date()
        staleness = (today - as_of).days
        if staleness > 1:
            ingestion_notes.append(
                f"Latest Garmin data is from {as_of.isoformat()} ({staleness} days old) — Garmin sync may be delayed."
            )

    baseline = _baseline_from_db(conn, as_of)
    readiness = compute_readiness_score(
        sleep_score=latest_health.get("sleep_score"),
        hrv=latest_health.get("hrv"),
        resting_hr=latest_health.get("resting_hr"),
        body_battery_max=latest_health.get("body_battery_max"),
        baseline=baseline,
    )

    activity_dates_rows = conn.execute("SELECT DISTINCT date FROM activities").fetchall()
    activity_dates = [datetime.fromisoformat(r["date"]).date() for r in activity_dates_rows]
    hourly = _hourly_forecast_from_db(conn, today)
    nudge = build_activity_nudge(
        activity_dates,
        as_of,
        hourly,
        inactivity_threshold_days=config.thresholds.inactivity_days,
        temp_min_c=config.thresholds.outdoor_temp_min_c,
        temp_max_c=config.thresholds.outdoor_temp_max_c,
        precip_prob_max=config.thresholds.outdoor_precip_prob_max,
        wind_max_kmh=config.thresholds.outdoor_wind_max_kmh,
    )

    comfort_inputs = _comfort_inputs_from_db(conn, today)
    comfort_rankings = rank_outdoor_days(
        comfort_inputs,
        ideal_temp_min_c=config.thresholds.outdoor_temp_min_c,
        ideal_temp_max_c=config.thresholds.outdoor_temp_max_c,
        wind_max_kmh=config.thresholds.outdoor_wind_max_kmh,
        aqi_good_max=config.thresholds.aqi_good_max,
        aqi_moderate_max=config.thresholds.aqi_moderate_max,
    )

    if not comfort_inputs:
        ingestion_notes.append("No weather forecast data available — outdoor comfort ranking is empty.")

    subject, html, text = build_daily_digest(
        report_date=today.isoformat(),
        nudge=nudge,
        readiness=readiness,
        comfort_rankings=comfort_rankings,
        ingestion_notes=ingestion_notes,
    )

    if args.dry_run:
        print(text)
        return 0

    try:
        send_email(config.email, subject, html, text)
        record_report(conn, "daily", period_key, "sent")
    except Exception as exc:  # noqa: BLE001
        record_report(conn, "daily", period_key, "failed", str(exc))
        logger.error("Failed to send daily digest: %s", exc)
        return 1
    return 0


def cmd_monthly_report(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    today = date.today()
    period_key = f"{today.year:04d}-{today.month:02d}"

    if not args.force and was_report_sent(conn, "monthly", period_key):
        logger.info("Monthly report for %s already sent; skipping (use --force to resend).", period_key)
        return 0

    ingest_observed_history(conn, config)

    start = (today - timedelta(days=30)).isoformat()
    env_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM weather_observed_daily WHERE date >= ?", (start,)
        ).fetchall()
    }
    health_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM daily_health WHERE date >= ?", (start,)
        ).fetchall()
    }
    all_dates = sorted(set(env_rows) | set(health_rows))
    joined = []
    for d in all_dates:
        row = {"date": d}
        row.update({k: v for k, v in env_rows.get(d, {}).items() if k != "date"})
        row.update({k: v for k, v in health_rows.get(d, {}).items() if k != "date"})
        joined.append(row)

    results = build_correlation_report(joined)
    notable = notable_correlations(results)

    subject, html, text = build_monthly_report(report_period=period_key, results=results, notable=notable)

    if args.dry_run:
        print(text)
        return 0

    try:
        send_email(config.email, subject, html, text)
        record_report(conn, "monthly", period_key, "sent")
    except Exception as exc:  # noqa: BLE001
        record_report(conn, "monthly", period_key, "failed", str(exc))
        logger.error("Failed to send monthly report: %s", exc)
        return 1
    return 0


def cmd_run_daily(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    ingest_result = cmd_ingest(config, conn, args)
    dq_result = cmd_dq_check(config, conn, args)
    digest_result = cmd_daily_digest(config, conn, args)
    if dq_result != 0:
        logger.warning("Data quality checks reported issues; digest was still sent with any relevant caveats.")
    if ingest_result != 0:
        logger.warning("Ingestion reported partial failures; see logs above.")
    return digest_result


def cmd_run_monthly(config: AppConfig, conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    return cmd_monthly_report(config, conn, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="advisor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest Garmin + weather data")
    p_ingest.add_argument("--garmin-days", type=int, default=7)
    p_ingest.set_defaults(func=cmd_ingest, needs_email=False, needs_garmin=True)

    p_dq = sub.add_parser("dq-check", help="Run data quality checks")
    p_dq.set_defaults(func=cmd_dq_check, needs_email=False, needs_garmin=False)

    p_daily = sub.add_parser("daily-digest", help="Build and send the daily digest")
    p_daily.add_argument("--dry-run", action="store_true", help="Print instead of sending")
    p_daily.add_argument("--force", action="store_true", help="Resend even if already sent today")
    p_daily.set_defaults(func=cmd_daily_digest, needs_email=True, needs_garmin=False)

    p_monthly = sub.add_parser("monthly-report", help="Build and send the monthly correlation report")
    p_monthly.add_argument("--dry-run", action="store_true")
    p_monthly.add_argument("--force", action="store_true")
    p_monthly.set_defaults(func=cmd_monthly_report, needs_email=True, needs_garmin=False)

    p_run_daily = sub.add_parser("run-daily", help="ingest + dq-check + daily-digest in one call")
    p_run_daily.add_argument("--garmin-days", type=int, default=7)
    p_run_daily.add_argument("--dry-run", action="store_true")
    p_run_daily.add_argument("--force", action="store_true")
    p_run_daily.set_defaults(func=cmd_run_daily, needs_email=True, needs_garmin=True)

    p_run_monthly = sub.add_parser("run-monthly", help="monthly-report (with observed-history ingestion)")
    p_run_monthly.add_argument("--dry-run", action="store_true")
    p_run_monthly.add_argument("--force", action="store_true")
    p_run_monthly.set_defaults(func=cmd_run_monthly, needs_email=True, needs_garmin=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_config(require_email=args.needs_email, require_garmin=args.needs_garmin)

    with get_connection(config.db_path) as conn:
        return args.func(config, conn, args)


if __name__ == "__main__":
    sys.exit(main())
