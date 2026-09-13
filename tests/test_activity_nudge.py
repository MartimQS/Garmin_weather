from datetime import date

from advisor.analyses.activity_nudge import (
    HourPoint,
    build_activity_nudge,
    days_since_last_activity,
    find_best_outdoor_window,
    is_inactive_streak,
)


def test_days_since_last_activity_none_when_no_activities():
    assert days_since_last_activity([], date(2024, 5, 10)) is None


def test_days_since_last_activity_computes_delta():
    dates = [date(2024, 5, 1), date(2024, 5, 6)]
    assert days_since_last_activity(dates, date(2024, 5, 10)) == 4


def test_is_inactive_streak_true_when_never_active():
    assert is_inactive_streak(None, threshold_days=3) is True


def test_is_inactive_streak_boundary():
    assert is_inactive_streak(3, threshold_days=3) is True
    assert is_inactive_streak(2, threshold_days=3) is False


def _hour(dt, temp=18.0, precip=10.0, wind=10.0):
    return HourPoint(target_datetime=dt, temp_c=temp, precip_prob=precip, wind_speed_kmh=wind)


def test_find_best_outdoor_window_finds_contiguous_block():
    hours = [
        _hour("2024-05-01T08:00", temp=5.0),  # too cold
        _hour("2024-05-01T09:00", temp=18.0),
        _hour("2024-05-01T10:00", temp=19.0),
        _hour("2024-05-01T11:00", temp=40.0),  # too hot
    ]
    window = find_best_outdoor_window(
        hours, temp_min_c=10, temp_max_c=27, precip_prob_max=30, wind_max_kmh=25, min_consecutive_hours=2
    )
    assert window is not None
    assert window.start == "2024-05-01T09:00"
    assert window.end == "2024-05-01T10:00"


def test_find_best_outdoor_window_returns_none_when_no_block_long_enough():
    hours = [_hour("2024-05-01T09:00", temp=18.0)]
    window = find_best_outdoor_window(
        hours, temp_min_c=10, temp_max_c=27, precip_prob_max=30, wind_max_kmh=25, min_consecutive_hours=2
    )
    assert window is None


def test_find_best_outdoor_window_rejects_missing_data():
    hours = [
        HourPoint("2024-05-01T09:00", None, 10.0, 10.0),
        HourPoint("2024-05-01T10:00", 18.0, None, 10.0),
    ]
    window = find_best_outdoor_window(
        hours, temp_min_c=10, temp_max_c=27, precip_prob_max=30, wind_max_kmh=25, min_consecutive_hours=2
    )
    assert window is None


def test_build_activity_nudge_no_nudge_when_active():
    result = build_activity_nudge(
        activity_dates=[date(2024, 5, 9)],
        as_of=date(2024, 5, 10),
        hourly=[],
        inactivity_threshold_days=3,
        temp_min_c=10,
        temp_max_c=27,
        precip_prob_max=30,
        wind_max_kmh=25,
    )
    assert result.is_inactive is False
    assert "no nudge needed" in result.message.lower()


def test_build_activity_nudge_recommends_window_when_inactive():
    hours = [_hour(f"2024-05-10T{h:02d}:00") for h in range(8, 12)]
    result = build_activity_nudge(
        activity_dates=[date(2024, 5, 1)],
        as_of=date(2024, 5, 10),
        hourly=hours,
        inactivity_threshold_days=3,
        temp_min_c=10,
        temp_max_c=27,
        precip_prob_max=30,
        wind_max_kmh=25,
    )
    assert result.is_inactive is True
    assert result.window is not None
    assert "good outdoor window" in result.message.lower()


def test_build_activity_nudge_no_window_available():
    hours = [_hour("2024-05-10T08:00", temp=40.0)]
    result = build_activity_nudge(
        activity_dates=[],
        as_of=date(2024, 5, 10),
        hourly=hours,
        inactivity_threshold_days=3,
        temp_min_c=10,
        temp_max_c=27,
        precip_prob_max=30,
        wind_max_kmh=25,
    )
    assert result.is_inactive is True
    assert result.window is None
    assert "no favorable outdoor window" in result.message.lower()
