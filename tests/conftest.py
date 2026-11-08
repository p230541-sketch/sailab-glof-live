"""Shared fixtures for the web app tests."""
from datetime import date

import sqlite3

import pytest

from sailab import db

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
