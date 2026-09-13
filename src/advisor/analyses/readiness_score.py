"""Readiness Score: a composite daily score from sleep, HRV, resting heart
rate trend, and body battery, with a plain-language training recommendation.

Weighting is a documented judgment call (see README "Assumptions"):
sleep 35%, HRV 25%, resting HR trend 20%, body battery 20%. Each
component is normalized to 0-100 before weighting so no single metric's
raw scale dominates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

WEIGHTS = {
    "sleep": 0.35,
    "hrv": 0.25,
    "resting_hr": 0.20,
    "body_battery": 0.20,
}


@dataclass
class Baseline:
    hrv_mean: Optional[float]
    hrv_std: Optional[float]
    resting_hr_mean: Optional[float]
    resting_hr_std: Optional[float]


@dataclass
class ReadinessResult:
    overall_score: Optional[float]
    label: str
    recommendation: str
    components: dict[str, Optional[float]]
    missing_metrics: list[str]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _z_score_component(value: Optional[float], mean: Optional[float], std: Optional[float], *, higher_is_better: bool) -> Optional[float]:
    if value is None or mean is None or std is None or std == 0:
        return None
    z = (value - mean) / std
    if not higher_is_better:
        z = -z
    return _clamp(50 + z * 15)


def compute_readiness_score(
    *,
    sleep_score: Optional[float],
    hrv: Optional[float],
    resting_hr: Optional[float],
    body_battery_max: Optional[float],
    baseline: Baseline,
) -> ReadinessResult:
    components: dict[str, Optional[float]] = {
        "sleep": _clamp(sleep_score) if sleep_score is not None else None,
        "hrv": _z_score_component(hrv, baseline.hrv_mean, baseline.hrv_std, higher_is_better=True),
        "resting_hr": _z_score_component(
            resting_hr, baseline.resting_hr_mean, baseline.resting_hr_std, higher_is_better=False
        ),
        "body_battery": _clamp(body_battery_max) if body_battery_max is not None else None,
    }

    missing = [name for name, val in components.items() if val is None]
    available = {name: val for name, val in components.items() if val is not None}

    if not available:
        return ReadinessResult(
            overall_score=None,
            label="Unknown",
            recommendation="Not enough data to compute a readiness score today.",
            components=components,
            missing_metrics=missing,
        )

    total_weight = sum(WEIGHTS[name] for name in available)
    weighted_sum = sum(WEIGHTS[name] * val for name, val in available.items())
    overall = round(weighted_sum / total_weight, 1)

    label, recommendation = classify_readiness(overall)
    return ReadinessResult(
        overall_score=overall,
        label=label,
        recommendation=recommendation,
        components=components,
        missing_metrics=missing,
    )


def classify_readiness(score: float) -> tuple[str, str]:
    if score >= 75:
        return "High", "Hard day — you're well recovered, good day for intense training."
    if score >= 55:
        return "Moderate", "Moderate day — normal training load is fine."
    if score >= 35:
        return "Low", "Easy day — favor light activity or active recovery."
    return "Very Low", "Rest day — prioritize recovery, sleep, and hydration."
