"""Tests for the Dashboard and Lake Detail pages and the offline charts.

Uses the temporary database from conftest.py (KRB: 5 scenes, 2 usable at 240.0 and 250.0 ha, one
score +1.50; ATS: no scenes; run 2 failed with "EarthEngineError: quota"). Every expected value below
comes from those rows, so a page that showed anything else would fail.
"""
import re
from datetime import date
from math import floor

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import db
from webapp import charts, images, pages
from webapp.main import create_app

TODAY = date(2026, 11, 9)


def visible_text(html: str) -> str:
    """What a person reading the page sees: tags removed, whitespace collapsed (SVG coordinates are not text)."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture
def client(source_db, tmp_path):
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo"))


def write_lake_window(path, lon, lat, rows=30, cols=30):
    """6-band window with a 5x5 water block (25 px) around the lake centre, as in test_pipeline.py."""
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lon], [lat])
    x0, y0 = floor(xs[0] / 10) * 10 - 150, floor(ys[0] / 10) * 10 + 160
    green = np.full((rows, cols), 100, np.uint16); nir = np.full((rows, cols), 300, np.uint16)
    green[13:18, 13:18], nir[13:18, 13:18] = 300, 50
    scl = np.full((rows, cols), 5, np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=cols, height=rows, count=6, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(np.stack([green, green, green, nir, nir, scl]))


# --- dashboard --------------------------------------------------------------------------------
def test_dashboard_shows_the_real_counts(client):
    html = client.get("/").text
    assert ">2</div>" in html                                      # lakes monitored
    assert ">5</div>" in html                                      # scenes recorded
    assert "40%" in html and "2 of 5 scenes" in html               # too cloudy: 2 of 5
    assert "of 3 downloaded scenes passed every check" in html     # usable measurements: 2 of 3
    assert ">120</div>" in html and "Karambar Lake, 12 Jul 2026" in html
    assert "250.00 ha on 12 Jul 2026, 120 days ago" in html
    assert "No usable measurement yet" in html                     # ATS has none: said in words


def test_dashboard_banners_come_from_the_data(client):
    text = visible_text(client.get("/").text)
    assert "for 2 of 2 lakes (Karambar Lake, Atro Sar)" in text    # both lakes over 7 days without a usable image
    assert "The latest pipeline run (run 2) recorded an error." in text
    assert "EarthEngineError: quota" in text


def test_dashboard_never_shows_the_reference_designs_sample_values(client):
    """The reference screens use sample data (33 lakes, Critical 0.86, advisories). None of it may appear."""
    text = visible_text(client.get("/").text)
    for sample in ("0.86", "Critical", "GL-014", "Hunza", "Advisor", "Sample data"):
        assert sample not in text, sample
    assert not re.search(r"\b33\b", text)


# --- lake detail --------------------------------------------------------------------------------
def test_lake_page_score_and_its_inputs(client):
    html = client.get("/lakes/KRB").text
    assert "Deviation <span class=\"num\">+1.50</span>" in html
    assert "245.00 ha" in html                                     # stored baseline
    assert "Earlier July values</dt><dd>1 from 1 year</dd>" in html   # only 2025-07-10 is an earlier July value


def test_lake_page_observation_log_has_every_scene_newest_first(client):
    html = client.get("/lakes/KRB").text
    html = html[html.index("<h2>Observation log</h2>"):]          # only the log table, not the header or chart
    order = [html.index(d) for d in ("21 Oct 2026", "12 Jul 2026", "15 Aug 2025", "01 Aug 2025", "10 Jul 2025")]
    assert order == sorted(order)
    assert html.count(">Not downloaded: cloud over lake</span>") == 2
    assert html.count(">Refused by quality checks</span>") == 1
    assert html.count(">Usable</span>") == 2


def test_lake_page_marks_unbuilt_panels(client):
    html = client.get("/lakes/KRB").text
    for title in ("Dam and glacier", "Terrain above the lake", "Recent weather", "Sentinel-1 radar"):
        assert f"<h2>{title}</h2>\n  <p>No data: not part of this build.</p>" in html


def test_a_lake_with_no_data_says_so(client):
    html = client.get("/lakes/ATS").text
    assert "None yet" in html and "No scenes recorded for this lake yet." in html
    assert "No risk score has been computed for this lake yet." in html
    assert client.get("/lakes/ATS/latest-image.png").status_code == 404


def test_unknown_lake_is_404(client):
    assert client.get("/lakes/XYZ").status_code == 404


def test_missing_image_file_is_reported_not_faked(client):
    html = client.get("/lakes/KRB").text
    assert "is not on this machine" in html and "data/scenes/KRB/2026-07-12.tif" in html
    r = client.get("/lakes/KRB/latest-image.png")
    assert r.status_code == 404 and "not on this machine" in r.json()["detail"]


def test_image_is_rendered_from_the_stored_file(client, tmp_path):
    write_lake_window(tmp_path / "repo" / "data/scenes/KRB/2026-07-12.tif", 73.7053229, 36.880833)
    r = client.get("/lakes/KRB/latest-image.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "/lakes/KRB/latest-image.png" in client.get("/lakes/KRB").text


def test_recomputed_region_has_the_same_pixel_count_as_the_measurement(tmp_path):
    write_lake_window(tmp_path / "w.tif", 73.7053229, 36.880833)
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0}
    assert images.render_scene_png(tmp_path / "w.tif", lake, tmp_path / "w.png") == 25
    assert (tmp_path / "w.png").is_file()


# --- charts ---------------------------------------------------------------------------------------
def test_sparkline_needs_two_values():
    assert "polyline" not in charts.sparkline([250.0])
    assert "polyline" in charts.sparkline([240.0, 250.0])


def test_extent_chart_draws_only_real_points_and_every_scene(conn):
    from sailab import queries
    history = queries.lake_history(conn, 1)
    svg = charts.extent_chart(history, date(2025, 1, 1), TODAY)
    assert svg.count('class="pt"') == 2                    # the two usable measurements
    assert svg.count('class="baseline"') == 1              # one scored measurement
    assert svg.count('class="tick ') == 5                  # every scene
    # 2025-07-10 and 2026-07-12 are a year apart: not joined by a line
    assert svg.count(f'stroke="{charts.OPTICAL}" stroke-width="1.5"') == 0


def test_extent_chart_with_nothing_usable_says_so():
    svg = charts.extent_chart([], date(2026, 1, 1), TODAY)
    assert "No usable measurement in this period" in svg


def test_location_map_places_both_lakes():
    svg = charts.location_map([
        {"code": "KRB", "name": "Karambar Lake", "centre_lon": 73.7053229, "centre_lat": 36.880833, "data_gap": True, "link": "/lakes/KRB"},
        {"code": "ATS", "name": "Atro Sar", "centre_lon": 73.65037, "centre_lat": 36.64458, "data_gap": False, "link": "/lakes/ATS"}])
    assert "KRB" in svg and "ATS" in svg and 'stroke-dasharray="3 2"' in svg


def test_score_formatting_uses_a_real_minus_sign():
    assert pages.fmt_score(-0.9645) == "−0.96" and pages.fmt_score(1.5) == "+1.50" and pages.fmt_score(None) == "—"
