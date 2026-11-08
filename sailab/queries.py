"""Read-only queries behind the GUI. Every number a screen shows comes from one of these functions.

Nothing here writes to the database or invents a value: a missing row is returned as None / an empty
list, and the screen must show it as missing. Each function takes an open sqlite3 connection, so the
same code runs against the real database copy and against a temporary test database.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

NOT_DOWNLOADED_PREFIX = "not_downloaded/"   # same marker pipeline.py writes for too-cloudy scenes


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def list_lakes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM lake ORDER BY id")]


def get_lake(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM lake WHERE code = ?", (code,)).fetchone())


def lake_summary(conn: sqlite3.Connection, lake_id: int, today: date) -> dict[str, Any]:
    """Everything the dashboard shows for one lake, each value from one query below."""
    counts = conn.execute(
        f"""SELECT COUNT(*) AS scenes,
                   COALESCE(SUM(s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%'), 0) AS too_cloudy,
                   COALESCE(SUM(m.status = 'ok'), 0) AS measured_ok,
                   COALESCE(SUM(m.status = 'insufficient_observation'), 0) AS insufficient_observation
            FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
            WHERE s.lake_id = ?""", (lake_id,)).fetchone()
    latest_scene = conn.execute(
        f"""SELECT s.id, s.acquired_at, s.cloud_fraction, s.file_path,
                   s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%' AS too_cloudy, m.status AS measurement_status
            FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
            WHERE s.lake_id = ? ORDER BY s.acquired_at DESC, s.id DESC LIMIT 1""", (lake_id,)).fetchone()
    latest_ok = conn.execute(
        """SELECT m.id AS measurement_id, s.acquired_at, m.extent_ha, s.cloud_fraction, s.file_path
           FROM measurement m JOIN scene s ON s.id = m.scene_id
           WHERE m.lake_id = ? AND m.status = 'ok' ORDER BY s.acquired_at DESC, m.id DESC LIMIT 1""",
        (lake_id,)).fetchone()
    latest_score = conn.execute(
        """SELECT r.status, r.baseline_ha, r.deviation_score, r.scored_at, s.acquired_at, m.extent_ha
           FROM risk_score r JOIN measurement m ON m.id = r.measurement_id JOIN scene s ON s.id = m.scene_id
           WHERE r.lake_id = ? ORDER BY s.acquired_at DESC, r.id DESC LIMIT 1""", (lake_id,)).fetchone()
    days_since_ok = None
    if latest_ok is not None:
        days_since_ok = (today - date.fromisoformat(latest_ok["acquired_at"][:10])).days
    return {
        "counts": dict(counts),
        "latest_scene": _row(latest_scene),
        "latest_ok_measurement": _row(latest_ok),
        "latest_risk_score": _row(latest_score),
        "days_since_last_ok": days_since_ok,
    }


def lake_history(conn: sqlite3.Connection, lake_id: int) -> list[dict[str, Any]]:
    """One row per scene, oldest first: what the satellite saw and what the pipeline did with it."""
    rows = conn.execute(
        f"""SELECT s.id AS scene_id, s.source, s.acquired_at, s.cloud_fraction, s.file_path, s.downloaded_at,
                   s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%' AS too_cloudy,
                   m.id AS measurement_id, m.sensor, m.status AS measurement_status, m.extent_ha,
                   r.status AS risk_status, r.baseline_ha, r.deviation_score
            FROM scene s
            LEFT JOIN measurement m ON m.scene_id = s.id
            LEFT JOIN risk_score r ON r.measurement_id = m.id
            WHERE s.lake_id = ? ORDER BY s.acquired_at, s.id""", (lake_id,)).fetchall()
    return [dict(r) for r in rows]


def run_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,))]


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT 1").fetchone())


def database_totals(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for table in ("lake", "scene", "measurement", "risk_score", "run_log"):
        out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    out["too_cloudy"] = conn.execute(
        f"SELECT COUNT(*) FROM scene WHERE file_path LIKE '{NOT_DOWNLOADED_PREFIX}%'").fetchone()[0]
    return out
