"""Client for the free, keyless Open-Meteo Weather and Air Quality APIs."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger("advisor.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _get_with_retry(url: str, params: dict, *, attempts: int = 4, base_delay: float = 2.0) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Open-Meteo request failed (attempt %d/%d) %s: %s",
                attempt,
                attempts,
                url,
                exc,
            )
            if attempt < attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


@dataclass
class DailyForecast:
    target_date: str
    temp_max_c: float | None
    temp_min_c: float | None
    precip_prob_max: float | None
    wind_speed_max_kmh: float | None


@dataclass
class HourlyForecast:
    target_datetime: str
    temp_c: float | None
    precip_prob: float | None
    wind_speed_kmh: float | None


@dataclass
class DailyAirQuality:
    date: str
    european_aqi: float | None
    pm2_5: float | None
    pm10: float | None


class WeatherClient:
    def __init__(self, latitude: float, longitude: float, timezone: str = "auto") -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone

    def fetch_daily_forecast(self, days: int = 7) -> list[DailyForecast]:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "forecast_days": days,
            "timezone": self.timezone,
        }
        data = _get_with_retry(FORECAST_URL, params)
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        results = []
        for i, d in enumerate(dates):
            results.append(
                DailyForecast(
                    target_date=d,
                    temp_max_c=_at(daily.get("temperature_2m_max"), i),
                    temp_min_c=_at(daily.get("temperature_2m_min"), i),
                    precip_prob_max=_at(daily.get("precipitation_probability_max"), i),
                    wind_speed_max_kmh=_at(daily.get("wind_speed_10m_max"), i),
                )
            )
        return results

    def fetch_hourly_forecast(self, hours: int = 48) -> list[HourlyForecast]:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
            "forecast_hours": hours,
            "timezone": self.timezone,
        }
        data = _get_with_retry(FORECAST_URL, params)
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        results = []
        for i, t in enumerate(times):
            results.append(
                HourlyForecast(
                    target_datetime=t,
                    temp_c=_at(hourly.get("temperature_2m"), i),
                    precip_prob=_at(hourly.get("precipitation_probability"), i),
                    wind_speed_kmh=_at(hourly.get("wind_speed_10m"), i),
                )
            )
        return results

    def fetch_daily_air_quality(self, days: int = 7, past_days: int = 0) -> list[DailyAirQuality]:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "european_aqi,pm2_5,pm10",
            "forecast_days": days,
            "timezone": self.timezone,
        }
        if past_days:
            params["past_days"] = past_days
        data = _get_with_retry(AIR_QUALITY_URL, params)
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        by_date: dict[str, list[dict[str, Any]]] = {}
        for i, t in enumerate(times):
            d = t[:10]
            by_date.setdefault(d, []).append(
                {
                    "aqi": _at(hourly.get("european_aqi"), i),
                    "pm2_5": _at(hourly.get("pm2_5"), i),
                    "pm10": _at(hourly.get("pm10"), i),
                }
            )
        results = []
        for d, rows in sorted(by_date.items()):
            aqis = [r["aqi"] for r in rows if r["aqi"] is not None]
            pm25s = [r["pm2_5"] for r in rows if r["pm2_5"] is not None]
            pm10s = [r["pm10"] for r in rows if r["pm10"] is not None]
            results.append(
                DailyAirQuality(
                    date=d,
                    european_aqi=round(sum(aqis) / len(aqis), 1) if aqis else None,
                    pm2_5=round(sum(pm25s) / len(pm25s), 1) if pm25s else None,
                    pm10=round(sum(pm10s) / len(pm10s), 1) if pm10s else None,
                )
            )
        return results

    def fetch_observed_daily(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Historical daily pressure/temperature for the correlation report.

        Uses the archive API which covers past dates (unlike the forecast
        API, which only looks forward a few days once dates have passed).
        """
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_mean,surface_pressure_mean",
            "timezone": self.timezone,
        }
        data = _get_with_retry(ARCHIVE_URL, params)
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        results = []
        for i, d in enumerate(dates):
            results.append(
                {
                    "date": d,
                    "temp_mean_c": _at(daily.get("temperature_2m_mean"), i),
                    "pressure_hpa": _at(daily.get("surface_pressure_mean"), i),
                }
            )
        return results


def _at(seq: list | None, i: int) -> Any:
    if not seq or i >= len(seq):
        return None
    return seq[i]
