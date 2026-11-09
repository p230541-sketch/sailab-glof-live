"""The radar (Sentinel-1) path through the real run_pipeline_once, with Earth Engine replaced by a fake.

Synthetic radar window (40x40, 10 m): lake 6x6 = 36 px = 0.36 ha at -20 dB, valley floor -15 dB,
steep bright mountain band (rows 0-9, slope 35 deg) at -5 dB. With the 10-degree slope mask the radar
measurement is exactly the 36-px lake (see tests/test_radar.py).
"""
from datetime import date
from math import floor

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import db, pipeline
from sailab.earth_engine_client import SceneInfo


def _grid(lake, rows=40, cols=40):
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lake["centre_lon"]], [lake["centre_lat"]])
    return from_origin(floor(xs[0] / 10) * 10 - (cols // 2) * 10, floor(ys[0] / 10) * 10 + (rows // 2 + 1) * 10, 10, 10)


def write_radar(path, lake):
    vv = np.full((40, 40), -15.0, dtype=np.float32)
    vv[:10, :] = -5.0
    vv[17:23, 17:23] = -20.0
    vv[39, :] = np.nan                                  # edge sliver, like real exports
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=40, height=40, count=2, dtype="float32",
                       crs="EPSG:32643", transform=_grid(lake)) as dst:
        dst.write(np.stack([vv, vv - 7]))
        dst.set_band_description(1, "VV"); dst.set_band_description(2, "VH")


def write_dem(path, lake, rows=40):
    """Rows 0-9 rise 6.2 m per 10 m (tan 35 deg ~ 0.70 -> 7 m per cell); the rest flat at 4262 m."""
    dem = np.full((rows, 40), 4262.0, dtype=np.float32)
    for r in range(10):
        dem[r, :] = 4262.0 + (10 - r) * 7.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=40, height=rows, count=1, dtype="float32",
                       crs="EPSG:32643", transform=_grid(lake, rows=rows)) as dst:
        dst.write(dem, 1)


def s1(code, day, n=1):
    return SceneInfo(f"S1A_IW_GRDH_{day.replace('-', '')}_{n}", code, f"{day}T13:05:17+00:00", None, None, "sentinel-1")


class FakeRadarClient:
    def __init__(self, radar=None, dem_rows=40):
        self.radar, self.dem_rows = radar or {}, dem_rows
        self.radar_calls, self.dem_downloads = [], 0

    def find_new_scenes(self, lake, since, until=None):
        return []

    def find_new_s1_scenes(self, lake, since, until=None):
        self.radar_calls.append((lake["code"], since))
        return [s for s in self.radar.get(lake["code"], []) if date.fromisoformat(s.acquired_at[:10]) > since]

    def download_s1_window(self, scene, lake, out_path):
        write_radar(out_path, lake)

    def download_dem_window(self, lake, out_path):
        self.dem_downloads += 1
        write_dem(out_path, lake, self.dem_rows)


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "sailab_glof.db"
    conn = db.connect(db_path); db.seed_lakes(conn); conn.close()
    return tmp_path, db_path


def run(repo, client, since=date(2026, 7, 1)):
    tmp_path, db_path = repo
    return pipeline.run_pipeline_once(db_path, tmp_path / "data" / "scenes", since, client=client,
                                      dem_dir=tmp_path / "dem")


def rows(db_path, sql):
    c = db.connect(db_path)
    out = [dict(r) for r in c.execute(sql)]
    c.close()
    return out


def test_a_radar_pass_is_downloaded_measured_and_stored_as_radar(repo):
    client = FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]})
    result = run(repo, client)
    _, db_path = repo
    assert result.errors is None
    [scene] = rows(db_path, "SELECT * FROM scene")
    assert (scene["source"], scene["cloud_fraction"]) == ("sentinel-1", None)
    [m] = rows(db_path, "SELECT * FROM measurement")
    assert (m["sensor"], m["status"]) == ("radar", "ok")
    assert m["extent_ha"] == pytest.approx(0.36)
    assert client.dem_downloads == 1                                     # DEM fetched once, then reused


def test_the_dem_is_reused_once_stored(repo):
    tmp_path, _ = repo
    write_dem(tmp_path / "dem" / "KRB_dem.tif", {"centre_lon": 73.7053229, "centre_lat": 36.880833})
    client = FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]})
    run(repo, client)
    assert client.dem_downloads == 0


def test_a_dem_on_a_different_grid_refuses_the_measurement(repo):
    client = FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]}, dem_rows=35)
    run(repo, client)
    _, db_path = repo
    [m] = rows(db_path, "SELECT * FROM measurement")
    assert (m["status"], m["extent_ha"]) == ("insufficient_observation", None)


def _add(db_path, sensor, day, extent):
    c = db.connect(db_path)
    source = "sentinel-2" if sensor == "optical" else "sentinel-1"
    sid = db.insert_scene(c, 1, source, day, 5.0 if sensor == "optical" else None, f"history/{sensor}/{day}.tif")
    db.insert_measurement(c, sid, 1, sensor, extent, "ok")
    c.close()


JULYS = ["2023-07-10", "2023-07-25", "2024-07-18", "2025-07-10", "2025-07-25"]


def test_radar_measurements_get_no_risk_score_while_scoring_is_off(repo):
    """Radar scoring is off (pipeline.SCORE_RADAR = False, 2026-11-09): the radar pass is measured, but no
    risk_score row is written for it, even with plenty of radar history."""
    _, db_path = repo
    for d, v in zip(JULYS, [0.30, 0.40, 0.36, 0.32, 0.42]):
        _add(db_path, "radar", d, v)
    assert pipeline.SCORE_RADAR is False
    run(repo, FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]}))
    [m] = rows(db_path, "SELECT * FROM measurement m JOIN scene s ON s.id = m.scene_id WHERE s.acquired_at LIKE '2026-07-18%'")
    assert (m["sensor"], m["status"]) == ("radar", "ok")
    assert rows(db_path, "SELECT * FROM risk_score") == []


def test_if_radar_scoring_is_switched_on_it_uses_radar_history_only(repo, monkeypatch):
    """Kept for when a melt-season check exists: radar July values 0.30, 0.40, 0.36, 0.32, 0.42 (mean 0.36);
    optical July values of 9.0 ha must be ignored. New radar value 0.36 -> baseline 0.36, score 0.0."""
    monkeypatch.setattr(pipeline, "SCORE_RADAR", True)
    _, db_path = repo
    for d, v in zip(JULYS, [0.30, 0.40, 0.36, 0.32, 0.42]):
        _add(db_path, "radar", d, v)
    for d in JULYS:
        _add(db_path, "optical", d, 9.0)
    run(repo, FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]}))
    [r] = rows(db_path, "SELECT r.* FROM risk_score r JOIN measurement m ON m.id = r.measurement_id WHERE m.sensor = 'radar'")
    assert r["status"] == "ok"
    assert r["baseline_ha"] == pytest.approx(0.36)
    assert r["deviation_score"] == pytest.approx(0.0, abs=1e-9)


def test_if_radar_scoring_is_switched_on_optical_history_is_not_used(repo, monkeypatch):
    monkeypatch.setattr(pipeline, "SCORE_RADAR", True)
    _, db_path = repo
    for d in JULYS:
        _add(db_path, "optical", d, 0.36)
    run(repo, FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]}))
    [r] = rows(db_path, "SELECT r.status FROM risk_score r JOIN measurement m ON m.id = r.measurement_id WHERE m.sensor = 'radar'")
    assert r["status"] == "insufficient_history"


def test_optical_history_ignores_radar_rows(repo):
    _, db_path = repo
    for d in JULYS:
        _add(db_path, "radar", d, 9.0)
    c = db.connect(db_path)
    assert db.get_extent_history(c, 1, sensor="optical") == []
    assert len(db.get_extent_history(c, 1, sensor="radar")) == 5
    assert len(db.get_extent_history(c, 1)) == 5                         # no filter: every sensor
    c.close()


def test_radar_listing_starts_from_the_newest_radar_scene_not_the_newest_optical_one(repo):
    _, db_path = repo
    _add(db_path, "optical", "2026-10-21", 250.0)                       # newest optical
    _add(db_path, "radar", "2026-08-01", 240.0)                         # newest radar is older
    client = FakeRadarClient({})
    run(repo, client)
    assert ("KRB", date(2026, 7, 31)) in client.radar_calls              # day before the newest RADAR scene


def test_a_radar_pass_already_stored_is_not_downloaded_again(repo):
    client = FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]})
    run(repo, client)
    run(repo, FakeRadarClient({"KRB": [s1("KRB", "2026-07-18")]}))
    _, db_path = repo
    assert len(rows(db_path, "SELECT * FROM scene")) == 1
