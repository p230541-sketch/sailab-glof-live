"""Persistent storage (SQLite) for the Acquisition, Measurement and Risk Scoring stages.

A minimal subset of the project's 16-table data model: only the five tables
these three stages actually read or write. SQLite is a single file, so it can
be committed back to the repository by the scheduled GitHub Actions run, which
gives a public, timestamped history of every row the pipeline has written.

Every insert commits immediately. That is deliberate: if a run crashes part way
through, everything written before the crash is already on disk, which is what
lets the next run resume instead of redoing completed work (FR-04).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from sailab.risk import ExtentRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS lake (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    centre_lon REAL NOT NULL,
    centre_lat REAL NOT NULL,
    boundary_radius_m REAL NOT NULL,
    growth_distance_limit_m REAL NOT NULL DEFAULT 2500
);

CREATE TABLE IF NOT EXISTS scene (
    id INTEGER PRIMARY KEY,
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    source TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    cloud_fraction REAL,
    file_path TEXT NOT NULL,
    downloaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurement (
    id INTEGER PRIMARY KEY,
    scene_id INTEGER NOT NULL UNIQUE REFERENCES scene(id),
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    sensor TEXT NOT NULL,
    extent_ha REAL,
    status TEXT NOT NULL,
    measured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_score (
    id INTEGER PRIMARY KEY,
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    measurement_id INTEGER NOT NULL REFERENCES measurement(id),
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    baseline_ha REAL,
    deviation_score REAL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    lakes_processed INTEGER NOT NULL DEFAULT 0,
    scenes_downloaded INTEGER NOT NULL DEFAULT 0,
    errors TEXT
);
"""

SCENE_SOURCES = ("sentinel-2", "sentinel-1")
SENSORS = ("optical", "radar")
MEASUREMENT_STATUSES = ("ok", "insufficient_observation")
RISK_STATUSES = ("ok", "insufficient_history")
# The score in risk.py is a z-score against the same calendar month in earlier years. Until 2026-11-11 it
# was saved under the name "anomaly_detector", which described a method this code never was.
# migrate() renames the old rows; the numbers are not touched.
RISK_METHOD_SEASONAL_ZSCORE = "seasonal_zscore"
OLD_RISK_METHOD_NAMES = {"anomaly_detector": RISK_METHOD_SEASONAL_ZSCORE}
RISK_METHODS = (RISK_METHOD_SEASONAL_ZSCORE,)

# The two lakes this build starts with. These are the literal values the
# project's existing real results (Karambar 237.2 ha, Atro Sar 76.51 ha) were
# computed from. They must not be "corrected" or rounded: new measurements are
# only comparable with the old ones if they use exactly these coordinates.
#
# Source check (2026-11-11): the centres have no recorded origin, so they were checked against the
# HMA Glacial Lake Inventory (Hi-MAG), Version 2.0, September 2020 (Chen, Zhang, Guo, Allen, Kargel,
# Haritashya, Watson). Karambar is 0.144 km from Hi-MAG lake GL073703E36879N (248.6 ha in 2017) and
# Atro Sar is 0.408 km from GL073645E36644N (98.2 ha in 2017). Hi-MAG is a check, not the origin.
# Details: logs/2026-11-11_lake_coordinates_vs_himag.md
SEED_LAKES = (
    {
        "code": "KRB",
        "name": "Karambar Lake",
        "centre_lon": 73.7053229,
        "centre_lat": 36.880833,
        "boundary_radius_m": 2500.0,
        "growth_distance_limit_m": 2500.0,
    },
    {
        # Centre unchanged. Window and growth limit changed on 2026-11-08 from 800 m / 1200 m to
        # 1500 m / 1500 m, agreed with the project owner: the original 800 m export cut the lake off
        # at the window's left edge (76.51 ha was only the part inside the window), and 1200 m growth
        # also stopped short (98.47 ha). On the same 2026-07-18 scene, radii of 1500, 2000 and 2500 m
        # all give 105.82 ha. Evidence: logs/2026-11-08_step5_atro_sar_radius_check.log
        "code": "ATS",
        "name": "Atro Sar",
        "centre_lon": 73.65037,
        "centre_lat": 36.64458,
        "boundary_radius_m": 1500.0,
        "growth_distance_limit_m": 1500.0,
    },
)


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string, to the second (e.g. 2026-11-07T06:00:12+00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database file and make sure every table exists."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores REFERENCES unless this is on
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Bring an older database up to date without losing data. Safe to run every time.

    Returns how many rows were changed (0 when the database is already up to date).
    Step 1 (2026-11-11): rename old risk method labels to what the code really is.
    """
    changed = 0
    for old_name, new_name in OLD_RISK_METHOD_NAMES.items():
        cursor = conn.execute("UPDATE risk_score SET method = ? WHERE method = ?", (new_name, old_name))
        changed += cursor.rowcount
    conn.commit()
    return changed


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------
def insert_lake(conn: sqlite3.Connection, code: str, name: str, centre_lon: float, centre_lat: float,
                boundary_radius_m: float, growth_distance_limit_m: float = 2500.0) -> int:
    if not (-180.0 <= centre_lon <= 180.0) or not (-90.0 <= centre_lat <= 90.0):
        raise ValueError(f"lake {code}: coordinates out of range (lon={centre_lon}, lat={centre_lat})")
    cursor = conn.execute(
        "INSERT INTO lake (code, name, centre_lon, centre_lat, boundary_radius_m, growth_distance_limit_m) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code, name, centre_lon, centre_lat, boundary_radius_m, growth_distance_limit_m),
    )
    conn.commit()
    return cursor.lastrowid


def insert_scene(conn: sqlite3.Connection, lake_id: int, source: str, acquired_at: str,
                 cloud_fraction: float | None, file_path: str, downloaded_at: str | None = None) -> int:
    if source not in SCENE_SOURCES:
        raise ValueError(f"scene source must be one of {SCENE_SOURCES}, got {source!r}")
    date.fromisoformat(acquired_at[:10])  # raises ValueError if acquired_at is not an ISO date
    cursor = conn.execute(
        "INSERT INTO scene (lake_id, source, acquired_at, cloud_fraction, file_path, downloaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (lake_id, source, acquired_at, cloud_fraction, file_path, downloaded_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def insert_measurement(conn: sqlite3.Connection, scene_id: int, lake_id: int, sensor: str,
                       extent_ha: float | None, status: str, measured_at: str | None = None) -> int:
    """Insert one lake-extent measurement.

    extent_ha must be None exactly when status is 'insufficient_observation':
    a failed measurement is recorded as missing, never as an invented zero.
    """
    if sensor not in SENSORS:
        raise ValueError(f"sensor must be one of {SENSORS}, got {sensor!r}")
    if status not in MEASUREMENT_STATUSES:
        raise ValueError(f"measurement status must be one of {MEASUREMENT_STATUSES}, got {status!r}")
    if status == "ok" and extent_ha is None:
        raise ValueError("status 'ok' needs an extent_ha value")
    if status == "insufficient_observation" and extent_ha is not None:
        raise ValueError("status 'insufficient_observation' must have extent_ha = None, not a number")
    cursor = conn.execute(
        "INSERT INTO measurement (scene_id, lake_id, sensor, extent_ha, status, measured_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scene_id, lake_id, sensor, extent_ha, status, measured_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def insert_risk_score(conn: sqlite3.Connection, lake_id: int, measurement_id: int, method: str, status: str,
                      baseline_ha: float | None, deviation_score: float | None,
                      scored_at: str | None = None) -> int:
    if method not in RISK_METHODS:
        raise ValueError(f"risk method must be one of {RISK_METHODS}, got {method!r}")
    if status not in RISK_STATUSES:
        raise ValueError(f"risk status must be one of {RISK_STATUSES}, got {status!r}")
    cursor = conn.execute(
        "INSERT INTO risk_score (lake_id, measurement_id, method, status, baseline_ha, deviation_score, scored_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lake_id, measurement_id, method, status, baseline_ha, deviation_score, scored_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_extent_history(conn: sqlite3.Connection, lake_id: int,
                       exclude_measurement_id: int | None = None, sensor: str | None = None) -> list[ExtentRecord]:
    """Every usable past extent of a lake, oldest first, ready for score_against_seasonal_baseline().

    - observed_on is the satellite pass date (scene.acquired_at), not when the
      pipeline happened to process it, since the seasonal baseline is about
      what month the lake was seen in.
    - Measurements with status 'insufficient_observation' are left out: they
      have no extent, and treating them as zero would drag the baseline down.
    - exclude_measurement_id lets the caller leave out the measurement it is
      about to score, so a new value is never compared against itself.
    - sensor ('optical' or 'radar') keeps the two sensors' baselines apart: they measure the same
      lake slightly differently, and mixing them would create false "change" scores.
    """
    rows = conn.execute(
        "SELECT m.id, s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
        "WHERE m.lake_id = ? AND m.status = 'ok' AND (? IS NULL OR m.sensor = ?) ORDER BY s.acquired_at, m.id",
        (lake_id, sensor, sensor),
    ).fetchall()
    return [
        ExtentRecord(observed_on=date.fromisoformat(row["acquired_at"][:10]), extent_ha=row["extent_ha"])
        for row in rows
        if row["id"] != exclude_measurement_id
    ]


def get_lakes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM lake ORDER BY id").fetchall()


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------
def start_run_log(conn: sqlite3.Connection, started_at: str | None = None) -> int:
    cursor = conn.execute("INSERT INTO run_log (started_at) VALUES (?)", (started_at or utc_now_iso(),))
    conn.commit()
    return cursor.lastrowid


def finish_run_log(conn: sqlite3.Connection, run_id: int, lakes_processed: int, scenes_downloaded: int,
                   errors: str | None = None, finished_at: str | None = None) -> None:
    """Close a run. errors is the real error text (None only for a genuinely clean run)."""
    cursor = conn.execute(
        "UPDATE run_log SET finished_at = ?, lakes_processed = ?, scenes_downloaded = ?, errors = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (finished_at or utc_now_iso(), lakes_processed, scenes_downloaded, errors, run_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        raise ValueError(f"run_log {run_id} does not exist or was already finished")


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def seed_lakes(conn: sqlite3.Connection) -> list[int]:
    """Insert the two seed lakes if missing. Safe to run every time.

    If a lake with the same code already exists with different values, this
    raises rather than silently keeping either version, because a changed
    coordinate would make new measurements incomparable with old ones.
    """
    ids: list[int] = []
    for lake in SEED_LAKES:
        existing = conn.execute("SELECT * FROM lake WHERE code = ?", (lake["code"],)).fetchone()
        if existing is None:
            ids.append(insert_lake(conn, **lake))
            continue
        mismatched = {key: (existing[key], value) for key, value in lake.items() if existing[key] != value}
        if mismatched:
            raise ValueError(f"lake {lake['code']} already stored with different values (stored, seed): {mismatched}")
        ids.append(existing["id"])
    return ids
