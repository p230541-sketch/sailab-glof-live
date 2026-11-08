"""Tests for the read-only data layer (sailab/queries.py) and the web API (webapp/main.py).

Every test builds its own temporary database with the real schema and the real seed lakes, then
inserts a small, known set of rows, so each expected number below can be checked by hand.
The live sailab_glof.db is never touched.

The KRB rows inserted (today is fixed at 2026-11-09):
  2025-07-10  cloud 3.0    measured ok 240.0 ha   risk insufficient_history
  2025-08-01  cloud 80.0   too cloudy, not downloaded
  2025-08-15  cloud 5.0    measured insufficient_observation
  2026-07-12  cloud 2.0    measured ok 250.0 ha   risk ok, baseline 245.0, score 1.5
  2026-10-21  cloud 99.0   too cloudy, not downloaded
ATS: no scenes at all.
"""
import hashlib
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sailab import db, queries
from webapp.main import create_app

TODAY = date(2026, 11, 9)


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "source.db"
    conn = db.connect(path)
    db.seed_lakes(conn)                                   # KRB = id 1, ATS = id 2

    def scene(day, cloud, downloaded=True):
        file_path = f"data/scenes/KRB/{day}.tif" if downloaded else f"not_downloaded/KRB/{day}"
        return db.insert_scene(conn, 1, "sentinel-2", f"{day}T05:58:58+00:00", cloud, file_path)

    s1 = scene("2025-07-10", 3.0)
    m1 = db.insert_measurement(conn, s1, 1, "optical", 240.0, "ok")
    db.insert_risk_score(conn, 1, m1, "anomaly_detector", "insufficient_history", None, None)
    scene("2025-08-01", 80.0, downloaded=False)
    s3 = scene("2025-08-15", 5.0)
    db.insert_measurement(conn, s3, 1, "optical", None, "insufficient_observation")
    s4 = scene("2026-07-12", 2.0)
    m4 = db.insert_measurement(conn, s4, 1, "optical", 250.0, "ok")
    db.insert_risk_score(conn, 1, m4, "anomaly_detector", "ok", 245.0, 1.5)
    scene("2026-10-21", 99.0, downloaded=False)
    r1 = db.start_run_log(conn, started_at="2026-11-08T18:00:00+00:00")
    db.finish_run_log(conn, r1, 2, 3, finished_at="2026-11-08T18:01:00+00:00")
    r2 = db.start_run_log(conn, started_at="2026-11-09T18:00:00+00:00")
    db.finish_run_log(conn, r2, 1, 0, errors="EarthEngineError: quota", finished_at="2026-11-09T18:00:30+00:00")
    conn.close()
    return path


@pytest.fixture
def conn(source_db):
    c = sqlite3.connect(source_db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def client(source_db, tmp_path):
    app = create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY)
    return TestClient(app)


# --- queries ---------------------------------------------------------------------------------
def test_lake_summary_counts_and_latest_values(conn):
    s = queries.lake_summary(conn, 1, TODAY)
    assert s["counts"] == {"scenes": 5, "too_cloudy": 2, "measured_ok": 2, "insufficient_observation": 1}
    assert s["latest_scene"]["acquired_at"].startswith("2026-10-21")
    assert s["latest_scene"]["too_cloudy"] == 1 and s["latest_scene"]["measurement_status"] is None
    assert s["latest_ok_measurement"]["acquired_at"].startswith("2026-07-12")
    assert s["latest_ok_measurement"]["extent_ha"] == 250.0
    assert s["latest_risk_score"]["status"] == "ok"
    assert (s["latest_risk_score"]["baseline_ha"], s["latest_risk_score"]["deviation_score"]) == (245.0, 1.5)
    # 12 Jul -> 9 Nov: 19 (rest of Jul) + 31 (Aug) + 30 (Sep) + 31 (Oct) + 9 (Nov) = 120 days
    assert s["days_since_last_ok"] == 120


def test_a_lake_with_no_data_returns_empty_values_not_invented_ones(conn):
    s = queries.lake_summary(conn, 2, TODAY)
    assert s["counts"] == {"scenes": 0, "too_cloudy": 0, "measured_ok": 0, "insufficient_observation": 0}
    assert s["latest_scene"] is None
    assert s["latest_ok_measurement"] is None
    assert s["latest_risk_score"] is None
    assert s["days_since_last_ok"] is None
    assert queries.lake_history(conn, 2) == []


def test_lake_history_is_one_row_per_scene_oldest_first(conn):
    h = queries.lake_history(conn, 1)
    assert [r["acquired_at"][:10] for r in h] == ["2025-07-10", "2025-08-01", "2025-08-15", "2026-07-12", "2026-10-21"]
    assert [r["measurement_status"] for r in h] == ["ok", None, "insufficient_observation", "ok", None]
    assert [r["too_cloudy"] for r in h] == [0, 1, 0, 0, 1]
    assert [r["extent_ha"] for r in h] == [240.0, None, None, 250.0, None]
    assert [r["risk_status"] for r in h] == ["insufficient_history", None, None, "ok", None]
    assert h[3]["deviation_score"] == 1.5


def test_run_log_newest_first_and_totals(conn):
    assert [r["id"] for r in queries.run_log(conn)] == [2, 1]
    assert queries.latest_run(conn)["errors"] == "EarthEngineError: quota"
    assert queries.database_totals(conn) == {"lake": 2, "scene": 5, "measurement": 3, "risk_score": 2,
                                             "run_log": 2, "too_cloudy": 2}


# --- API -------------------------------------------------------------------------------------
def test_api_lakes_matches_the_queries(client):
    body = client.get("/api/lakes").json()
    assert [l["code"] for l in body] == ["KRB", "ATS"]
    assert body[0]["summary"]["counts"]["measured_ok"] == 2
    assert body[0]["summary"]["days_since_last_ok"] == 120
    assert body[1]["summary"]["latest_ok_measurement"] is None


def test_api_single_lake_history_and_404(client):
    assert client.get("/api/lakes/KRB").json()["name"] == "Karambar Lake"
    assert len(client.get("/api/lakes/KRB/history").json()) == 5
    missing = client.get("/api/lakes/XYZ")
    assert missing.status_code == 404 and "XYZ" in missing.json()["detail"]
    assert client.get("/api/lakes/XYZ/history").status_code == 404


def test_api_run_log_latest_shows_the_real_error(client):
    latest = client.get("/api/run-log/latest").json()
    assert latest["id"] == 2 and latest["errors"] == "EarthEngineError: quota"


def test_empty_run_log_is_a_404_not_a_made_up_run(tmp_path):
    empty = tmp_path / "empty.db"
    c = db.connect(empty); db.seed_lakes(c); c.close()
    client = TestClient(create_app(source_db=empty, work_dir=tmp_path / "w", today=lambda: TODAY))
    assert client.get("/api/run-log/latest").status_code == 404


# --- the working copy ----------------------------------------------------------------------------
def test_provenance_identifies_the_exact_source_file(client, source_db):
    p = client.get("/api/provenance").json()
    assert p["source_sha256"] == hashlib.sha256(source_db.read_bytes()).hexdigest()
    assert p["working_copy"] != str(source_db)


def test_the_app_reads_a_copy_and_never_changes_the_source(client, source_db):
    before = hashlib.sha256(source_db.read_bytes()).hexdigest()
    for url in ("/api/lakes", "/api/lakes/KRB/history", "/api/run-log", "/api/totals"):
        assert client.get(url).status_code == 200
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == before


def test_page_reads_are_genuinely_read_only(client):
    with client.app.state.read_only() as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM lake")


def test_a_missing_source_database_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_app(source_db=tmp_path / "nope.db", work_dir=tmp_path / "w")


def test_the_app_shows_its_snapshot_even_if_the_source_changes_afterwards(client, source_db):
    """The pages must read the start-up copy, not the published file: a later change to the source
    (e.g. the nightly bot's commit being pulled) must not appear until the app is restarted."""
    assert client.get("/api/totals").json()["scene"] == 5
    c = db.connect(source_db)
    db.insert_scene(c, 2, "sentinel-2", "2026-11-09T05:58:58+00:00", 1.0, "data/scenes/ATS/new.tif")
    c.close()
    assert client.get("/api/totals").json()["scene"] == 5
