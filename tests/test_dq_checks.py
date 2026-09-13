from datetime import date

from advisor.dq_checks import check_freshness, check_not_null, check_ranges


def test_check_freshness_passes_when_recent():
    result = check_freshness(date(2024, 5, 9), date(2024, 5, 10), max_staleness_days=2)
    assert result.passed is True


def test_check_freshness_fails_when_stale():
    result = check_freshness(date(2024, 5, 1), date(2024, 5, 10), max_staleness_days=2)
    assert result.passed is False


def test_check_freshness_fails_when_no_data():
    result = check_freshness(None, date(2024, 5, 10))
    assert result.passed is False


def test_check_not_null_passes_with_all_critical_fields():
    row = {"date": "2024-05-10", "steps": 5000, "sleep_score": 80, "resting_hr": 55}
    result = check_not_null(row)
    assert result.passed is True


def test_check_not_null_fails_with_missing_field():
    row = {"date": "2024-05-10", "steps": None, "sleep_score": 80, "resting_hr": 55}
    result = check_not_null(row)
    assert result.passed is False
    assert "steps" in result.message


def test_check_ranges_flags_out_of_range_value():
    row = {"date": "2024-05-10", "resting_hr": 300, "sleep_score": 80}
    results = check_ranges(row)
    rhr_result = next(r for r in results if r.name == "range:resting_hr")
    assert rhr_result.passed is False
    sleep_result = next(r for r in results if r.name == "range:sleep_score")
    assert sleep_result.passed is True


def test_check_ranges_skips_missing_fields():
    row = {"date": "2024-05-10", "resting_hr": None}
    results = check_ranges(row)
    assert results == []
