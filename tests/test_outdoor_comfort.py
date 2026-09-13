from advisor.analyses.outdoor_comfort import DayForecastInput, rank_outdoor_days, score_day

COMMON_KWARGS = dict(
    ideal_temp_min_c=10,
    ideal_temp_max_c=27,
    wind_max_kmh=25,
    aqi_good_max=50,
    aqi_moderate_max=100,
)


def test_score_day_ideal_conditions_scores_high():
    day = DayForecastInput(
        date="2024-05-01", temp_max_c=20, temp_min_c=16, precip_prob_max=0, wind_speed_max_kmh=5, european_aqi=10
    )
    result = score_day(day, **COMMON_KWARGS)
    assert result.comfort_score is not None
    assert result.comfort_score >= 85
    assert result.label == "Excellent"


def test_score_day_bad_conditions_scores_low():
    day = DayForecastInput(
        date="2024-05-01", temp_max_c=38, temp_min_c=34, precip_prob_max=90, wind_speed_max_kmh=60, european_aqi=180
    )
    result = score_day(day, **COMMON_KWARGS)
    assert result.comfort_score is not None
    assert result.comfort_score < 40
    assert result.label == "Poor"


def test_score_day_missing_fields_only_uses_available_components():
    day = DayForecastInput(
        date="2024-05-01", temp_max_c=None, temp_min_c=None, precip_prob_max=5, wind_speed_max_kmh=None, european_aqi=None
    )
    result = score_day(day, **COMMON_KWARGS)
    assert result.comfort_score is not None
    assert result.components["temperature"] is None
    assert result.components["precipitation"] is not None


def test_score_day_all_missing_returns_unknown():
    day = DayForecastInput(date="2024-05-01", temp_max_c=None, temp_min_c=None, precip_prob_max=None, wind_speed_max_kmh=None, european_aqi=None)
    result = score_day(day, **COMMON_KWARGS)
    assert result.comfort_score is None
    assert result.label == "Unknown"


def test_rank_outdoor_days_sorts_descending_by_score():
    good = DayForecastInput("2024-05-01", 20, 16, 0, 5, 10)
    bad = DayForecastInput("2024-05-02", 38, 34, 90, 60, 180)
    mediocre = DayForecastInput("2024-05-03", 30, 25, 40, 20, 60)
    ranked = rank_outdoor_days([bad, good, mediocre], **COMMON_KWARGS)
    assert [r.date for r in ranked] == ["2024-05-01", "2024-05-03", "2024-05-02"]


def test_rank_outdoor_days_puts_unknown_last():
    good = DayForecastInput("2024-05-01", 20, 16, 0, 5, 10)
    unknown = DayForecastInput("2024-05-02", None, None, None, None, None)
    ranked = rank_outdoor_days([unknown, good], **COMMON_KWARGS)
    assert ranked[0].date == "2024-05-01"
    assert ranked[-1].date == "2024-05-02"
