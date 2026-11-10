"""The made-up sample data (sailab/sample_data.py, scripts/make_sample_db.py): marked as sample, the
same on every run, and shaped the way its three lakes are described."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from sailab import sample_data

_SPEC = importlib.util.spec_from_file_location(
    "sailab_make_sample_db", Path(__file__).resolve().parent.parent / "scripts" / "make_sample_db.py")
make_sample_db = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(make_sample_db)

STEADY, JUMP, SHRINK = sample_data.SAMPLE_LAKES


def _ratio_of_last_value_to_same_slot_a_year_before(lake):
    series = sample_data.sample_series(lake)
    per_year = len(series) // len(sample_data.YEARS)
    return series[-1].extent_ha / series[-1 - per_year].extent_ha


def test_series_is_the_same_on_every_run():
    assert sample_data.sample_series(JUMP) == sample_data.sample_series(JUMP)


def test_series_has_four_summers_of_twelve_values_oldest_first():
    series = sample_data.sample_series(STEADY)
    assert len(series) == 4 * 4 * 3
    assert [m.observed_on for m in series] == sorted(m.observed_on for m in series)
    assert {m.observed_on.month for m in series} == {6, 7, 8, 9}


def test_steady_lake_stays_within_two_percent_of_its_seasonal_shape():
    for m in sample_data.sample_series(STEADY):
        expected = STEADY.base_ha * sample_data.SEASON_SHARE[m.observed_on.month]
        assert abs(m.extent_ha - expected) / expected < 0.02


def test_jumping_lake_ends_about_a_quarter_larger_than_the_year_before():
    assert _ratio_of_last_value_to_same_slot_a_year_before(JUMP) == pytest.approx(1.25, abs=0.02)


def test_shrinking_lake_ends_about_a_quarter_smaller_than_the_year_before():
    assert _ratio_of_last_value_to_same_slot_a_year_before(SHRINK) == pytest.approx(0.75, abs=0.02)


def test_only_the_newest_values_carry_the_sudden_change():
    series = sample_data.sample_series(JUMP)
    unchanged = series[:-sample_data.CHANGED_VALUES]
    assert max(m.extent_ha for m in unchanged) < JUMP.base_ha * 1.05


def test_every_sample_lake_is_marked_as_sample():
    for lake in sample_data.SAMPLE_LAKES:
        assert sample_data.is_sample_code(lake.code)
        assert lake.name.startswith(sample_data.SAMPLE_NAME_PREFIX)
    assert not sample_data.is_sample_code("KRB")


# --- the sample database ------------------------------------------------------------------------
@pytest.fixture
def sample_db(tmp_path):
    path = tmp_path / "sample.db"
    counts = make_sample_db.build_sample_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn, counts


def test_sample_database_holds_only_marked_rows(sample_db):
    conn, counts = sample_db
    assert counts == {"lakes": 3, "measurements": 144, "scores": 144}
    codes = [r["code"] for r in conn.execute("SELECT code FROM lake")]
    assert codes and all(code.startswith("SAMPLE-") for code in codes)
    assert conn.execute("SELECT COUNT(*) FROM scene WHERE file_path NOT LIKE 'sample_data/%'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM lake WHERE centre_lon != 0 OR centre_lat != 0").fetchone()[0] == 0


def _newest_scores(conn, code, n):
    """The n newest scores of one lake, oldest of them first."""
    rows = conn.execute(
        "SELECT r.status, r.deviation_score FROM risk_score r JOIN measurement m ON m.id = r.measurement_id "
        "JOIN scene s ON s.id = m.scene_id JOIN lake l ON l.id = m.lake_id WHERE l.code = ? "
        "ORDER BY s.acquired_at DESC LIMIT ?", (code, n)).fetchall()
    return rows[::-1]


def test_existing_z_score_on_the_first_changed_value(sample_db):
    """The FIRST value after the sudden change: low for the steady lake, high for the jump, strongly
    negative for the shrink (below normal, so a shrinking lake is never scored as growth)."""
    conn, _ = sample_db
    n = sample_data.CHANGED_VALUES
    steady, jump, shrink = (_newest_scores(conn, lake.code, n)[0] for lake in (STEADY, JUMP, SHRINK))
    assert steady["status"] == jump["status"] == shrink["status"] == "ok"
    assert abs(steady["deviation_score"]) < 4
    assert jump["deviation_score"] > 10
    assert shrink["deviation_score"] < -10


def test_known_weakness_of_the_z_score_the_jump_hides_itself(sample_db):
    """A real weakness of the baseline method, kept visible on purpose: once a jumped value is stored it
    becomes part of the same month's "normal", the spread grows, and the NEXT jumped values score far
    lower although the lake is just as large. A new method has to do better than this."""
    conn, _ = sample_db
    first, _second, third = (r["deviation_score"] for r in _newest_scores(conn, JUMP.code, 3))
    assert first > 10
    assert 0 < third < 4


def test_first_year_has_too_little_history_to_score(sample_db):
    conn, _ = sample_db
    statuses = {r[0] for r in conn.execute(
        "SELECT r.status FROM risk_score r JOIN measurement m ON m.id = r.measurement_id "
        "JOIN scene s ON s.id = m.scene_id WHERE s.acquired_at < '2024-01-01'")}
    assert statuses == {"insufficient_history"}


def test_refuses_to_write_into_the_real_database():
    with pytest.raises(ValueError):
        make_sample_db.build_sample_db(make_sample_db.REAL_DB)
