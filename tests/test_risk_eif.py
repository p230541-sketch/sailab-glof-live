"""sailab/risk_eif.py: the relative features, the 0 to 100 scale, the reason line, and the three
behaviours the plan asks for (steady lake low, jumping lake high, shrinking lake never flagged as growing).
All data here is made up."""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from sailab import db, eif, risk_eif, sample_data
from sailab.risk import ExtentRecord

STEADY, JUMP, SHRINK = sample_data.SAMPLE_LAKES
SERIES = {lake.code: [ExtentRecord(m.observed_on, m.extent_ha) for m in sample_data.sample_series(lake)]
          for lake in sample_data.SAMPLE_LAKES}


def score_reading(code: str, index: int) -> risk_eif.EifResult:
    """Score one reading of a sample lake exactly as the pipeline does: only earlier readings are used."""
    record = SERIES[code][index]
    own = [r for r in SERIES[code] if r.observed_on < record.observed_on]
    others = [[r for r in series if r.observed_on < record.observed_on]
              for other, series in SERIES.items() if other != code]
    return risk_eif.score_with_eif(code, own, others, record.observed_on, record.extent_ha)


# --- the two relative features -------------------------------------------------------------------
def _julys(value=100.0):
    """Six made-up July readings from two earlier years, all the same area."""
    return [ExtentRecord(date(year, 7, day), value) for year in (2024, 2025) for day in (5, 15, 25)]


def test_level_is_the_share_above_the_usual_area_for_the_month():
    earlier = _julys(100.0) + [ExtentRecord(date(2026, 7, 5), 100.0)]
    features = risk_eif.relative_features(earlier, date(2026, 7, 15), 125.0)
    assert features.usual_ha == 100.0                     # median of the seven earlier July readings
    assert features.level == pytest.approx(0.25)          # (125 - 100) / 100
    assert features.previous_level == pytest.approx(0.0)  # ten days before, the lake was at its usual area
    assert features.change == pytest.approx(0.25)         # so the level moved up by 0.25
    assert features.days_since_previous == 10


def test_usual_is_the_median_so_one_wild_earlier_reading_does_not_move_it():
    earlier = _julys(100.0)[:-1] + [ExtentRecord(date(2025, 7, 25), 400.0)]
    assert risk_eif.relative_features(earlier, date(2026, 7, 15), 100.0).usual_ha == 100.0


def test_no_features_without_five_same_month_readings_from_two_years():
    four_readings = _julys()[:4]
    assert risk_eif.relative_features(four_readings, date(2026, 7, 15), 100.0) is None
    one_year_only = [ExtentRecord(date(2025, 7, day), 100.0) for day in (1, 5, 10, 15, 20, 25)]
    assert risk_eif.relative_features(one_year_only, date(2026, 7, 15), 100.0) is None


def test_change_is_zero_when_the_previous_reading_is_too_old():
    features = risk_eif.relative_features(_julys(), date(2026, 7, 15), 125.0)   # previous reading: July 2025
    assert features.change == 0.0 and features.previous_level is None and features.days_since_previous is None


def test_the_normal_summer_rise_and_fall_is_not_counted_as_change():
    """The steady sample lake falls about 3% from August to September every year. Measured against the
    usual area of each month that is no change at all."""
    series = SERIES[STEADY.code]
    first_september_2026 = next(r for r in series if r.observed_on == date(2026, 9, 5))
    earlier = [r for r in series if r.observed_on < first_september_2026.observed_on]
    features = risk_eif.relative_features(earlier, first_september_2026.observed_on, first_september_2026.extent_ha)
    assert earlier[-1].extent_ha > first_september_2026.extent_ha * 1.02        # the raw area really fell
    assert abs(features.change) < 0.01                                          # the level did not


def test_features_of_history_never_look_ahead():
    series = SERIES[JUMP.code]
    with_jump = risk_eif.features_of_history(series)
    without_last = risk_eif.features_of_history(series[:-1])
    assert with_jump[:-1] == without_last          # adding a later reading changes nothing before it


# --- the 0 to 100 scale ---------------------------------------------------------------------------
def test_scale_is_0_at_an_ordinary_point_and_100_at_the_highest_possible_score():
    n = 64
    highest = 2.0 ** (-1.0 / eif.c_factor(n))
    assert risk_eif.to_0_100(0.5, n) == 0.0
    assert risk_eif.to_0_100(0.31, n) == 0.0                  # more ordinary than ordinary is still 0
    assert risk_eif.to_0_100(highest, n) == 100.0
    assert risk_eif.to_0_100((0.5 + highest) / 2, n) == 50.0  # a straight line in between
    assert risk_eif.to_0_100(0.999, n) == 100.0               # never above 100


def test_direction_words():
    assert risk_eif.direction_of(0.25) == "above usual"
    assert risk_eif.direction_of(-0.25) == "below usual"
    assert risk_eif.direction_of(0.01) == risk_eif.direction_of(-0.01) == "about usual"


# --- the three behaviours the plan asks for --------------------------------------------------------
def test_a_steady_lake_scores_low():
    newest = [score_reading(STEADY.code, i) for i in (-3, -2, -1)]
    assert all(r.status == "ok" and r.score_0_100 < 20 for r in newest)
    assert not any(risk_eif.is_flagged_as_growing(r) for r in newest)


def test_a_jumping_lake_scores_high_and_is_flagged_as_growing():
    first_jumped = score_reading(JUMP.code, -3)
    assert first_jumped.score_0_100 > 80
    assert first_jumped.direction == "above usual"
    assert risk_eif.is_flagged_as_growing(first_jumped)


def test_a_shrinking_lake_is_unusual_but_is_never_flagged_as_growing():
    for index in (-3, -2, -1):
        result = score_reading(SHRINK.code, index)
        assert result.direction == "below usual"
        assert not risk_eif.is_flagged_as_growing(result)
    assert score_reading(SHRINK.code, -3).score_0_100 > 80     # the sudden loss itself is still seen


def test_the_second_jumped_reading_is_still_flagged_where_the_z_score_lost_it():
    """The z-score gave the second jumped reading 2.8 (see test_sample_data.py): the jump had become part
    of its own normal. The usual area here is a median, so one jumped value does not move it."""
    second_jumped = score_reading(JUMP.code, -2)
    assert second_jumped.score_0_100 >= risk_eif.FLAG_SCORE
    assert risk_eif.is_flagged_as_growing(second_jumped)


def test_known_limit_the_score_falls_as_jumped_readings_pile_up():
    """Kept visible on purpose: every jumped reading joins the earlier points, so the next one is a
    little less alone. By the third the score is under the flag line, although the lake is just as large."""
    first, second, third = (score_reading(JUMP.code, i).score_0_100 for i in (-3, -2, -1))
    assert first > second > third
    assert third < risk_eif.FLAG_SCORE


# --- other rules -----------------------------------------------------------------------------------
def test_same_reading_scored_twice_gives_the_same_score():
    assert score_reading(JUMP.code, -3) == score_reading(JUMP.code, -3)


def test_no_score_with_too_few_earlier_points():
    # On 25 August 2024 this reading has enough same-month history of its own (three August readings
    # from 2023 and two from 2024), but only six earlier points exist in all three lakes together:
    # the 25 June and 25 July 2024 readings of each lake. Six is fewer than MIN_EARLIER_POINTS.
    index = next(i for i, r in enumerate(SERIES[JUMP.code]) if r.observed_on == date(2024, 8, 25))
    result = score_reading(JUMP.code, index)
    assert result.status == "insufficient_history" and result.score_0_100 is None
    assert result.earlier_points == 6 < risk_eif.MIN_EARLIER_POINTS


def test_no_score_in_the_first_year():
    assert score_reading(STEADY.code, 3).status == "insufficient_history"


def test_reason_line_says_the_size_the_usual_size_and_the_direction():
    reason = score_reading(JUMP.code, -3).reason
    assert "149.1 ha" in reason and "25% above the usual" in reason and "September" in reason
    assert "11 days before it was about usual" in reason
    assert reason.endswith("earlier readings.")
    assert "below the usual" in score_reading(SHRINK.code, -3).reason
    assert "is about the usual" in score_reading(STEADY.code, -1).reason


# --- saved to the database ------------------------------------------------------------------------
def test_old_database_gets_the_two_new_columns_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE lake (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, centre_lon REAL NOT NULL,
                           centre_lat REAL NOT NULL, boundary_radius_m REAL NOT NULL, growth_distance_limit_m REAL NOT NULL DEFAULT 2500);
        CREATE TABLE risk_score (id INTEGER PRIMARY KEY, lake_id INTEGER NOT NULL, measurement_id INTEGER NOT NULL,
                                 method TEXT NOT NULL, status TEXT NOT NULL, baseline_ha REAL, deviation_score REAL,
                                 scored_at TEXT NOT NULL);
        INSERT INTO risk_score VALUES (1, 1, 1, 'seasonal_zscore', 'ok', 245.0, 1.5, '2026-07-01T06:00:00+00:00');
    """)
    conn.commit()
    conn.close()

    conn = db.connect(path)                       # opening the database runs the migration
    columns = [row[1] for row in conn.execute("PRAGMA table_info(risk_score)")]
    assert columns[-2:] == ["score_0_100", "reason"]
    assert tuple(conn.execute("SELECT * FROM risk_score").fetchone()) == (
        1, 1, 1, "seasonal_zscore", "ok", 245.0, 1.5, "2026-07-01T06:00:00+00:00", None, None)
    assert db.migrate(conn) == 0                  # running it again changes nothing


def test_score_outside_0_to_100_is_refused(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 1000.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-01T05:59:00+00:00", 1.0, "data/x/a.tif")
    m_id = db.insert_measurement(conn, scene_id, lake_id, "optical", 250.0, "ok")
    with pytest.raises(ValueError):
        db.insert_risk_score(conn, lake_id, m_id, db.RISK_METHOD_EIF, "ok", 245.0, 0.8, score_0_100=120.0)


def test_pipeline_saves_the_new_score_next_to_the_z_score(tmp_path):
    from sailab import pipeline

    conn = db.connect(tmp_path / "t.db")
    ids = {}
    for lake in sample_data.SAMPLE_LAKES:
        lake_id = db.insert_lake(conn, lake.code, lake.name, 0.0, 0.0, 1000.0, 1000.0)
        for record in SERIES[lake.code]:
            at = record.observed_on.isoformat() + "T06:00:00+00:00"
            scene_id = db.insert_scene(conn, lake_id, "sentinel-2", at, 0.0, f"sample_data/{lake.code}/{record.observed_on}.tif")
            ids[(lake.code, record.observed_on)] = db.insert_measurement(conn, scene_id, lake_id, "optical", record.extent_ha, "ok")
    jump_row = {"id": 2, "code": JUMP.code}
    first_jumped = SERIES[JUMP.code][-3]
    status = pipeline.score_eif(conn, jump_row, first_jumped.observed_on.isoformat() + "T06:00:00+00:00", "sample",
                                ids[(JUMP.code, first_jumped.observed_on)], first_jumped.extent_ha, "optical")
    assert status == "ok"
    [row] = conn.execute("SELECT method, status, baseline_ha, deviation_score, score_0_100, reason FROM risk_score").fetchall()
    assert row["method"] == "extended_isolation_forest" and row["status"] == "ok"
    assert row["score_0_100"] == score_reading(JUMP.code, -3).score_0_100      # later readings in the table were ignored
    assert 0.0 < row["deviation_score"] < 1.0                                  # the forest's raw score
    assert row["baseline_ha"] == pytest.approx(119.0, abs=0.5)                 # the usual area for September
    assert "25% above the usual" in row["reason"]
