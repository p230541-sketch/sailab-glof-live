"""sailab/water_index.py (SMBWI, Su et al. 2024, and NDWI with an Otsu cutoff) and the alt_measurement
table, on small made-up pictures with known answers."""
from __future__ import annotations

import numpy as np
import pytest

from sailab import db, pipeline, water_index as wi

# Made-up surface reflectances (0 to 1) for three kinds of ground, band by band.
#                 B2    B3    B8    B8A   B9    B11   B12
WATER = dict(b2=0.08, b3=0.07, b8=0.02, b8a=0.015, b9=0.01, b11=0.005, b12=0.004)
SNOW = dict(b2=0.90, b3=0.88, b8=0.80, b8a=0.75, b9=0.60, b11=0.10, b12=0.08)
ROCK = dict(b2=0.12, b3=0.15, b8=0.25, b8a=0.27, b9=0.20, b11=0.30, b12=0.25)


# --- equation (1) ---------------------------------------------------------------------------------
def test_smbwi_matches_equation_1_worked_by_hand():
    # 0.08 + 2.5*0.07 - 2*(0.02 + 0.015 + 0.01) - 0.005 - 0.004 = 0.08 + 0.175 - 0.09 - 0.009 = 0.156
    assert wi.smbwi(**WATER) == pytest.approx(0.156)


def test_water_scores_above_snow_and_rock():
    assert wi.smbwi(**WATER) > 0 > wi.smbwi(**ROCK)
    assert wi.smbwi(**WATER) > wi.smbwi(**SNOW)


def test_smbwi_works_on_whole_grids():
    grids = {band: np.full((2, 3), value) for band, value in WATER.items()}
    assert np.allclose(wi.smbwi(**grids), 0.156)


def test_ndwi_grid_is_nan_where_there_is_no_data():
    green = np.array([[0.0, 0.3]])
    nir = np.array([[0.0, 0.1]])
    out = wi.ndwi_grid(green, nir)
    assert np.isnan(out[0, 0]) and out[0, 1] == pytest.approx(0.5)


# --- Otsu cutoff ---------------------------------------------------------------------------------
def test_otsu_cutoff_falls_between_water_and_land_and_marks_only_water():
    index = np.array([[0.15, 0.16, -0.3], [0.14, -0.35, -0.32]])
    valid = np.ones_like(index, dtype=bool)
    water, cutoff = wi.water_map_by_otsu(index, valid)
    assert -0.3 < cutoff < 0.14
    assert sorted((p.row, p.col) for p, is_w in water.items() if is_w) == [(0, 0), (0, 1), (1, 0)]


def test_pixels_without_data_are_never_water_and_do_not_move_the_cutoff():
    index = np.array([[0.15, 0.16, -0.3, 99.0]])
    valid = np.array([[True, True, True, False]])
    water, cutoff = wi.water_map_by_otsu(index, valid)
    assert cutoff < 0.15
    assert not water[wi.Pixel(0, 3)]


# --- a whole made-up scene, through the same checks as the NDWI measurement ------------------------
LAKE = {"code": "TST", "centre_lon": 73.70, "centre_lat": 36.88, "boundary_radius_m": 200.0,
        "growth_distance_limit_m": 200.0}


def _write_scene(tmp_path, water_square: slice, snow_rows: slice | None = None):
    """A 41 x 41 picture of rock with a square lake in the middle (stored file + extra-band file), on a
    10 m UTM grid centred on LAKE, written like the real downloads (DN = reflectance x 10000)."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import transform as warp

    size = 41
    (x,), (y,) = warp("EPSG:4326", "EPSG:32643", [LAKE["centre_lon"]], [LAKE["centre_lat"]])
    transform = from_origin(x - size * 5, y + size * 5, 10, 10)
    kind = np.full((size, size), "rock", dtype=object)
    kind[water_square, water_square] = "water"
    if snow_rows is not None:
        kind[snow_rows, :] = "snow"
    table = {"water": WATER, "snow": SNOW, "rock": ROCK}

    def band(name):
        return np.vectorize(lambda k: table[k][name] * wi.REFLECTANCE_SCALE)(kind).astype("uint16")

    scl = np.where(kind == "snow", pipeline.SCL_SNOW_ICE, 4).astype("uint16")   # 4 = vegetation, a harmless class
    stored = [band("b2"), band("b3"), band("b3"), band("b8"), band("b11"), scl]   # B2 B3 B4 B8 B11 SCL
    extra = [band("b8a"), band("b9"), band("b11"), band("b12")]
    paths = []
    for name, layers in (("stored.tif", stored), ("extra.tif", extra)):
        path = tmp_path / name
        with rasterio.open(path, "w", driver="GTiff", width=size, height=size, count=len(layers), dtype="uint16",
                           crs="EPSG:32643", transform=transform) as dst:
            for i, layer in enumerate(layers, start=1):
                dst.write(layer, i)
        paths.append(path)
    return paths


def test_smbwi_measures_a_made_up_lake_exactly(tmp_path):
    stored, extra = _write_scene(tmp_path, slice(15, 26))                    # 11 x 11 water pixels
    outcome = wi.measure_smbwi_otsu(stored, extra, LAKE)
    assert outcome.status == "ok"
    assert outcome.extent_ha == pytest.approx(121 * 100 / 10_000)           # 121 pixels x 100 m2 = 1.21 ha
    assert wi.smbwi(**ROCK) < outcome.cutoff < wi.smbwi(**WATER)


def test_ndwi_with_otsu_measures_the_same_made_up_lake(tmp_path):
    stored, _ = _write_scene(tmp_path, slice(15, 26))
    outcome = wi.measure_ndwi_otsu(stored, LAKE)
    assert outcome.status == "ok" and outcome.extent_ha == pytest.approx(1.21)


def test_snow_touching_the_lake_is_refused_by_the_same_check_c(tmp_path):
    stored, extra = _write_scene(tmp_path, slice(15, 26), snow_rows=slice(26, 28))   # snow right below the lake
    outcome = wi.measure_smbwi_otsu(stored, extra, LAKE)
    assert outcome.status == "insufficient_observation" and outcome.extent_ha is None
    assert "check C" in outcome.reason


def test_an_extra_band_file_on_another_grid_is_refused(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    stored, _ = _write_scene(tmp_path, slice(15, 26))
    wrong = tmp_path / "wrong.tif"
    with rasterio.open(wrong, "w", driver="GTiff", width=10, height=10, count=4, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(0, 0, 10, 10)) as dst:
        dst.write(np.ones((4, 10, 10), dtype="uint16"))
    with pytest.raises(ValueError):
        wi.measure_smbwi_otsu(stored, wrong, LAKE)


# --- the alt_measurement table -----------------------------------------------------------------------
def _measurement(conn):
    lake_id = db.insert_lake(conn, "TST", "Test Lake", 73.0, 36.0, 1000.0)
    scene_id = db.insert_scene(conn, lake_id, "sentinel-2", "2026-07-01T05:59:00+00:00", 1.0, "data/x/a.tif")
    return db.insert_measurement(conn, scene_id, lake_id, "optical", 250.0, "ok")


def test_alt_measurement_is_saved_next_to_the_original_and_can_be_replaced(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    m_id = _measurement(conn)
    db.insert_alt_measurement(conn, m_id, "smbwi_otsu", "ok", 248.0, 0.05)
    db.insert_alt_measurement(conn, m_id, "smbwi_otsu", "ok", 247.5, 0.04)   # measured again: replaced, not doubled
    db.insert_alt_measurement(conn, m_id, "ndwi_otsu", "insufficient_observation", None, 0.3)
    rows = conn.execute("SELECT method, status, extent_ha, cutoff FROM alt_measurement ORDER BY method").fetchall()
    assert [tuple(r) for r in rows] == [("ndwi_otsu", "insufficient_observation", None, 0.3),
                                        ("smbwi_otsu", "ok", 247.5, 0.04)]
    assert conn.execute("SELECT extent_ha FROM measurement").fetchone()[0] == 250.0      # the original is untouched


def test_alt_measurement_keeps_the_no_invented_zero_rule(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    m_id = _measurement(conn)
    with pytest.raises(ValueError):
        db.insert_alt_measurement(conn, m_id, "smbwi_otsu", "ok", None, 0.1)
    with pytest.raises(ValueError):
        db.insert_alt_measurement(conn, m_id, "smbwi_otsu", "insufficient_observation", 0.0, 0.1)
    with pytest.raises(ValueError):
        db.insert_alt_measurement(conn, m_id, "made_up_method", "ok", 1.0, 0.1)
