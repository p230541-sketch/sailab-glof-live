"""scripts/redownload_stored_scenes.py: the parts that need no Earth Engine connection."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sailab import db

_SPEC = importlib.util.spec_from_file_location(
    "sailab_redownload", Path(__file__).resolve().parent.parent / "scripts" / "redownload_stored_scenes.py")
redownload = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(redownload)

SHA_A = "a" * 64
SHA_B = "b" * 64


def test_fingerprints_are_read_from_run_logs_and_the_newest_log_wins(tmp_path):
    (tmp_path / "2026-11-08T100000Z.log").write_text(
        f"x INFO sailab.pipeline: KRB s1: downloaded data/backfill/KRB/s1.tif sha256={SHA_A}\n"
        "x INFO sailab.pipeline: a line with no fingerprint\n")
    (tmp_path / "2026-11-08T110000Z.log").write_text(
        f"x INFO sailab.pipeline: KRB s1: downloaded data/backfill/KRB/s1.tif sha256={SHA_B}\n"
        f"x INFO sailab.pipeline: ATS s2: downloaded data\\backfill\\ATS\\s2.tif sha256={SHA_A}\n")
    assert redownload.expected_checksums(tmp_path) == {
        "data/backfill/KRB/s1.tif": SHA_B,        # downloaded twice: the later run's file is the one stored
        "data/backfill/ATS/s2.tif": SHA_A,        # a Windows-style path is matched with forward slashes
    }


def test_too_cloudy_scenes_are_not_in_the_download_list(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 1000.0)
    db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-01T05:59:00+00:00", 80.0, "not_downloaded/TST/cloudy")
    db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-06T05:59:00+00:00", 1.0, "data/backfill/TST/clear.tif")
    db.insert_scene(conn, lake_id, "sentinel-1", "2026-07-03T13:05:00+00:00", None, "data/backfill/TST/radar.tif")
    paths = [row["file_path"] for row in redownload.stored_scenes(conn)]
    assert paths == ["data/backfill/TST/radar.tif", "data/backfill/TST/clear.tif"]


def test_verdict_says_same_different_or_unknown():
    assert redownload.verdict_for(SHA_A, SHA_A) == "same file"
    assert redownload.verdict_for(SHA_A, SHA_B) == "DIFFERENT file"
    assert redownload.verdict_for(SHA_A, None) == "no fingerprint on record"
