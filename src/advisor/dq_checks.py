"""Data quality checks: freshness, not-null, and range checks on health
metrics. The check functions are pure (operate on plain dicts/values) so
they're easy to unit test; ``run_all_checks`` wires them up against the
live database.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger("advisor.dq")

RANGE_RULES: dict[str, tuple[float, float]] = {
    "steps": (0, 100_000),
    "resting_hr": (25, 220),
    "sleep_score": (0, 100),
    "hrv": (0, 300),
    "body_battery_max": (0, 100),
    "body_battery_min": (0, 100),
    "training_load": (0, 2000),
    "stress_avg": (0, 100),
}

CRITICAL_FIELDS = ["steps", "sleep_score", "resting_hr"]


@dataclass
class DQCheckResult:
    name: str
    passed: bool
    message: str


def check_freshness(latest_date: Optional[date], as_of: date, max_staleness_days: int = 2) -> DQCheckResult:
    if latest_date is None:
        return DQCheckResult("freshness", False, "No health data has ever been ingested.")
    staleness = (as_of - latest_date).days
    if staleness > max_staleness_days:
        return DQCheckResult(
            "freshness",
            False,
            f"Most recent health record is {staleness} days old (as of {latest_date}); "
            f"expected at most {max_staleness_days}.",
        )
    return DQCheckResult("freshness", True, f"Most recent health record is {staleness} day(s) old.")


def check_not_null(row: dict, required_fields: list[str] = CRITICAL_FIELDS) -> DQCheckResult:
    missing = [f for f in required_fields if row.get(f) is None]
    if missing:
        return DQCheckResult(
            "not_null", False, f"Missing critical fields on {row.get('date', 'unknown date')}: {missing}"
        )
    return DQCheckResult("not_null", True, "All critical fields present.")


def check_ranges(row: dict, rules: dict[str, tuple[float, float]] = RANGE_RULES) -> list[DQCheckResult]:
    results = []
    for field, (lo, hi) in rules.items():
        value = row.get(field)
        if value is None:
            continue
        ok = lo <= value <= hi
        results.append(
            DQCheckResult(
                f"range:{field}",
                ok,
                f"{field}={value} is {'within' if ok else 'OUTSIDE'} expected range [{lo}, {hi}] "
                f"on {row.get('date', 'unknown date')}.",
            )
        )
    return results


def run_all_checks(conn: sqlite3.Connection, *, as_of: Optional[date] = None, max_staleness_days: int = 2) -> list[DQCheckResult]:
    as_of = as_of or date.today()
    results: list[DQCheckResult] = []

    latest_row = conn.execute(
        "SELECT * FROM daily_health ORDER BY date DESC LIMIT 1"
    ).fetchone()
    latest_date = datetime.fromisoformat(latest_row["date"]).date() if latest_row else None
    results.append(check_freshness(latest_date, as_of, max_staleness_days))

    if latest_row is not None:
        row = dict(latest_row)
        results.append(check_not_null(row))
        results.extend(check_ranges(row))

    recent_rows = conn.execute(
        "SELECT * FROM daily_health WHERE date >= ? ORDER BY date DESC",
        ((as_of - timedelta(days=7)).isoformat(),),
    ).fetchall()
    for r in recent_rows:
        results.extend(check_ranges(dict(r)))

    forecast_row = conn.execute(
        "SELECT MAX(fetched_at) as fetched_at FROM weather_daily_forecast"
    ).fetchone()
    if forecast_row and forecast_row["fetched_at"]:
        fetched_at = datetime.fromisoformat(forecast_row["fetched_at"])
        age_hours = (datetime.now(fetched_at.tzinfo) - fetched_at).total_seconds() / 3600
        ok = age_hours <= 30
        results.append(
            DQCheckResult(
                "weather_freshness",
                ok,
                f"Weather forecast last fetched {age_hours:.1f}h ago "
                f"({'ok' if ok else 'STALE, expected <= 30h'}).",
            )
        )
    else:
        results.append(DQCheckResult("weather_freshness", False, "No weather forecast has ever been ingested."))

    return results


def log_results(results: list[DQCheckResult]) -> bool:
    """Log every check result and return True if all passed."""
    all_passed = True
    for r in results:
        level = logging.INFO if r.passed else logging.WARNING
        logger.log(level, "[DQ] %s: %s", r.name, r.message)
        if not r.passed:
            all_passed = False
    return all_passed
