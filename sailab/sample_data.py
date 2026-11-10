"""SAMPLE DATA. Made-up lake measurements for tests and demos. Nothing here was measured from a satellite.

Three made-up lakes, each with four summers of made-up areas:
  SAMPLE-STEADY     stays the same every year                      -> should score low
  SAMPLE-JUMP       the same, then grows suddenly at the very end  -> should score high
  SAMPLE-SHRINK     the same, then shrinks suddenly at the very end -> must not be flagged as growing

Everything is marked so it cannot be mistaken for real data:
  - lake codes start with "SAMPLE-" and lake names start with "SAMPLE DATA";
  - the coordinates are 0, 0 (the Gulf of Guinea, where there is no glacial lake);
  - every scene's file path starts with "sample_data/" and no picture file exists.

The numbers are the same on every run (the "random" wiggle uses a fixed seed), so tests can rely on them.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

SAMPLE_CODE_PREFIX = "SAMPLE-"
SAMPLE_NAME_PREFIX = "SAMPLE DATA"
SAMPLE_PATH_PREFIX = "sample_data/"

YEARS = (2023, 2024, 2025, 2026)
# Summer only, like the real lakes (they are frozen or snowed in for the rest of the year).
# The area rises a little through the melt season and falls again: a share of the lake's base area.
SEASON_SHARE = {6: 0.96, 7: 1.00, 8: 1.02, 9: 0.99}
DAYS = (5, 15, 25)
WIGGLE_SHARE = 0.005        # each value moves up or down by at most half a percent
CHANGE_SHARE = 0.25         # the sudden change of the JUMP and SHRINK lakes: a quarter of the area
CHANGED_VALUES = 3          # how many of the newest values carry the sudden change


@dataclass(frozen=True)
class SampleLake:
    code: str
    name: str
    base_ha: float
    final_change_share: float     # 0 = no change; +0.25 = the last values are 25% larger; -0.25 = 25% smaller


SAMPLE_LAKES = (
    SampleLake(SAMPLE_CODE_PREFIX + "STEADY", SAMPLE_NAME_PREFIX + ": steady lake (not real)", 200.0, 0.0),
    SampleLake(SAMPLE_CODE_PREFIX + "JUMP", SAMPLE_NAME_PREFIX + ": jumping lake (not real)", 120.0, +CHANGE_SHARE),
    SampleLake(SAMPLE_CODE_PREFIX + "SHRINK", SAMPLE_NAME_PREFIX + ": shrinking lake (not real)", 80.0, -CHANGE_SHARE),
)


@dataclass(frozen=True)
class SampleMeasurement:
    lake_code: str
    observed_on: date
    extent_ha: float


def sample_series(lake: SampleLake) -> list[SampleMeasurement]:
    """The made-up area series of one sample lake, oldest first.

    Each value = base area x the season's share x (1 + a tiny wiggle). The wiggle comes from a random
    number generator seeded with the lake's code, so the series is identical every time. For the JUMP and
    SHRINK lakes the newest CHANGED_VALUES values are then multiplied by (1 + final_change_share).
    """
    rng = random.Random(lake.code)   # fixed seed: same numbers on every run and every machine
    series = [
        SampleMeasurement(lake.code, date(year, month, day),
                          lake.base_ha * SEASON_SHARE[month] * (1 + rng.uniform(-WIGGLE_SHARE, WIGGLE_SHARE)))
        for year in YEARS for month in sorted(SEASON_SHARE) for day in DAYS
    ]
    if lake.final_change_share:
        cut = len(series) - CHANGED_VALUES
        series = series[:cut] + [
            SampleMeasurement(m.lake_code, m.observed_on, m.extent_ha * (1 + lake.final_change_share))
            for m in series[cut:]
        ]
    return [SampleMeasurement(m.lake_code, m.observed_on, round(m.extent_ha, 2)) for m in series]


def is_sample_code(code: str) -> bool:
    return code.startswith(SAMPLE_CODE_PREFIX)
