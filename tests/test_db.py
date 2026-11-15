"""Tests for sailab.db, each against a real SQLite file in a temporary directory (no mocks)."""
import sqlite3
from datetime import date

import pytest

from sailab import db
from sailab.risk import ExtentRecord, score_against_seasonal_baseline


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_sailab.db"


@pytest.fixture
def conn(db_path):
    connection = db.connect(db_path)
    yield connection
    connection.close()


def _add_measured_scene(conn, lake_id, acquired_at, extent_ha, status="ok"):
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", acquired_at, 10.0, f"/data/{acquired_at}.tif")
    return db.insert_measurement(conn, scene_id, lake_id, "optical", extent_ha, status)


def test_connect_creates_all_six_tables(conn):
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"lake", "scene", "measurement", "alt_measurement", "risk_score", "run_log"}


def test_rows_survive_closing_and_reopening_the_file(db_path):
    """The point of this module: data written in one run is still there in the next."""
    first = db.connect(db_path)
    lake_id = db.insert_lake(first, "TST", "Test Lake", 73.0, 36.0, 500.0)
    first.close()

    second = db.connect(db_path)
    row = second.execute("SELECT * FROM lake WHERE id = ?", (lake_id,)).fetchone()
    second.close()

    assert (row["code"], row["name"], row["centre_lon"], row["centre_lat"]) == ("TST", "Test Lake", 73.0, 36.0)
    assert row["growth_distance_limit_m"] == 2500.0  # default from the schema


def test_seed_inserts_the_two_lakes_with_the_exact_given_coordinates(conn):
    db.seed_lakes(conn)
    lakes = {row["code"]: dict(row) for row in db.get_lakes(conn)}

    assert set(lakes) == {"KRB", "ATS"}
    assert lakes["KRB"]["name"] == "Karambar Lake"
    assert (lakes["KRB"]["centre_lon"], lakes["KRB"]["centre_lat"]) == (73.7053229, 36.880833)
    assert (lakes["KRB"]["boundary_radius_m"], lakes["KRB"]["growth_distance_limit_m"]) == (2500.0, 2500.0)
    assert lakes["ATS"]["name"] == "Atro Sar"
    assert (lakes["ATS"]["centre_lon"], lakes["ATS"]["centre_lat"]) == (73.65037, 36.64458)
    # Changed from (800, 1200) on 2026-11-08: the 800 m window cut the lake off (see db.SEED_LAKES comment)
    assert (lakes["ATS"]["boundary_radius_m"], lakes["ATS"]["growth_distance_limit_m"]) == (1500.0, 1500.0)


def test_seeding_twice_does_not_duplicate(conn):
    first_ids = db.seed_lakes(conn)
    second_ids = db.seed_lakes(conn)
    assert first_ids == second_ids
    assert conn.execute("SELECT COUNT(*) FROM lake").fetchone()[0] == 2


def test_seeding_refuses_to_overwrite_a_changed_coordinate(conn):
    db.seed_lakes(conn)
    conn.execute("UPDATE lake SET centre_lat = 36.9 WHERE code = 'KRB'")
    conn.commit()
    with pytest.raises(ValueError, match="KRB"):
        db.seed_lakes(conn)


def test_duplicate_lake_code_is_rejected(conn):
    db.insert_lake(conn, "DUP", "First", 73.0, 36.0, 500.0)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_lake(conn, "DUP", "Second", 74.0, 35.0, 500.0)


def test_foreign_keys_are_enforced(conn):
    """A scene pointing at a lake that does not exist must be refused, not silently stored."""
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_scene(conn, 999, "sentinel-2", "2026-07-15", 12.0, "/data/x.tif")


def test_insert_scene_records_download_time_and_nullable_cloud(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-1", "2026-07-15", None, "/data/s1.tif",
                               downloaded_at="2026-11-07T06:00:00+00:00")
    row = conn.execute("SELECT * FROM scene WHERE id = ?", (scene_id,)).fetchone()
    assert row["cloud_fraction"] is None
    assert row["downloaded_at"] == "2026-11-07T06:00:00+00:00"


def test_insert_scene_rejects_unknown_source_and_bad_date(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    with pytest.raises(ValueError):
        db.insert_scene(conn, lake_id, "landsat-8", "2026-07-15", 10.0, "/x.tif")
    with pytest.raises(ValueError):
        db.insert_scene(conn, lake_id, "sentinel-2", "15/07/2026", 10.0, "/x.tif")


def test_measurement_status_and_extent_must_agree(conn):
    """An 'insufficient_observation' must be stored as NULL, never as an invented 0."""
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-15", 10.0, "/x.tif")

    with pytest.raises(ValueError):
        db.insert_measurement(conn, scene_id, lake_id, "optical", 0.0, "insufficient_observation")
    with pytest.raises(ValueError):
        db.insert_measurement(conn, scene_id, lake_id, "optical", None, "ok")

    m_id = db.insert_measurement(conn, scene_id, lake_id, "optical", None, "insufficient_observation")
    row = conn.execute("SELECT extent_ha, status FROM measurement WHERE id = ?", (m_id,)).fetchone()
    assert row["extent_ha"] is None and row["status"] == "insufficient_observation"


def test_one_measurement_per_scene(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-15", 10.0, "/x.tif")
    db.insert_measurement(conn, scene_id, lake_id, "optical", 40.0, "ok")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_measurement(conn, scene_id, lake_id, "optical", 41.0, "ok")


def test_get_extent_history_uses_pass_date_skips_failures_and_sorts(conn):
    """Given three 'ok' measurements inserted out of order and one failed one,
    history is the three ok values sorted by satellite pass date."""
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    other_lake = db.insert_lake(conn, "OTH", "Other Lake", 74.0, 35.0, 500.0)
    _add_measured_scene(conn, lake_id, "2025-07-15", 44.0)
    _add_measured_scene(conn, lake_id, "2023-07-15", 40.0)
    _add_measured_scene(conn, lake_id, "2024-07-15", None, status="insufficient_observation")
    _add_measured_scene(conn, lake_id, "2024-07-20", 42.0)
    _add_measured_scene(conn, other_lake, "2024-07-15", 999.0)

    history = db.get_extent_history(conn, lake_id)

    assert history == [
        ExtentRecord(date(2023, 7, 15), 40.0),
        ExtentRecord(date(2024, 7, 20), 42.0),
        ExtentRecord(date(2025, 7, 15), 44.0),
    ]


def test_get_extent_history_can_exclude_the_measurement_being_scored(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    _add_measured_scene(conn, lake_id, "2025-07-15", 44.0)
    new_id = _add_measured_scene(conn, lake_id, "2026-07-15", 50.0)

    history = db.get_extent_history(conn, lake_id, exclude_measurement_id=new_id)

    assert history == [ExtentRecord(date(2025, 7, 15), 44.0)]


def test_history_from_the_database_reproduces_TC_BAS_01(conn):
    """Round trip into the real, unmodified risk module: July extents of 40, 42, 44 ha stored in the
    database, then a new July value of 50 ha, must give baseline 42.0 and deviation score 4.0,
    the same numbers TC-BAS-01 pre-calculated by hand."""
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    for year, extent in [(2023, 40.0), (2024, 42.0), (2025, 44.0)]:
        _add_measured_scene(conn, lake_id, f"{year}-07-15", extent)
    new_id = _add_measured_scene(conn, lake_id, "2026-07-15", 50.0)

    history = db.get_extent_history(conn, lake_id, exclude_measurement_id=new_id)
    result = score_against_seasonal_baseline(history, date(2026, 7, 15), new_extent_ha=50.0)
    risk_id = db.insert_risk_score(conn, lake_id, new_id, "seasonal_zscore", "ok",
                                   result.baseline_ha, result.deviation_score)

    row = conn.execute("SELECT * FROM risk_score WHERE id = ?", (risk_id,)).fetchone()
    assert row["baseline_ha"] == pytest.approx(42.0)
    assert row["deviation_score"] == pytest.approx(4.0)
    assert row["status"] == "ok"


def test_insert_risk_score_insufficient_history_stores_nulls(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    m_id = _add_measured_scene(conn, lake_id, "2026-07-15", 50.0)
    risk_id = db.insert_risk_score(conn, lake_id, m_id, "seasonal_zscore", "insufficient_history", None, None)
    row = conn.execute("SELECT * FROM risk_score WHERE id = ?", (risk_id,)).fetchone()
    assert (row["status"], row["baseline_ha"], row["deviation_score"]) == ("insufficient_history", None, None)


def test_insert_risk_score_rejects_unknown_status_and_method(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 500.0)
    m_id = _add_measured_scene(conn, lake_id, "2026-07-15", 50.0)
    with pytest.raises(ValueError):
        # risk.py's own spelling has a space; the database column uses an underscore. The caller must map it.
        db.insert_risk_score(conn, lake_id, m_id, "seasonal_zscore", "insufficient history", None, None)
    with pytest.raises(ValueError):
        db.insert_risk_score(conn, lake_id, m_id, "trained_model", "ok", 1.0, 1.0)


def test_run_log_start_and_finish_clean(conn):
    run_id = db.start_run_log(conn, started_at="2026-11-07T06:00:00+00:00")
    open_row = conn.execute("SELECT * FROM run_log WHERE id = ?", (run_id,)).fetchone()
    assert open_row["finished_at"] is None

    db.finish_run_log(conn, run_id, lakes_processed=2, scenes_downloaded=3,
                      finished_at="2026-11-07T06:04:30+00:00")

    row = conn.execute("SELECT * FROM run_log WHERE id = ?", (run_id,)).fetchone()
    assert (row["started_at"], row["finished_at"]) == ("2026-11-07T06:00:00+00:00", "2026-11-07T06:04:30+00:00")
    assert (row["lakes_processed"], row["scenes_downloaded"], row["errors"]) == (2, 3, None)


def test_run_log_keeps_the_real_error_text(conn):
    run_id = db.start_run_log(conn)
    error_text = "EEException: Earth Engine memory capacity exceeded."
    db.finish_run_log(conn, run_id, lakes_processed=1, scenes_downloaded=0, errors=error_text)
    assert conn.execute("SELECT errors FROM run_log WHERE id = ?", (run_id,)).fetchone()[0] == error_text


def test_run_log_cannot_be_finished_twice_or_if_missing(conn):
    run_id = db.start_run_log(conn)
    db.finish_run_log(conn, run_id, 0, 0)
    with pytest.raises(ValueError):
        db.finish_run_log(conn, run_id, 5, 5)
    with pytest.raises(ValueError):
        db.finish_run_log(conn, 12345, 0, 0)


@pytest.mark.parametrize("lon, lat", [(73.7, 95.0), (73.7, -90.5), (181.0, 36.9), (-180.5, 36.9)])
def test_out_of_range_coordinates_are_refused(conn, lon, lat):
    """Added after mutation D7 (latitude limit widened to ±180) survived the whole suite: nothing tested it."""
    with pytest.raises(ValueError, match="coordinates out of range"):
        db.insert_lake(conn, "BAD", "Bad lake", lon, lat, 1000.0)


# --- migration: the old, wrong method label is renamed and no number changes (2026-11-11) ----------
def test_old_method_label_is_renamed_and_the_numbers_are_kept(tmp_path):
    path = tmp_path / "old.db"
    conn = db.connect(path)
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 1000.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-01T05:59:00+00:00", 1.0, "data/x/a.tif")
    m_id = db.insert_measurement(conn, scene_id, lake_id, "optical", 250.0, "ok")
    # Written the way an older version of this code wrote it (the insert function now refuses the old name).
    conn.execute("INSERT INTO risk_score (lake_id, measurement_id, method, status, baseline_ha, deviation_score, scored_at) "
                 "VALUES (?, ?, 'anomaly_detector', 'ok', 245.0, 1.5, '2026-07-01T06:00:00+00:00')", (lake_id, m_id))
    conn.commit()
    conn.close()

    conn = db.connect(path)   # opening the database runs the migration
    rows = conn.execute("SELECT method, status, baseline_ha, deviation_score, scored_at FROM risk_score").fetchall()
    assert [tuple(r) for r in rows] == [("seasonal_zscore", "ok", 245.0, 1.5, "2026-07-01T06:00:00+00:00")]
    assert db.migrate(conn) == 0   # running it again changes nothing


def test_the_old_method_label_can_no_longer_be_written():
    assert "anomaly_detector" not in db.RISK_METHODS
