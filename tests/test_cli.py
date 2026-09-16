from datetime import date, datetime, timedelta

from advisor.cli import _hourly_forecast_from_db
from advisor.db import get_connection, upsert


def test_hourly_forecast_from_db_excludes_stale_past_days(tmp_path):
    """Regression test: rows from earlier ingestion runs (e.g. two days ago)
    must not leak into the window search, or a stale-but-suitable past
    window can outrank today's real forecast (see build_activity_nudge)."""
    db_path = str(tmp_path / "test.db")
    today = date(2026, 9, 16)
    stale_day = today - timedelta(days=2)  # e.g. the 14th
    with get_connection(db_path) as conn:
        upsert(
            conn,
            "weather_hourly_forecast",
            ["target_datetime"],
            {
                "target_datetime": f"{stale_day.isoformat()}T10:00",
                "temp_c": 20.0,
                "precip_prob": 5.0,
                "wind_speed_kmh": 10.0,
                "fetched_at": "x",
            },
        )
        upsert(
            conn,
            "weather_hourly_forecast",
            ["target_datetime"],
            {
                "target_datetime": f"{today.isoformat()}T14:00",
                "temp_c": 18.0,
                "precip_prob": 5.0,
                "wind_speed_kmh": 8.0,
                "fetched_at": "x",
            },
        )
        hours = _hourly_forecast_from_db(conn, today)

    dates_returned = {h.target_datetime[:10] for h in hours}
    assert stale_day.isoformat() not in dates_returned
    assert today.isoformat() in dates_returned


def test_hourly_forecast_from_db_includes_future_days(tmp_path):
    db_path = str(tmp_path / "test.db")
    today = date(2026, 9, 16)
    with get_connection(db_path) as conn:
        upsert(
            conn,
            "weather_hourly_forecast",
            ["target_datetime"],
            {
                "target_datetime": f"{(today + timedelta(days=1)).isoformat()}T09:00",
                "temp_c": 19.0,
                "precip_prob": 10.0,
                "wind_speed_kmh": 12.0,
                "fetched_at": "x",
            },
        )
        hours = _hourly_forecast_from_db(conn, today)
    assert len(hours) == 1
