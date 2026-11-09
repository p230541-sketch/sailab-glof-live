"""Tests for sailab.radar: the slope calculation, the radar measurement, and the known real failure."""
from math import atan, degrees, floor

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab.radar import measure_radar_scene, slope_degrees

KARAMBAR = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0}
ORIGINAL_SAR = "tests/data/KarambarLake_Sentinel1_SAR_RAW.tif"
KRB_DEM = "data/dem/KRB_dem.tif"


# --- slope ---------------------------------------------------------------------------------------
def test_slope_of_a_flat_surface_is_zero():
    assert np.allclose(slope_degrees(np.full((5, 5), 4262.0), 10.0), 0.0)


def test_slope_of_a_plane_rising_1_m_per_10_m_cell():
    """z rises 1 m per 10 m east: tan(slope) = 0.1, slope = atan(0.1) = 5.7106 degrees, everywhere."""
    dem = np.tile(np.arange(6, dtype=float), (4, 1))
    assert np.allclose(slope_degrees(dem, 10.0), degrees(atan(0.1)))


def test_slope_of_a_diagonal_plane():
    """z rises 1 m per cell east AND 1 m per cell south: tan(slope) = hypot(0.1, 0.1) = 0.14142."""
    r, c = np.mgrid[0:5, 0:5]
    assert np.allclose(slope_degrees((r + c).astype(float), 10.0), degrees(atan(np.hypot(0.1, 0.1))))


# --- synthetic radar window ---------------------------------------------------------------------
def write_sar(path, vv):
    rows, cols = vv.shape
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [KARAMBAR["centre_lon"]], [KARAMBAR["centre_lat"]])
    x0, y0 = floor(xs[0] / 10) * 10 - (cols // 2) * 10, floor(ys[0] / 10) * 10 + (rows // 2 + 1) * 10
    with rasterio.open(path, "w", driver="GTiff", width=cols, height=rows, count=1, dtype="float64",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(vv, 1)
        dst.set_band_description(1, "VV")


def synthetic_valley():
    """40x40: lake 6x6 at -20 dB in the middle; a flat valley floor at -15 dB joined to it on the east;
    bright mountain at -5 dB on the west half of the top; the rest -15 dB valley floor."""
    vv = np.full((40, 40), -15.0)
    vv[:10, :] = -5.0                      # bright mountain face (steep)
    vv[17:23, 17:23] = -20.0               # the lake (36 px)
    slope = np.zeros((40, 40)); slope[:10, :] = 35.0
    return vv, slope


def test_without_the_slope_mask_the_valley_floor_floods_in(tmp_path):
    """Whole-window Otsu splits mountain (-5) from everything else, so the -15 dB valley counts as water and
    the region reaches the window edge: refused, as on the real Karambar file."""
    vv, _ = synthetic_valley()
    write_sar(tmp_path / "s.tif", vv)
    vv_nd = vv.copy(); vv_nd[39, :] = np.nan    # an edge row of no-data, like the real exports
    write_sar(tmp_path / "s.tif", vv_nd)
    o = measure_radar_scene(tmp_path / "s.tif", KARAMBAR)
    assert o.status == "insufficient_observation" and "borders no-data" in o.reason


def test_with_the_slope_mask_otsu_separates_lake_from_valley(tmp_path):
    """Mountain removed first: Otsu now splits -20 (lake) from -15 (valley): only the 36-px lake remains."""
    vv, slope = synthetic_valley()
    vv[39, :] = np.nan
    write_sar(tmp_path / "s.tif", vv)
    o = measure_radar_scene(tmp_path / "s.tif", KARAMBAR, slope, 10.0)
    assert o.status == "ok" and o.extent_ha == pytest.approx(36 * 100 / 10_000)
    assert -20.0 < o.threshold_db < -15.0
    assert o.masked_steep_px == 400                      # the 10x40 mountain band


def test_a_centre_that_is_not_dark_is_refused(tmp_path):
    vv, slope = synthetic_valley()
    vv[17:23, 17:23] = -15.0                             # lake gone (e.g. frozen and bright, or no lake)
    write_sar(tmp_path / "s.tif", vv)
    o = measure_radar_scene(tmp_path / "s.tif", KARAMBAR, slope, 10.0)
    assert o.status == "insufficient_observation"


def test_slope_mask_needs_a_matching_grid(tmp_path):
    vv, _ = synthetic_valley()
    write_sar(tmp_path / "s.tif", vv)
    with pytest.raises(ValueError):
        measure_radar_scene(tmp_path / "s.tif", KARAMBAR, np.zeros((3, 3)), 10.0)


# --- the real original Karambar SAR file -----------------------------------------------------------
def load_slope():
    with rasterio.open(KRB_DEM) as s:
        dem = s.read(1).astype(float)
    dem[~np.isfinite(dem)] = np.nan
    return slope_degrees(dem, 10.0)


def test_real_karambar_sar_known_failure_is_still_visible():
    """The original method (no mask) still leaks: 97,571 px grown from the georeferenced centre
    (97,588 px = 975.88 ha with the original rows//2 seed, the documented 975.9 ha). The region reaches the
    window edge, so the pipeline refuses it instead of reporting 975.7 ha."""
    o = measure_radar_scene(ORIGINAL_SAR, KARAMBAR)
    assert o.status == "insufficient_observation"
    assert "lake region (97571 px) borders no-data" in o.reason
    assert o.threshold_db == pytest.approx(-9.529, abs=0.001)


def test_real_karambar_sar_with_the_slope_mask():
    """Slope > 10 deg removed before Otsu: threshold -15.32 dB, region 26,752 px = 267.52 ha, not touching
    the edge (logs/2026-11-09_radar_slope_mask_original_karambar.log)."""
    o = measure_radar_scene(ORIGINAL_SAR, KARAMBAR, load_slope(), 10.0)
    assert o.status == "ok"
    assert o.extent_ha == pytest.approx(267.52)
    assert o.threshold_db == pytest.approx(-15.32, abs=0.01)
