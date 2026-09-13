from advisor.analyses.readiness_score import Baseline, classify_readiness, compute_readiness_score

NEUTRAL_BASELINE = Baseline(hrv_mean=None, hrv_std=None, resting_hr_mean=None, resting_hr_std=None)
NORMAL_BASELINE = Baseline(hrv_mean=50.0, hrv_std=5.0, resting_hr_mean=55.0, resting_hr_std=4.0)


def test_classify_readiness_bands():
    assert classify_readiness(90)[0] == "High"
    assert classify_readiness(75)[0] == "High"
    assert classify_readiness(60)[0] == "Moderate"
    assert classify_readiness(40)[0] == "Low"
    assert classify_readiness(10)[0] == "Very Low"


def test_compute_readiness_score_all_missing_returns_unknown():
    result = compute_readiness_score(
        sleep_score=None, hrv=None, resting_hr=None, body_battery_max=None, baseline=NEUTRAL_BASELINE
    )
    assert result.overall_score is None
    assert result.label == "Unknown"


def test_compute_readiness_score_uses_available_metrics_only():
    result = compute_readiness_score(
        sleep_score=80, hrv=None, resting_hr=None, body_battery_max=None, baseline=NEUTRAL_BASELINE
    )
    assert result.overall_score == 80.0
    assert set(result.missing_metrics) == {"hrv", "resting_hr", "body_battery"}


def test_compute_readiness_score_good_night_scores_high():
    result = compute_readiness_score(
        sleep_score=90, hrv=60.0, resting_hr=48.0, body_battery_max=95, baseline=NORMAL_BASELINE
    )
    assert result.overall_score is not None
    assert result.overall_score > 75
    assert result.label == "High"


def test_compute_readiness_score_bad_night_scores_low():
    result = compute_readiness_score(
        sleep_score=30, hrv=35.0, resting_hr=68.0, body_battery_max=20, baseline=NORMAL_BASELINE
    )
    assert result.overall_score is not None
    assert result.overall_score < 40


def test_hrv_above_baseline_increases_score_vs_at_baseline():
    at_baseline = compute_readiness_score(
        sleep_score=70, hrv=50.0, resting_hr=55.0, body_battery_max=70, baseline=NORMAL_BASELINE
    )
    above_baseline = compute_readiness_score(
        sleep_score=70, hrv=65.0, resting_hr=55.0, body_battery_max=70, baseline=NORMAL_BASELINE
    )
    assert above_baseline.overall_score > at_baseline.overall_score


def test_resting_hr_above_baseline_decreases_score():
    at_baseline = compute_readiness_score(
        sleep_score=70, hrv=50.0, resting_hr=55.0, body_battery_max=70, baseline=NORMAL_BASELINE
    )
    elevated_rhr = compute_readiness_score(
        sleep_score=70, hrv=50.0, resting_hr=70.0, body_battery_max=70, baseline=NORMAL_BASELINE
    )
    assert elevated_rhr.overall_score < at_baseline.overall_score
