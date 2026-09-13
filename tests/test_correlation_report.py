from advisor.analyses.correlation_report import (
    build_correlation_report,
    notable_correlations,
    paired_values,
    pearson_correlation,
)


def test_pearson_correlation_perfect_positive():
    xs = [1, 2, 3, 4, 5]
    ys = [2, 4, 6, 8, 10]
    assert pearson_correlation(xs, ys) == 1.0


def test_pearson_correlation_perfect_negative():
    xs = [1, 2, 3, 4, 5]
    ys = [10, 8, 6, 4, 2]
    assert pearson_correlation(xs, ys) == -1.0


def test_pearson_correlation_no_variance_returns_none():
    xs = [5, 5, 5, 5]
    ys = [1, 2, 3, 4]
    assert pearson_correlation(xs, ys) is None


def test_pearson_correlation_too_few_points_returns_none():
    assert pearson_correlation([1], [2]) is None


def test_paired_values_skips_rows_with_missing_data():
    rows = [
        {"pressure_hpa": 1000, "sleep_score": 80},
        {"pressure_hpa": None, "sleep_score": 70},
        {"pressure_hpa": 1010, "sleep_score": None},
        {"pressure_hpa": 1020, "sleep_score": 60},
    ]
    xs, ys = paired_values(rows, "pressure_hpa", "sleep_score")
    assert xs == [1000, 1020]
    assert ys == [80, 60]


def test_build_correlation_report_marks_insufficient_data():
    rows = [{"pressure_hpa": 1000 + i, "sleep_score": 80 - i} for i in range(3)]
    results = build_correlation_report(rows, min_pairs=8)
    pressure_sleep = next(r for r in results if r.env_var == "pressure_hpa" and r.health_var == "sleep_score")
    assert pressure_sleep.r is None
    assert pressure_sleep.strength == "insufficient data"
    assert pressure_sleep.n == 3


def test_build_correlation_report_computes_with_enough_pairs():
    rows = [{"pressure_hpa": 1000 + i, "sleep_score": 80 - i * 2} for i in range(10)]
    results = build_correlation_report(rows, min_pairs=8)
    pressure_sleep = next(r for r in results if r.env_var == "pressure_hpa" and r.health_var == "sleep_score")
    assert pressure_sleep.r is not None
    assert pressure_sleep.r < -0.9
    assert "strong" in pressure_sleep.strength


def test_notable_correlations_filters_by_threshold():
    rows_strong = [{"pressure_hpa": 1000 + i, "sleep_score": 80 - i * 2} for i in range(10)]
    results = build_correlation_report(rows_strong, min_pairs=8)
    notable = notable_correlations(results, min_abs_r=0.3)
    assert any(r.env_var == "pressure_hpa" and r.health_var == "sleep_score" for r in notable)
    # unrelated pairing (temp/aqi/hrv/rhr all missing) shouldn't appear
    assert all(r.r is not None and abs(r.r) >= 0.3 for r in notable)
