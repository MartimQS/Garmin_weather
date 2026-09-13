"""Monthly Correlation Report: look for relationships between
environmental variables (pressure, temperature, air quality) and health
metrics (sleep score, HRV, resting HR) over the trailing 30 days.

Uses a manual Pearson correlation implementation (no numpy/scipy
dependency) so it is trivial to unit test and keeps the runtime footprint
small.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

ENV_VARS = ["pressure_hpa", "temp_mean_c", "european_aqi"]
HEALTH_VARS = ["sleep_score", "hrv", "resting_hr"]

MIN_PAIRS = 8


@dataclass
class CorrelationResult:
    env_var: str
    health_var: str
    r: Optional[float]
    n: int
    strength: str


def pearson_correlation(xs: list[float], ys: list[float]) -> Optional[float]:
    """Standard Pearson correlation coefficient. Returns ``None`` when
    fewer than 2 points or when either series has zero variance."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return None
    r = cov / denom
    return max(-1.0, min(1.0, r))


def _strength_label(r: Optional[float]) -> str:
    if r is None:
        return "insufficient data"
    abs_r = abs(r)
    if abs_r < 0.1:
        direction = "negligible"
    elif abs_r < 0.3:
        direction = "weak"
    elif abs_r < 0.5:
        direction = "moderate"
    elif abs_r < 0.7:
        direction = "strong"
    else:
        direction = "very strong"
    sign = "positive" if r >= 0 else "negative"
    return f"{direction} {sign}" if abs_r >= 0.1 else direction


def paired_values(rows: list[dict], env_var: str, health_var: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for row in rows:
        x = row.get(env_var)
        y = row.get(health_var)
        if x is not None and y is not None:
            xs.append(float(x))
            ys.append(float(y))
    return xs, ys


def build_correlation_report(
    rows: list[dict], *, min_pairs: int = MIN_PAIRS
) -> list[CorrelationResult]:
    """``rows`` is a list of per-day dicts joining environmental and health
    columns on date, e.g.::

        {"date": "2024-05-01", "pressure_hpa": 1013.2, "temp_mean_c": 18.4,
         "european_aqi": 32.0, "sleep_score": 78, "hrv": 55.0, "resting_hr": 52}

    Missing values for any column on a given day are fine — pairs are
    computed per (env_var, health_var) combination using only the days
    where both are present.
    """
    results: list[CorrelationResult] = []
    for env_var in ENV_VARS:
        for health_var in HEALTH_VARS:
            xs, ys = paired_values(rows, env_var, health_var)
            n = len(xs)
            if n < min_pairs:
                results.append(
                    CorrelationResult(env_var=env_var, health_var=health_var, r=None, n=n, strength="insufficient data")
                )
                continue
            r = pearson_correlation(xs, ys)
            results.append(
                CorrelationResult(env_var=env_var, health_var=health_var, r=r, n=n, strength=_strength_label(r))
            )
    return results


def notable_correlations(results: list[CorrelationResult], *, min_abs_r: float = 0.3) -> list[CorrelationResult]:
    """Filter to correlations worth calling out in the email (moderate or
    stronger, with enough data points)."""
    return [r for r in results if r.r is not None and abs(r.r) >= min_abs_r]
