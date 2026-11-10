"""Risk score with the Extended Isolation Forest (the new method; the z-score in risk.py stays as the baseline).

What goes into the forest: NOT the lake's area. A 250 ha lake and a 100 ha lake cannot be compared by
area. Each reading is turned into two RELATIVE numbers, measured against the lake's own past only:

  level   how far the area is above or below this lake's usual area for that calendar month
          (usual = the median of earlier same-month readings; +0.25 means 25% above usual)
  change  how much the level moved since the previous reading: level now minus level then
          (0 when there is no earlier reading within RECENT_DAYS days). Using the level, not the raw
          area, matters: a lake that follows its normal summer rise and fall has change near 0.

Because both are shares of the lake's own size, readings from different lakes can share one forest.

The steps for one new reading:
  1. Work out (level, change) for the new reading, and for every earlier usable reading of every lake,
     each from the data before its own date only (never from the future).
  2. Build an Extended Isolation Forest from those earlier points plus the new point.
  3. The forest's score for the new point (0 to 1) is rescaled to 0 to 100.
  4. A reason line says in plain words what the two numbers were.

The forest only says "unusual", not which way. A lake that suddenly SHRINKS is also unusual (it may have
drained), so the direction is worked out separately and a shrinking lake is never called growing.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import date
from statistics import median

from sailab.eif import ExtendedIsolationForest, c_factor
from sailab.risk import ExtentRecord

METHOD = "extended_isolation_forest"

# Settings. The paper leaves the number of trees and the sub-sample size as inputs (Algorithm 1), so
# these are OUR choices, not values from the paper: 200 trees, and up to 256 points per tree.
N_TREES = 200
SAMPLE_SIZE = 256
# Fewer earlier points than this and no score is given: a forest built on a handful of points calls
# everything unusual. A judgement, not a calibrated value.
MIN_EARLIER_POINTS = 10
# The "usual area for the month" needs the same history the z-score needs (check F in pipeline.py).
MIN_SAME_MONTH_VALUES = 5
MIN_SAME_MONTH_YEARS = 2
RECENT_DAYS = 60            # a previous reading older than this says nothing about a sudden change
STEADY_SHARE = 0.02         # within 2% of usual counts as "about usual" (readings wobble by about this much)
FLAG_SCORE = 50.0           # a score at or above this is "flagged". A judgement, not a calibrated value.


@dataclass(frozen=True)
class Features:
    level: float                    # (area - usual) / usual
    change: float                   # level now - level of the previous reading, or 0.0 with no recent one
    usual_ha: float                 # the median of earlier same-month readings
    previous_level: float | None    # the previous reading's own level, if it was within RECENT_DAYS
    days_since_previous: int | None


@dataclass(frozen=True)
class EifResult:
    status: str                     # "ok" or "insufficient_history"
    score_0_100: float | None = None
    raw_score: float | None = None  # the forest's own score, equation (1) of the paper, 0 to 1
    usual_ha: float | None = None
    direction: str | None = None    # "above usual", "below usual" or "about usual"
    reason: str | None = None
    earlier_points: int = 0


def _level(earlier: list[ExtentRecord], observed_on: date, extent_ha: float) -> tuple[float, float] | None:
    """(level, usual area) of one reading, or None when its month has too little earlier history."""
    same_month = [r for r in earlier if r.observed_on.month == observed_on.month]
    if len(same_month) < MIN_SAME_MONTH_VALUES or len({r.observed_on.year for r in same_month}) < MIN_SAME_MONTH_YEARS:
        return None
    usual = median(r.extent_ha for r in same_month)
    return (extent_ha - usual) / usual, usual


def relative_features(earlier: list[ExtentRecord], observed_on: date, extent_ha: float) -> Features | None:
    """(level, change) of one reading against the same lake's EARLIER readings. None when the month has
    too little history to say what is usual. `earlier` must hold only readings from before observed_on."""
    now = _level(earlier, observed_on, extent_ha)
    if now is None:
        return None
    level, usual = now
    previous = max(earlier, key=lambda r: r.observed_on)
    days = (observed_on - previous.observed_on).days
    if days <= RECENT_DAYS:
        before_previous = [r for r in earlier if r.observed_on < previous.observed_on]
        then = _level(before_previous, previous.observed_on, previous.extent_ha)
        if then is not None:
            return Features(level, level - then[0], usual, then[0], days)
    return Features(level, 0.0, usual, None, None)


def features_of_history(history: list[ExtentRecord]) -> list[Features]:
    """The features of every reading in one lake's history that has enough earlier data, oldest first.
    Each reading only sees the readings before its own date."""
    ordered = sorted(history, key=lambda r: r.observed_on)
    out = []
    for record in ordered:
        earlier = [r for r in ordered if r.observed_on < record.observed_on]
        features = relative_features(earlier, record.observed_on, record.extent_ha) if earlier else None
        if features is not None:
            out.append(features)
    return out


def to_0_100(raw_score: float, points_per_tree: int) -> float:
    """Rescale the forest's score to 0 to 100.

    0   = raw score 0.5 or less. In equation (1) a raw score of 0.5 means the point needed exactly the
          usual number of cuts c(n): an ordinary point.
    100 = the highest raw score this forest can give: alone after the very first cut in every tree,
          2 ** (-1 / c(n)).
    In between the scale is a straight line. This rescaling is our own; the paper stops at the raw score.
    """
    highest = 2.0 ** (-1.0 / c_factor(points_per_tree))
    share = (raw_score - 0.5) / (highest - 0.5)
    return round(100.0 * min(1.0, max(0.0, share)), 1)


def direction_of(level: float) -> str:
    if level > STEADY_SHARE:
        return "above usual"
    if level < -STEADY_SHARE:
        return "below usual"
    return "about usual"


def is_flagged_as_growing(result: EifResult) -> bool:
    """True only for an unusual reading that is ABOVE the lake's usual area. A shrinking lake can be very
    unusual, but it is never flagged as growing."""
    return result.status == "ok" and result.score_0_100 >= FLAG_SCORE and result.direction == "above usual"


def reason_line(features: Features, extent_ha: float, observed_on: date, score_0_100: float, earlier_points: int) -> str:
    month = observed_on.strftime("%B")
    percent = abs(features.level) * 100
    if direction_of(features.level) == "about usual":
        level_text = f"Area {extent_ha:.1f} ha is about the usual {features.usual_ha:.1f} ha for {month}"
    else:
        side = "above" if features.level > 0 else "below"
        level_text = f"Area {extent_ha:.1f} ha is {percent:.0f}% {side} the usual {features.usual_ha:.1f} ha for {month}"
    if features.previous_level is None:
        change_text = f"no earlier reading in the last {RECENT_DAYS} days to compare with"
    else:
        days = features.days_since_previous
        when = f"{days} day{'s' if days != 1 else ''} before"
        then = direction_of(features.previous_level)
        if then == "about usual":
            change_text = f"{when} it was about usual"
        else:
            change_text = f"{when} it was {abs(features.previous_level) * 100:.0f}% {then.split()[0]} usual"
    if score_0_100 >= FLAG_SCORE:
        verdict = "Unusual"
    elif score_0_100 > 0:
        verdict = "Slightly unusual"
    else:
        verdict = "Ordinary"
    return f"{level_text}; {change_text}. {verdict} compared with {earlier_points} earlier readings."


def seed_for(lake_code: str, observed_on: date) -> int:
    """A fixed seed per lake and date, so scoring the same reading again gives the same score."""
    return zlib.crc32(f"{lake_code}|{observed_on.isoformat()}".encode("utf-8"))


def score_with_eif(lake_code: str, own_earlier: list[ExtentRecord], other_lakes_earlier: list[list[ExtentRecord]],
                   observed_on: date, extent_ha: float) -> EifResult:
    """Score one new reading.

    own_earlier          this lake's usable readings from before observed_on (same sensor)
    other_lakes_earlier  the same for every other lake (one list per lake), also only before observed_on
    """
    features = relative_features(own_earlier, observed_on, extent_ha) if own_earlier else None
    if features is None:
        return EifResult(status="insufficient_history")
    earlier_features = features_of_history(own_earlier)
    for history in other_lakes_earlier:
        earlier_features.extend(features_of_history(history))
    if len(earlier_features) < MIN_EARLIER_POINTS:
        return EifResult(status="insufficient_history", earlier_points=len(earlier_features))

    new_point = (features.level, features.change)
    points = [(f.level, f.change) for f in earlier_features] + [new_point]
    forest = ExtendedIsolationForest(N_TREES, SAMPLE_SIZE, seed=seed_for(lake_code, observed_on)).fit(points)
    raw = forest.anomaly_score(new_point)
    score = to_0_100(raw, forest.points_per_tree)
    return EifResult(status="ok", score_0_100=score, raw_score=raw, usual_ha=features.usual_ha,
                     direction=direction_of(features.level),
                     reason=reason_line(features, extent_ha, observed_on, score, len(earlier_features)),
                     earlier_points=len(earlier_features))
