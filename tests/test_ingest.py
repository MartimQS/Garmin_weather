from datetime import date, timedelta

import advisor.ingest as ingest_module
from advisor.config import AppConfig, EmailConfig, GarminConfig, LocationConfig, ThresholdConfig
from advisor.db import get_connection, upsert
from advisor.weather_client import DailyAirQuality, DailyForecast, HourlyForecast


def _make_config(db_path: str) -> AppConfig:
    return AppConfig(
        garmin=GarminConfig(username="u", password="p"),
        location=LocationConfig(latitude=0.0, longitude=0.0, timezone="UTC"),
        email=EmailConfig(
            smtp_host="h", smtp_port=587, smtp_username="u", smtp_password="p",
            from_address="a@example.com", to_address="b@example.com",
        ),
        thresholds=ThresholdConfig(),
        db_path=db_path,
    )


class _FakeWeatherClient:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_daily_forecast(self, days=8):
        return [DailyForecast(target_date=date.today().isoformat(), temp_max_c=20, temp_min_c=10, precip_prob_max=5, wind_speed_max_kmh=10)]

    def fetch_hourly_forecast(self, hours=48):
        today = date.today()
        return [HourlyForecast(target_datetime=f"{today.isoformat()}T12:00", temp_c=18, precip_prob=5, wind_speed_kmh=8)]

    def fetch_daily_air_quality(self, days=8, past_days=0):
        return [DailyAirQuality(date=date.today().isoformat(), european_aqi=20, pm2_5=5, pm10=10)]


def test_ingest_weather_forecast_prunes_stale_hourly_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_module, "WeatherClient", _FakeWeatherClient)
    db_path = str(tmp_path / "test.db")
    config = _make_config(db_path)
    today = date.today()
    stale_day = today - timedelta(days=2)

    with get_connection(db_path) as conn:
        upsert(
            conn,
            "weather_hourly_forecast",
            ["target_datetime"],
            {"target_datetime": f"{stale_day.isoformat()}T10:00", "temp_c": 20.0, "precip_prob": 5.0, "wind_speed_kmh": 10.0, "fetched_at": "x"},
        )

        assert ingest_module.ingest_weather_forecast(conn, config) is True

        rows = conn.execute("SELECT target_datetime FROM weather_hourly_forecast").fetchall()
        remaining = {r["target_datetime"] for r in rows}

    assert not any(dt.startswith(stale_day.isoformat()) for dt in remaining)
    assert f"{today.isoformat()}T12:00" in remaining
