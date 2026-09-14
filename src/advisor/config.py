"""Central configuration loaded from environment variables.

Every credential and location value comes from the environment so nothing
sensitive is ever hardcoded. See README.md for the full list of variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _get_env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and (value is None or value.strip() == ""):
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _get_float_env(name: str, *, required: bool = True, default: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        if required and default is None:
            raise ConfigError(f"Missing required environment variable: {name}")
        return default if default is not None else 0.0
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class GarminConfig:
    username: str
    password: str


@dataclass(frozen=True)
class LocationConfig:
    latitude: float
    longitude: float
    timezone: str = "auto"


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    from_address: str
    to_address: str
    use_tls: bool = True


@dataclass(frozen=True)
class ThresholdConfig:
    """Tunable business-logic thresholds. All overridable via env vars."""

    inactivity_days: int = field(default=3)
    outdoor_temp_min_c: float = field(default=10.0)
    outdoor_temp_max_c: float = field(default=27.0)
    outdoor_precip_prob_max: float = field(default=30.0)
    outdoor_wind_max_kmh: float = field(default=25.0)
    forecast_window_hours: int = field(default=48)
    aqi_good_max: float = field(default=50.0)
    aqi_moderate_max: float = field(default=100.0)


@dataclass(frozen=True)
class AppConfig:
    garmin: GarminConfig
    location: LocationConfig
    email: EmailConfig
    thresholds: ThresholdConfig
    db_path: str


def load_config(*, require_email: bool = True, require_garmin: bool = True) -> AppConfig:
    """Load and validate configuration from environment variables.

    Args:
        require_email: set False for commands that don't send email (e.g. ingest-only).
        require_garmin: set False for commands that don't touch Garmin (e.g. weather-only).
    """
    garmin = GarminConfig(
        username=_get_env("GARMIN_USERNAME", required=require_garmin, default="") or "",
        password=_get_env("GARMIN_PASSWORD", required=require_garmin, default="") or "",
    )

    location = LocationConfig(
        latitude=_get_float_env("LOCATION_LATITUDE"),
        longitude=_get_float_env("LOCATION_LONGITUDE"),
        timezone=_get_env("LOCATION_TIMEZONE", required=False, default="auto") or "auto",
    )

    email = EmailConfig(
        smtp_host=_get_env("SMTP_HOST", required=False, default="smtp.gmail.com") or "smtp.gmail.com",
        smtp_port=_get_int_env("SMTP_PORT", 587),
        smtp_username=_get_env("SMTP_USERNAME", required=require_email, default="") or "",
        smtp_password=_get_env("SMTP_PASSWORD", required=require_email, default="") or "",
        from_address=_get_env("EMAIL_FROM", required=require_email, default="") or "",
        to_address=_get_env("EMAIL_TO", required=require_email, default="") or "",
        use_tls=_get_env("SMTP_USE_TLS", required=False, default="true") == "true",
    )

    thresholds = ThresholdConfig(
        inactivity_days=_get_int_env("THRESHOLD_INACTIVITY_DAYS", 3),
        outdoor_temp_min_c=_get_float_env("THRESHOLD_OUTDOOR_TEMP_MIN_C", required=False, default=10.0),
        outdoor_temp_max_c=_get_float_env("THRESHOLD_OUTDOOR_TEMP_MAX_C", required=False, default=27.0),
        outdoor_precip_prob_max=_get_float_env("THRESHOLD_OUTDOOR_PRECIP_PROB_MAX", required=False, default=30.0),
        outdoor_wind_max_kmh=_get_float_env("THRESHOLD_OUTDOOR_WIND_MAX_KMH", required=False, default=25.0),
        forecast_window_hours=_get_int_env("THRESHOLD_FORECAST_WINDOW_HOURS", 48),
        aqi_good_max=_get_float_env("THRESHOLD_AQI_GOOD_MAX", required=False, default=50.0),
        aqi_moderate_max=_get_float_env("THRESHOLD_AQI_MODERATE_MAX", required=False, default=100.0),
    )

    db_path = _get_env("DB_PATH", required=False, default="data/advisor.db") or "data/advisor.db"

    return AppConfig(
        garmin=garmin,
        location=location,
        email=email,
        thresholds=thresholds,
        db_path=db_path,
    )
