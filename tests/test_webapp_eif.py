"""The new score (Extended Isolation Forest) on the dashboard and the lake page: shown with its reason,
next to the old z-score, and the dashboard ranked by it."""
from __future__ import annotations

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import TODAY
from sailab import db
from webapp.main import create_app


def text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _add_eif(source_db, lake_id: int, day: str, score: float | None, reason: str | None):
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    scene = db.insert_scene(conn, lake_id, "sentinel-2", f"{day}T05:58:58+00:00", 1.0, f"data/scenes/X/{day}-{lake_id}.tif")
    m = db.insert_measurement(conn, scene, lake_id, "optical", 200.0, "ok")
    status = "ok" if score is not None else "insufficient_history"
    db.insert_risk_score(conn, lake_id, m, db.RISK_METHOD_EIF, status, 190.0, 0.7 if score is not None else None,
                         score_0_100=score, reason=reason)
    conn.close()


@pytest.fixture
def make_client(source_db, tmp_path):
    def make():
        return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                     repo=tmp_path / "repo"))
    return make


def test_dashboard_shows_the_new_score_and_its_reason(source_db, make_client):
    _add_eif(source_db, 1, "2026-08-20", 64.3, "Area 200.0 ha is 25% above the usual 160.0 ha for August.")
    page = text(make_client().get("/").text)
    assert "New score (Extended Isolation Forest): 64.3 / 100" in page
    assert "25% above the usual 160.0 ha for August" in page


def test_dashboard_ranks_lakes_by_the_new_score(source_db, make_client):
    _add_eif(source_db, 1, "2026-08-20", 12.0, "Karambar reason.")
    _add_eif(source_db, 2, "2026-08-20", 80.0, "Atro Sar reason.")
    page = text(make_client().get("/").text)
    assert page.index("Atro Sar reason.") < page.index("Karambar reason.")      # 80 before 12


def test_a_lake_without_a_new_score_comes_last_and_says_so(source_db, make_client):
    _add_eif(source_db, 2, "2026-08-20", 5.0, "Atro Sar reason.")
    page = text(make_client().get("/").text)
    assert page.index("Atro Sar reason.") < page.index("not computed yet")


def test_lake_page_shows_the_new_score_next_to_the_old_one(source_db, make_client):
    _add_eif(source_db, 1, "2026-08-20", 64.3, "Area 200.0 ha is 25% above the usual 160.0 ha for August.")
    page = text(make_client().get("/lakes/KRB").text)
    assert "Deviation score" in page or "Insufficient history" in page          # the old z-score section is still there
    assert "New score: Extended Isolation Forest (optical)" in page
    assert "64.3 / 100" in page and "25% above the usual 160.0 ha for August" in page


def test_lake_page_says_when_the_new_score_had_too_little_history(source_db, make_client):
    _add_eif(source_db, 2, "2026-08-20", None, None)
    page = text(make_client().get("/lakes/ATS").text)
    assert "too little history to score yet" in page
