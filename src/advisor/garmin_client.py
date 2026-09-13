"""Defensive wrapper around the unofficial ``garminconnect`` library.

``garminconnect`` talks to Garmin's undocumented internal API by scraping
the same endpoints the Garmin Connect web app uses. It is not officially
supported, individual field names have changed between releases, and
Garmin can rate-limit or temporarily lock accounts that authenticate too
often. This module isolates all of that risk:

* every network call is retried with exponential backoff
* every field extraction is defensive (missing/renamed keys degrade to
  ``None`` instead of raising)
* all failures are logged with enough context to diagnose without ever
  logging credentials
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date as date_type
from typing import Any, Callable, TypeVar

logger = logging.getLogger("advisor.garmin")

T = TypeVar("T")


class GarminAuthError(RuntimeError):
    """Raised when Garmin login fails after all retries."""


class GarminDataError(RuntimeError):
    """Raised when a Garmin data fetch fails after all retries."""


def _retry(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay_seconds: float = 2.0,
    what: str = "operation",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - the unofficial client raises many types
            last_exc = exc
            logger.warning(
                "Garmin %s failed (attempt %d/%d): %s: %s",
                what,
                attempt,
                attempts,
                type(exc).__name__,
                exc,
            )
            if attempt < attempts:
                time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


@dataclass
class DailyHealthMetrics:
    date: str
    steps: int | None = None
    activity_minutes: float | None = None
    sleep_score: int | None = None
    sleep_duration_min: float | None = None
    deep_sleep_min: float | None = None
    light_sleep_min: float | None = None
    rem_sleep_min: float | None = None
    awake_min: float | None = None
    hrv: float | None = None
    resting_hr: int | None = None
    body_battery_max: int | None = None
    body_battery_min: int | None = None
    body_battery_charged: int | None = None
    training_load: float | None = None
    stress_avg: float | None = None


@dataclass
class LoggedActivity:
    activity_id: str
    date: str
    activity_type: str | None
    duration_min: float | None
    distance_m: float | None
    calories: float | None
    start_time: str | None


class GarminClient:
    """Thin, defensive facade over ``garminconnect.Garmin``."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._client = None

    def login(self) -> None:
        try:
            import garminconnect
        except ImportError as exc:  # pragma: no cover - import guard
            raise GarminAuthError(
                "python-garminconnect is not installed; add it to requirements.txt"
            ) from exc

        def _do_login():
            client = garminconnect.Garmin(self._username, self._password)
            client.login()
            return client

        try:
            self._client = _retry(_do_login, what="login")
        except Exception as exc:  # noqa: BLE001
            raise GarminAuthError(
                "Failed to authenticate with Garmin Connect after retries. "
                "Check GARMIN_USERNAME/GARMIN_PASSWORD and whether Garmin is "
                "requiring additional verification for this account."
            ) from exc
        logger.info("Garmin login succeeded")

    def _require_client(self):
        if self._client is None:
            raise GarminAuthError("GarminClient.login() must be called before fetching data")
        return self._client

    @staticmethod
    def _safe_get(d: dict | None, *keys: str, default: Any = None) -> Any:
        """Walk nested dict keys, returning ``default`` on any miss."""
        cur: Any = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur if cur is not None else default

    def fetch_daily_health(self, day: date_type) -> DailyHealthMetrics:
        """Fetch one day of health metrics. Individual metric failures are
        logged and degrade to ``None`` rather than aborting the whole day."""
        client = self._require_client()
        iso = day.isoformat()
        metrics = DailyHealthMetrics(date=iso)

        try:
            stats = _retry(lambda: client.get_stats(iso), what=f"get_stats({iso})")
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch stats for %s: %s", iso, exc)
            stats = {}

        metrics.steps = self._safe_get(stats, "totalSteps")
        metrics.resting_hr = self._safe_get(stats, "restingHeartRate")
        metrics.stress_avg = self._safe_get(stats, "averageStressLevel")
        active_seconds = self._safe_get(stats, "activeSeconds", default=0) or 0
        metrics.activity_minutes = round(active_seconds / 60, 1) if active_seconds else None
        metrics.training_load = self._safe_get(stats, "trainingLoad")

        try:
            sleep = _retry(lambda: client.get_sleep_data(iso), what=f"get_sleep_data({iso})")
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch sleep for %s: %s", iso, exc)
            sleep = {}

        dto = self._safe_get(sleep, "dailySleepDTO", default={}) or {}
        metrics.sleep_score = self._safe_get(dto, "sleepScores", "overall", "value")
        total_sleep_s = self._safe_get(dto, "sleepTimeSeconds")
        metrics.sleep_duration_min = round(total_sleep_s / 60, 1) if total_sleep_s else None
        deep_s = self._safe_get(dto, "deepSleepSeconds")
        light_s = self._safe_get(dto, "lightSleepSeconds")
        rem_s = self._safe_get(dto, "remSleepSeconds")
        awake_s = self._safe_get(dto, "awakeSleepSeconds")
        metrics.deep_sleep_min = round(deep_s / 60, 1) if deep_s else None
        metrics.light_sleep_min = round(light_s / 60, 1) if light_s else None
        metrics.rem_sleep_min = round(rem_s / 60, 1) if rem_s else None
        metrics.awake_min = round(awake_s / 60, 1) if awake_s else None

        try:
            hrv = _retry(lambda: client.get_hrv_data(iso), what=f"get_hrv_data({iso})")
            metrics.hrv = self._safe_get(hrv, "hrvSummary", "lastNightAvg")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch HRV for %s: %s", iso, exc)

        try:
            bb = _retry(
                lambda: client.get_body_battery(iso, iso), what=f"get_body_battery({iso})"
            )
            if isinstance(bb, list) and bb:
                day_bb = bb[0]
                metrics.body_battery_charged = self._safe_get(day_bb, "charged")
                values = self._safe_get(day_bb, "bodyBatteryValuesArray", default=[]) or []
                levels = [v[1] for v in values if isinstance(v, (list, tuple)) and len(v) > 1 and v[1] is not None]
                if levels:
                    metrics.body_battery_max = max(levels)
                    metrics.body_battery_min = min(levels)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch body battery for %s: %s", iso, exc)

        return metrics

    def fetch_activities(self, start: date_type, end: date_type) -> list[LoggedActivity]:
        """Fetch logged activities between start and end (inclusive)."""
        client = self._require_client()
        try:
            raw = _retry(
                lambda: client.get_activities_by_date(start.isoformat(), end.isoformat()),
                what=f"get_activities_by_date({start}..{end})",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch activities for %s..%s: %s", start, end, exc)
            return []

        activities: list[LoggedActivity] = []
        for a in raw or []:
            start_time = self._safe_get(a, "startTimeLocal")
            act_date = (start_time or "")[:10] or start.isoformat()
            duration_s = self._safe_get(a, "duration")
            activities.append(
                LoggedActivity(
                    activity_id=str(self._safe_get(a, "activityId", default="")),
                    date=act_date,
                    activity_type=self._safe_get(a, "activityType", "typeKey"),
                    duration_min=round(duration_s / 60, 1) if duration_s else None,
                    distance_m=self._safe_get(a, "distance"),
                    calories=self._safe_get(a, "calories"),
                    start_time=start_time,
                )
            )
        return activities
