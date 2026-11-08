"""Tests for sailab.risk, matching the Test Case Register."""
from datetime import date
import pytest
from sailab.risk import ExtentRecord, score_against_seasonal_baseline


def test_TC_BAS_01_seasonal_baseline_and_deviation_score():
    """Given July extents of 40, 42 and 44 ha in three earlier years, and a new July value of 50 ha,
    the baseline is 42.0 ha, the standard deviation is 2.0, and the deviation score is 4.0."""
    history = [
        ExtentRecord(observed_on=date(2023, 7, 15), extent_ha=40.0),
        ExtentRecord(observed_on=date(2024, 7, 15), extent_ha=42.0),
        ExtentRecord(observed_on=date(2025, 7, 15), extent_ha=44.0),
    ]
    as_of = date(2026, 7, 15)

    result = score_against_seasonal_baseline(history, as_of, new_extent_ha=50.0)

    assert result.status == "ok"
    assert result.baseline_ha == pytest.approx(42.0)
    assert result.deviation_ha == pytest.approx(8.0)
    assert result.deviation_score == pytest.approx(4.0)


def test_TC_BAS_03_insufficient_history_gives_no_score():
    """Given a lake monitored for only 4 months, the result is "insufficient history" and no score is produced."""
    history = [
        ExtentRecord(observed_on=date(2026, 3, 1), extent_ha=30.0),
        ExtentRecord(observed_on=date(2026, 4, 1), extent_ha=31.0),
    ]
    as_of = date(2026, 7, 1)   # 4 months after the earliest record, short of the 12-month minimum

    result = score_against_seasonal_baseline(history, as_of, new_extent_ha=33.0)

    assert result.status == "insufficient history"
    assert result.baseline_ha is None
    assert result.deviation_score is None
