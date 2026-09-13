"""Activity Nudge: detect inactivity streaks and suggest a favorable
outdoor window from the upcoming forecast.

All functions here are pure (no I/O, no DB, no network) so the
threshold/window logic can be unit tested directly against plain data
structures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple, Optional


class HourPoint(NamedTuple):
    target_datetime: str  # ISO 8601, e.g. "2024-05-01T14:00"
    temp_c: Optional[float]
    precip_prob: Optional[float]
    wind_speed_kmh: Optional[float]


@dataclass
class FavorableWindow:
    start: str
    end: str
    avg_temp_c: float
    max_precip_prob: float
    max_wind_kmh: float


@dataclass
class ActivityNudgeResult:
    days_since_last_activity: Optional[int]
    is_inactive: bool
    window: Optional[FavorableWindow]
    message: str


def days_since_last_activity(activity_dates: list[date], as_of: date) -> Optional[int]:
    """Days elapsed since the most recent logged activity. ``None`` if no
    activity has ever been logged."""
    if not activity_dates:
        return None
    most_recent = max(activity_dates)
    return (as_of - most_recent).days


def is_inactive_streak(days_since: Optional[int], threshold_days: int) -> bool:
    if days_since is None:
        return True
    return days_since >= threshold_days


def _hour_is_suitable(
    hour: HourPoint,
    temp_min_c: float,
    temp_max_c: float,
    precip_prob_max: float,
    wind_max_kmh: float,
) -> bool:
    if hour.temp_c is None or hour.precip_prob is None or hour.wind_speed_kmh is None:
        return False
    return (
        temp_min_c <= hour.temp_c <= temp_max_c
        and hour.precip_prob <= precip_prob_max
        and hour.wind_speed_kmh <= wind_max_kmh
    )


def find_best_outdoor_window(
    hours: list[HourPoint],
    *,
    temp_min_c: float,
    temp_max_c: float,
    precip_prob_max: float,
    wind_max_kmh: float,
    min_consecutive_hours: int = 2,
) -> Optional[FavorableWindow]:
    """Return the earliest contiguous block of at least
    ``min_consecutive_hours`` suitable hours, or ``None`` if no such block
    exists in the supplied forecast."""
    run: list[HourPoint] = []
    for hour in hours:
        if _hour_is_suitable(hour, temp_min_c, temp_max_c, precip_prob_max, wind_max_kmh):
            run.append(hour)
            if len(run) >= min_consecutive_hours:
                # Keep extending the run to capture the full window, but we
                # already have a qualifying block starting at run[0].
                continue
        else:
            if len(run) >= min_consecutive_hours:
                return _window_from_run(run)
            run = []
    if len(run) >= min_consecutive_hours:
        return _window_from_run(run)
    return None


def _window_from_run(run: list[HourPoint]) -> FavorableWindow:
    temps = [h.temp_c for h in run if h.temp_c is not None]
    precs = [h.precip_prob for h in run if h.precip_prob is not None]
    winds = [h.wind_speed_kmh for h in run if h.wind_speed_kmh is not None]
    return FavorableWindow(
        start=run[0].target_datetime,
        end=run[-1].target_datetime,
        avg_temp_c=round(sum(temps) / len(temps), 1) if temps else 0.0,
        max_precip_prob=max(precs) if precs else 0.0,
        max_wind_kmh=max(winds) if winds else 0.0,
    )


def _format_window_human(window: FavorableWindow) -> str:
    try:
        start_dt = datetime.fromisoformat(window.start)
        end_dt = datetime.fromisoformat(window.end)
        day = start_dt.strftime("%A %b %d")
        return f"{day}, {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
    except ValueError:
        return f"{window.start} to {window.end}"


def build_activity_nudge(
    activity_dates: list[date],
    as_of: date,
    hourly: list[HourPoint],
    *,
    inactivity_threshold_days: int,
    temp_min_c: float,
    temp_max_c: float,
    precip_prob_max: float,
    wind_max_kmh: float,
) -> ActivityNudgeResult:
    days_since = days_since_last_activity(activity_dates, as_of)
    inactive = is_inactive_streak(days_since, inactivity_threshold_days)

    if not inactive:
        return ActivityNudgeResult(
            days_since_last_activity=days_since,
            is_inactive=False,
            window=None,
            message=f"You logged an activity {days_since} day(s) ago — no nudge needed.",
        )

    window = find_best_outdoor_window(
        hourly,
        temp_min_c=temp_min_c,
        temp_max_c=temp_max_c,
        precip_prob_max=precip_prob_max,
        wind_max_kmh=wind_max_kmh,
    )

    streak_desc = "You've never logged an activity" if days_since is None else (
        f"You haven't logged an activity in {days_since} days"
    )

    if window is not None:
        message = (
            f"{streak_desc}. Good outdoor window coming up: {_format_window_human(window)} "
            f"(~{window.avg_temp_c}°C, up to {window.max_precip_prob:.0f}% precipitation chance, "
            f"winds up to {window.max_wind_kmh:.0f} km/h)."
        )
    else:
        message = (
            f"{streak_desc}, and no favorable outdoor window is in the forecast right now. "
            "Consider an indoor session instead."
        )

    return ActivityNudgeResult(
        days_since_last_activity=days_since,
        is_inactive=True,
        window=window,
        message=message,
    )
