"""Seasonal baseline and anomaly fallback (FR-14, FR-18), used when no trained risk model exists.

A lake needs at least `min_history_months` of monitoring before any baseline
means anything; before that the result is "insufficient history" rather than a
score that would just be noise (Test Plan, TC-BAS-03).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from statistics import mean, stdev


@dataclass(frozen=True)
class ExtentRecord:
    """One past measurement of a lake's extent, the building block of ExtentSeries."""
    observed_on: date
    extent_ha: float


@dataclass(frozen=True)
class BaselineResult:
    status: str                      # "ok" or "insufficient history"
    baseline_ha: float | None = None
    deviation_ha: float | None = None
    deviation_score: float | None = None


def months_of_history(history: list[ExtentRecord], as_of: date) -> int:
    """Whole calendar months between the earliest record and `as_of`."""
    if not history:
        return 0
    earliest = min(record.observed_on for record in history)
    return (as_of.year - earliest.year) * 12 + (as_of.month - earliest.month)


def score_against_seasonal_baseline(
    history: list[ExtentRecord],
    as_of: date,
    new_extent_ha: float,
    min_history_months: int = 12,
) -> BaselineResult:
    """FR-14 / FR-18: the seasonal baseline and deviation score, or "insufficient history".

    The baseline is the mean of the lake's own extent in the same calendar
    month in earlier years; the spread is the sample standard deviation of
    those same values (statistics.stdev, which uses n-1 in the denominator).
    """
    if months_of_history(history, as_of) < min_history_months:
        return BaselineResult(status="insufficient history")

    same_month_values = [r.extent_ha for r in history if r.observed_on.month == as_of.month]
    if len(same_month_values) < 2:
        # Not enough same-month observations to compute a spread; treat the same as insufficient history.
        return BaselineResult(status="insufficient history")

    baseline_ha = mean(same_month_values)
    spread_ha = stdev(same_month_values)
    deviation_ha = new_extent_ha - baseline_ha
    deviation_score = deviation_ha / spread_ha if spread_ha else None

    return BaselineResult(
        status="ok",
        baseline_ha=baseline_ha,
        deviation_ha=deviation_ha,
        deviation_score=deviation_score,
    )
