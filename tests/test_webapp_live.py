"""The live-check button: the three outcomes, run through the REAL run_pipeline_once with only Earth Engine
replaced by a fake client (the real Earth Engine runs are recorded in logs/, not here).

Database: the temporary one from conftest.py. Its newest KRB scene is 2026-10-21; ATS has none.
"""
import hashlib
import sqlite3
import threading
from datetime import date
from math import floor

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import pipeline
from sailab.earth_engine_client import EarthEngineError, SceneInfo
from webapp.main import create_app

TODAY = date(2026, 11, 9)


def write_window(path, lake):
    """6-band, 30x30, 10 m window with a 5x5 water block at the lake centre (0.25 ha)."""
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lake["centre_lon"]], [lake["centre_lat"]])
    x0, y0 = floor(xs[0] / 10) * 10 - 150, floor(ys[0] / 10) * 10 + 160
    green = np.full((30, 30), 100, np.uint16); nir = np.full((30, 30), 300, np.uint16)
    green[13:18, 13:18], nir[13:18, 13:18] = 300, 50
    scl = np.where(green == 300, 6, 5).astype(np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=30, height=30, count=6, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(np.stack([green, green, green, nir, nir, scl]))


class FakeEarthEngine:
    def __init__(self, scenes=None, fail=None):
        self.scenes, self.fail = scenes or {}, fail

    def find_new_scenes(self, lake, since_date, until_date=None):
        if self.fail:
            raise EarthEngineError(self.fail)
        return [s for s in self.scenes.get(lake["code"], []) if date.fromisoformat(s.acquired_at[:10]) > since_date]

    def download_scene_window(self, scene, lake, out_path):
        write_window(out_path, lake)


def runner_with(fake):
    return lambda db_path, data_dir, since: pipeline.run_pipeline_once(db_path, data_dir, since, client=fake)


def make(source_db, tmp_path, runner):
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo", live_runner=runner))


def check_now(client):
    r = client.post("/live/check", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/live"
    client.app.state.live.wait(30)
    return client.get("/live").text


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


NEW_SCENE = SceneInfo("20261107T054600_X_T43SCA", "KRB", "2026-11-07T05:58:58+00:00", 2.0, 2.0)


# --- outcome 1: a new scene found, downloaded and measured -----------------------------------------
def test_new_scene_is_measured_and_written_to_the_working_copy_only(source_db, tmp_path):
    before = sha(source_db)
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    html = check_now(client)

    assert "1 new scene recorded." in html and "1 downloaded and measured" in html
    assert "ok 0.25" in html                                              # the pipeline's own log line
    assert sha(source_db) == before                                        # published file untouched
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    row = copy.execute("SELECT m.status, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
                       "WHERE s.acquired_at LIKE '2026-11-07%'").fetchone()
    assert row == ("ok", 0.25)
    dashboard = client.get("/").text
    assert "live check, this laptop" in dashboard and "+ 1 live check on this laptop" in dashboard
    assert "0.25 ha on 07 Nov 2026" in dashboard                           # the page now reads the new row
    assert client.get("/lakes/KRB/latest-image.png").status_code == 200   # image found in the live folder


# --- outcome 2: no new scene ---------------------------------------------------------------------
def test_no_new_scene_says_so(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    html = check_now(client)
    assert "No new scene for either lake" in html
    assert client.app.state.live.snapshot()["status"] == "no_new_scene"
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    assert copy.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 3     # the check itself is logged
    assert copy.execute("SELECT COUNT(*) FROM scene").fetchone()[0] == 5      # nothing added


# --- outcome 3: a real failure inside the pipeline ---------------------------------------------------
def test_a_failure_shows_the_real_error_and_is_recorded(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine(fail="Earth Engine memory capacity exceeded.")))
    html = check_now(client)
    assert "The check could not complete." in html
    assert "Earth Engine memory capacity exceeded." in html
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    errors = copy.execute("SELECT errors FROM run_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "memory capacity exceeded" in errors
    # neither the success banner nor the no-new-scene banner may appear for a failed check
    assert "new scene recorded." not in html and "new scenes recorded." not in html
    assert "No new scene for either lake" not in html


def test_a_crash_outside_the_pipeline_is_shown_too(source_db, tmp_path):
    def broken(*_):
        raise OSError("disk full")
    html = check_now(make(source_db, tmp_path, broken))
    assert "The check could not complete." in html and "OSError: disk full" in html


# --- behaviour ---------------------------------------------------------------------------------------
def test_only_one_check_runs_at_a_time_and_the_page_refreshes_meanwhile(source_db, tmp_path):
    release = threading.Event()

    def slow(db_path, data_dir, since):
        release.wait(10)
        return pipeline.run_pipeline_once(db_path, data_dir, since, client=FakeEarthEngine({}))

    client = make(source_db, tmp_path, slow)
    live = client.app.state.live
    assert live.start() is True
    assert live.start() is False                                           # second click while running: ignored
    page = client.get("/live").text
    assert '<meta http-equiv="refresh" content="3">' in page and "Checking both lakes" in page
    release.set(); live.wait(10)
    assert live.snapshot()["status"] == "no_new_scene"
    assert len(live.history) == 1


def test_idle_page_and_no_refresh(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    page = client.get("/live").text
    assert "No live check has run since the app started." in page
    assert "http-equiv=\"refresh\"" not in page


def test_restarting_the_app_forgets_live_checks_with_the_old_copy(source_db, tmp_path):
    first = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    check_now(first)
    second = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))   # same work dir, fresh copy
    assert second.app.state.live.history == []
    assert "live check, this laptop" not in second.get("/").text
    assert "0.25 ha" not in second.get("/").text


# --- the plain-language line on a failed check ------------------------------------------------------
REAL_NETWORK_ERROR = ("EarthEngineError: Earth Engine sign-in failed for sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com: "
                      "ConnectionError: HTTPSConnectionPool(host='oauth2.googleapis.com', port=443): Max retries exceeded with url: "
                      "/token (Caused by ProxyError('Unable to connect to proxy', NewConnectionError(\"HTTPSConnection(host='127.0.0.1', "
                      "port=9): Failed to establish a new connection: [Errno 111] Connection refused\")))")   # captured live, 2026-11-08


@pytest.mark.parametrize("error, expected", [
    (REAL_NETWORK_ERROR, "Could not reach Google's servers"),
    ("EarthEngineError: Too many concurrent aggregations.", "usage limit"),
    ("EarthEngineError: download HTTP 429: quota", "usage limit"),
    ("EarthEngineError: sign-in failed: invalid_grant: Invalid JWT Signature.", "refused the sign-in"),
    ("EEException: Permission 'earthengine.thumbnails.create' denied", "denied permission"),
    ("EarthEngineError: no service-account key: EE_SERVICE_ACCOUNT_KEY is unset", "No Earth Engine key"),
    ("OSError: disk full", "The pipeline reported an error."),
])
def test_failure_explanations_are_chosen_from_the_real_error(error, expected):
    from webapp.live import explain_error
    assert expected in explain_error(error)


def test_failed_page_leads_with_the_plain_line_and_keeps_the_exact_error(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine(fail="Too many concurrent aggregations.")))
    html = check_now(client)
    assert "usage limit" in html and "It stopped after" in html
    assert "Technical details: the exact error" in html and "Too many concurrent aggregations." in html
