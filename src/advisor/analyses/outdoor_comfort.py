"""Outdoor Comfort Ranking: rank the next 7 days by outdoor-activity
friendliness, combining temperature, precipitation probability, wind, and
air quality.

Weighting is a documented judgment call (see README "Assumptions"):
temperature 35%, precipitation 30%, wind 15%, air quality 20%.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

WEIGHTS = {
    "temperature": 0.35,
    "precipitation": 0.30,
    "wind": 0.15,
    "air_quality": 0.20,
}


@dataclass
class DayForecastInput:
    date: str
    temp_max_c: Optional[float]
    temp_min_c: Optional[float]
    precip_prob_max: Optional[float]
    wind_speed_max_kmh: Optional[float]
    european_aqi: Optional[float]


@dataclass
class ComfortRanking:
    date: str
    comfort_score: Optional[float]
    label: str
    components: dict[str, Optional[float]]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _temperature_score(temp_max: Optional[float], temp_min: Optional[float], ideal_min: float, ideal_max: float) -> Optional[float]:
    if temp_max is None or temp_min is None:
        return None
    mean_temp = (temp_max + temp_min) / 2
    ideal_mid = (ideal_min + ideal_max) / 2
    half_range = max((ideal_max - ideal_min) / 2, 1e-6)
    distance = abs(mean_temp - ideal_mid)
    # Full marks within the ideal range; linear falloff of ~5 points per
    # degree beyond it.
    if distance <= half_range:
        return 100.0
    overage = distance - half_range
    return _clamp(100 - overage * 5)


def _precip_score(precip_prob_max: Optional[float]) -> Optional[float]:
    if precip_prob_max is None:
        return None
    return _clamp(100 - precip_prob_max)


def _wind_score(wind_speed_max_kmh: Optional[float], wind_max_kmh: float) -> Optional[float]:
    if wind_speed_max_kmh is None:
        return None
    if wind_speed_max_kmh <= wind_max_kmh:
        return _clamp(100 - (wind_speed_max_kmh / max(wind_max_kmh, 1e-6)) * 30)
    overage = wind_speed_max_kmh - wind_max_kmh
    return _clamp(70 - overage * 3)


def _aqi_score(european_aqi: Optional[float], aqi_good_max: float, aqi_moderate_max: float) -> Optional[float]:
    if european_aqi is None:
        return None
    if european_aqi <= aqi_good_max:
        return _clamp(100 - (european_aqi / max(aqi_good_max, 1e-6)) * 20)
    if european_aqi <= aqi_moderate_max:
        span = max(aqi_moderate_max - aqi_good_max, 1e-6)
        return _clamp(80 - ((european_aqi - aqi_good_max) / span) * 40)
    return _clamp(40 - (european_aqi - aqi_moderate_max) * 0.3)


def score_day(
    day: DayForecastInput,
    *,
    ideal_temp_min_c: float,
    ideal_temp_max_c: float,
    wind_max_kmh: float,
    aqi_good_max: float,
    aqi_moderate_max: float,
) -> ComfortRanking:
    components = {
        "temperature": _temperature_score(day.temp_max_c, day.temp_min_c, ideal_temp_min_c, ideal_temp_max_c),
        "precipitation": _precip_score(day.precip_prob_max),
        "wind": _wind_score(day.wind_speed_max_kmh, wind_max_kmh),
        "air_quality": _aqi_score(day.european_aqi, aqi_good_max, aqi_moderate_max),
    }
    available = {name: val for name, val in components.items() if val is not None}
    if not available:
        return ComfortRanking(date=day.date, comfort_score=None, label="Unknown", components=components)

    total_weight = sum(WEIGHTS[name] for name in available)
    weighted_sum = sum(WEIGHTS[name] * val for name, val in available.items())
    score = round(weighted_sum / total_weight, 1)
    return ComfortRanking(date=day.date, comfort_score=score, label=_label_for(score), components=components)


def _label_for(score: float) -> str:
    if score >= 80:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Fair"
    return "Poor"


def rank_outdoor_days(
    days: list[DayForecastInput],
    *,
    ideal_temp_min_c: float,
    ideal_temp_max_c: float,
    wind_max_kmh: float,
    aqi_good_max: float,
    aqi_moderate_max: float,
) -> list[ComfortRanking]:
    scored = [
        score_day(
            d,
            ideal_temp_min_c=ideal_temp_min_c,
            ideal_temp_max_c=ideal_temp_max_c,
            wind_max_kmh=wind_max_kmh,
            aqi_good_max=aqi_good_max,
            aqi_moderate_max=aqi_moderate_max,
        )
        for d in days
    ]
    return sorted(scored, key=lambda r: (r.comfort_score is None, -(r.comfort_score or 0)))
