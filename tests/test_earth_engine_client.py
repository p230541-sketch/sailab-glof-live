"""Offline tests for sailab.earth_engine_client.

What these DO cover: the pure logic (UTM zone, window grid, lake-circle mask,
lake-window cloud count, date range), how find_new_scenes builds its AOI and
assembles results, and that every failure path raises instead of returning [].

What these CANNOT cover (only a live run can): that the service-account key is
accepted, that Earth Engine returns the scenes and SCL pixels we expect, and
quota/network behaviour. Those are checked by the live run logs in logs/.
"""
from datetime import date
from unittest import mock

import numpy as np
import pytest

from sailab import earth_engine_client as eec
from sailab.acquisition import choose_sensor

KARAMBAR = {"code": "KRB", "centre_lon": 73.7053229, "centre_lat": 36.880833, "boundary_radius_m": 2500.0}


# --- utm_epsg --------------------------------------------------------------
@pytest.mark.parametrize("lon, lat, expected", [
    (73.7053229, 36.880833, 32643),   # Karambar: UTM 43N, matching the T43SCA tile Earth Engine returned
    (73.65037, 36.64458, 32643),      # Atro Sar: also 43N
    (-0.1, 51.5, 32630),              # London: 30N
    (151.2, -33.9, 32756),            # Sydney: 56S
    (180.0, 0.0, 32660),              # the antimeridian edge stays in zone 60, not a non-existent zone 61
])
def test_utm_epsg(lon, lat, expected):
    assert eec.utm_epsg(lon, lat) == expected


# --- window_grid -----------------------------------------------------------
def test_window_grid_hand_calculated():
    """Centre (300095, 4099955), radius 100 m, 10 m pixels, 60 m alignment:
    x0 = floor(299995/60)*60 = 299940;  y0 = ceil(4100055/60)*60 = 4100100
    width = ceil((300195-299940)/10) = 26;  height = ceil((4100100-4099855)/10) = 25
    centre_col = (300095-299940)/10 = 15.5;  centre_row = (4100100-4099955)/10 = 14.5"""
    grid = eec.window_grid(32643, 300095.0, 4099955.0, radius_m=100.0, pixel_size_m=10.0)

    assert (grid.x0, grid.y0) == (299940.0, 4100100.0)
    assert (grid.width, grid.height) == (26, 25)
    assert (grid.centre_col, grid.centre_row) == (15.5, 14.5)
    assert grid.as_ee_grid() == {
        "dimensions": {"width": 26, "height": 25},
        "affineTransform": {"scaleX": 10.0, "shearX": 0, "translateX": 299940.0,
                            "shearY": 0, "scaleY": -10.0, "translateY": 4100100.0},
        "crsCode": "EPSG:32643",
    }


def test_window_grid_always_contains_the_whole_circle():
    grid = eec.window_grid(32643, 312345.6, 4087654.3, radius_m=2500.0, pixel_size_m=20.0)
    assert grid.x0 <= 312345.6 - 2500 and grid.x0 + grid.width * 20 >= 312345.6 + 2500
    assert grid.y0 >= 4087654.3 + 2500 and grid.y0 - grid.height * 20 <= 4087654.3 - 2500
    assert grid.x0 % 60 == 0 and grid.y0 % 60 == 0


# --- lake-window cloud -----------------------------------------------------
def _ten_by_ten_grid():
    """10x10 grid of 10 m pixels with the centre exactly at the corner shared by pixels (4,4),(4,5),(5,4),(5,5).
    With a 20 m (2 pixel) radius, the pixel centres inside are those with offsets of +-0.5 or +-1.5 pixels
    in each direction, except the 4 corners (1.5^2 + 1.5^2 = 4.5 > 4): 16 - 4 = 12 pixels."""
    return eec.WindowGrid(epsg=32643, x0=0.0, y0=100.0, pixel_size_m=10.0, width=10, height=10,
                          centre_row=5.0, centre_col=5.0)


def test_inside_radius_mask_has_exactly_12_pixels():
    mask = eec.inside_radius_mask(_ten_by_ten_grid(), radius_m=20.0)
    assert int(mask.sum()) == 12
    assert mask[4, 4] and mask[3, 4] and not mask[3, 3] and not mask[0, 0]


def test_lake_cloud_percent_counts_only_inside_the_circle():
    grid = _ten_by_ten_grid()
    scl = np.full((10, 10), 6, dtype=np.uint8)       # 6 = water
    scl[4, 4] = scl[4, 5] = scl[5, 5] = eec.SCL_CLOUD_HIGH_PROBABILITY
    scl[0, 0] = scl[9, 9] = eec.SCL_CLOUD_HIGH_PROBABILITY   # outside the circle: must not count
    assert eec.lake_cloud_percent(scl, grid, 20.0) == pytest.approx(25.0)    # 3 / 12

    scl[5, 4] = eec.SCL_CLOUD_SHADOW                  # shadow counts as cloud
    assert eec.lake_cloud_percent(scl, grid, 20.0) == pytest.approx(100 * 4 / 12)

    scl[5, 4] = 11                                    # 11 = snow: not cloud
    assert eec.lake_cloud_percent(scl, grid, 20.0) == pytest.approx(25.0)


def test_lake_cloud_percent_leaves_no_data_out_of_the_fraction():
    grid = _ten_by_ten_grid()
    scl = np.full((10, 10), 6, dtype=np.uint8)
    scl[4, 4] = scl[4, 5] = scl[5, 5] = eec.SCL_CLOUD_HIGH_PROBABILITY
    scl[3, 4] = scl[3, 5] = eec.SCL_NO_DATA           # 2 of the 12 inside pixels are outside the swath
    assert eec.lake_cloud_percent(scl, grid, 20.0) == pytest.approx(30.0)    # 3 / 10


def test_all_no_data_gives_none_and_choose_sensor_falls_back_to_radar():
    grid = _ten_by_ten_grid()
    scl = np.zeros((10, 10), dtype=np.uint8)
    value = eec.lake_cloud_percent(scl, grid, 20.0)
    assert value is None
    assert choose_sensor(value) == "radar"


def test_lake_cloud_percent_rejects_a_wrong_shaped_array():
    with pytest.raises(ValueError):
        eec.lake_cloud_percent(np.zeros((9, 10), dtype=np.uint8), _ten_by_ten_grid(), 20.0)


# --- dates -----------------------------------------------------------------
def test_query_dates_are_strictly_after_since_and_include_until():
    assert eec.query_dates(date(2026, 10, 20), date(2026, 11, 8)) == ("2026-10-21", "2026-11-09")


# --- find_new_scenes wiring, with Earth Engine mocked -----------------------
def test_lake_aoi_uses_the_exact_stored_centre_and_radius():
    fake_ee = mock.MagicMock()
    with mock.patch.object(eec, "ee", fake_ee):
        aoi = eec.lake_aoi(KARAMBAR)
    fake_ee.Geometry.Point.assert_called_once_with([73.7053229, 36.880833])
    fake_ee.Geometry.Point.return_value.buffer.assert_called_once_with(2500.0)
    assert aoi is fake_ee.Geometry.Point.return_value.buffer.return_value


def test_find_new_scenes_builds_scene_info_from_mocked_responses():
    metadata = [
        {"scene_id": "20261021T054849_20261021T054910_T43SCA", "time_start": 1792562338000, "tile_cloud_percent": 12.4},
        {"scene_id": "20261105T055021_20261105T055015_T43SCA", "time_start": 1793858333000, "tile_cloud_percent": 94.05},
    ]
    # Window for centre (331000, 4083000), radius 2500 m, 20 m pixels, 60 m alignment:
    # x0 = floor(328500/60)*60 = 328500 (already aligned) -> width  = (333500-328500)/20 = 250
    # y0 = ceil(4085500/60)*60 = 4085520 (snapped up 20 m) -> height = (4085520-4080500)/20 = 251
    # (First version of this test expected 250 x 250: I forgot the 20 m snap on the top edge.
    # The code was right; re-deriving by hand caught the wrong expected value.)
    clear = np.full((251, 250), 6, dtype=np.uint8)
    cloudy = np.full((251, 250), eec.SCL_CLOUD_HIGH_PROBABILITY, dtype=np.uint8)

    with mock.patch.object(eec, "lake_aoi", return_value="AOI") as aoi_mock, \
         mock.patch.object(eec, "_list_scene_metadata", return_value=metadata) as list_mock, \
         mock.patch.object(eec, "_centre_in_utm", return_value=(331000.0, 4083000.0)), \
         mock.patch.object(eec, "_fetch_scl", side_effect=[clear, cloudy]) as fetch_mock:
        scenes = eec.find_new_scenes(KARAMBAR, since_date=date(2026, 10, 20), until_date=date(2026, 11, 8))

    aoi_mock.assert_called_once_with(KARAMBAR)
    list_mock.assert_called_once_with("AOI", "2026-10-21", "2026-11-09")
    assert fetch_mock.call_count == 2
    grid = fetch_mock.call_args_list[0].args[1]
    assert (grid.width, grid.height, grid.epsg) == (250, 251, 32643)

    assert [s.scene_id for s in scenes] == [m["scene_id"] for m in metadata]
    assert scenes[0].acquired_at == "2026-10-21T05:58:58+00:00"
    assert (scenes[0].tile_cloud_percent, scenes[0].lake_cloud_percent) == (12.4, 0.0)
    assert (scenes[1].tile_cloud_percent, scenes[1].lake_cloud_percent) == (94.05, 100.0)
    assert all(s.lake_code == "KRB" and s.source == "sentinel-2" for s in scenes)


def test_find_new_scenes_with_no_scenes_returns_empty_and_fetches_nothing():
    with mock.patch.object(eec, "lake_aoi", return_value="AOI"), \
         mock.patch.object(eec, "_list_scene_metadata", return_value=[]), \
         mock.patch.object(eec, "_fetch_scl") as fetch_mock:
        assert eec.find_new_scenes(KARAMBAR, date(2026, 11, 7), date(2026, 11, 8)) == []
    fetch_mock.assert_not_called()


def test_a_listing_failure_raises_instead_of_returning_empty():
    quota_error = Exception("Too many concurrent aggregations.")
    with mock.patch.object(eec, "lake_aoi", return_value="AOI"), \
         mock.patch.object(eec, "_list_scene_metadata", side_effect=quota_error):
        with pytest.raises(eec.EarthEngineError, match="Too many concurrent aggregations") as info:
            eec.find_new_scenes(KARAMBAR, date(2026, 10, 1), date(2026, 11, 8))
    assert info.value.__cause__ is quota_error   # the original error is kept, not replaced


def test_a_failure_part_way_through_raises_instead_of_returning_partial_results():
    metadata = [{"scene_id": "A", "time_start": 0, "tile_cloud_percent": 1.0},
                {"scene_id": "B", "time_start": 0, "tile_cloud_percent": 1.0}]
    with mock.patch.object(eec, "lake_aoi", return_value="AOI"), \
         mock.patch.object(eec, "_list_scene_metadata", return_value=metadata), \
         mock.patch.object(eec, "_centre_in_utm", return_value=(331000.0, 4083000.0)), \
         mock.patch.object(eec, "_fetch_scl", side_effect=[np.full((251, 250), 6, np.uint8), ConnectionError("reset")]):
        with pytest.raises(eec.EarthEngineError, match="ConnectionError"):
            eec.find_new_scenes(KARAMBAR, date(2026, 10, 1), date(2026, 11, 8))


# --- initialize ------------------------------------------------------------
def test_initialize_with_no_key_anywhere_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("EE_SERVICE_ACCOUNT_KEY", raising=False)
    monkeypatch.setenv("EE_SERVICE_ACCOUNT_KEY_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(eec.EarthEngineError, match="no service-account key"):
        eec.initialize()


def test_initialize_with_a_malformed_key_raises(monkeypatch):
    monkeypatch.setenv("EE_SERVICE_ACCOUNT_KEY", "{not json")
    with pytest.raises(eec.EarthEngineError, match="not valid JSON"):
        eec.initialize()


def test_initialize_wraps_a_rejected_sign_in(monkeypatch):
    key = '{"client_email": "bot@example.iam.gserviceaccount.com", "project_id": "p"}'
    monkeypatch.setenv("EE_SERVICE_ACCOUNT_KEY", key)
    with mock.patch.object(eec.ee, "ServiceAccountCredentials", side_effect=ValueError("invalid_grant")):
        with pytest.raises(eec.EarthEngineError, match="invalid_grant"):
            eec.initialize()


def test_initialize_passes_the_key_text_and_project(monkeypatch):
    key = '{"client_email": "bot@example.iam.gserviceaccount.com", "project_id": "my-proj"}'
    monkeypatch.setenv("EE_SERVICE_ACCOUNT_KEY", key)
    with mock.patch.object(eec.ee, "ServiceAccountCredentials", return_value="CREDS") as creds_mock, \
         mock.patch.object(eec.ee, "Initialize") as init_mock:
        assert eec.initialize() == "bot@example.iam.gserviceaccount.com"
    creds_mock.assert_called_once_with("bot@example.iam.gserviceaccount.com", key_data=key)
    init_mock.assert_called_once_with("CREDS", project="my-proj")


# --- download_scene_window -------------------------------------------------
import rasterio  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

SCENE = eec.SceneInfo(scene_id="20261021T054849_20261021T054910_T43SCA", lake_code="KRB",
                      acquired_at="2026-10-21T05:58:58+00:00", tile_cloud_percent=12.4, lake_cloud_percent=0.57)


def _write_tif(path, epsg=32643, res=10.0, bands=6, size=(20, 20)):
    data = np.ones((bands, size[0], size[1]), dtype=np.uint16)
    with rasterio.open(path, "w", driver="GTiff", width=size[1], height=size[0], count=bands, dtype="uint16",
                       crs=f"EPSG:{epsg}", transform=from_origin(382100.0, 4084970.0, res, res)) as dst:
        dst.write(data)
    return path.read_bytes()


def test_export_region_is_the_bounding_square_of_the_buffer_like_the_manual_export():
    fake_ee = mock.MagicMock()
    with mock.patch.object(eec, "ee", fake_ee):
        region = eec.export_region(KARAMBAR)
    fake_ee.Geometry.Point.assert_called_once_with([73.7053229, 36.880833])
    fake_ee.Geometry.Point.return_value.buffer.assert_called_once_with(2500.0)
    fake_ee.Geometry.Point.return_value.buffer.return_value.bounds.assert_called_once_with()
    assert region is fake_ee.Geometry.Point.return_value.buffer.return_value.bounds.return_value


def test_download_params_match_the_manual_export():
    params = eec.download_params(KARAMBAR, "REGION")
    assert params == {"bands": ["B2", "B3", "B4", "B8", "B11", "SCL"], "region": "REGION", "scale": 10,
                      "crs": "EPSG:32643", "format": "GEO_TIFF"}


def test_check_downloaded_window_accepts_the_right_file(tmp_path):
    _write_tif(tmp_path / "ok.tif")
    eec.check_downloaded_window(tmp_path / "ok.tif", 32643)   # no exception


@pytest.mark.parametrize("kwargs, message", [
    ({"epsg": 4326, "res": 0.0001}, "crs"),
    ({"res": 20.0}, "pixel size"),
    ({"bands": 5}, "5 bands != 6"),   # an old-style 5-band file without SCL must be refused
])
def test_check_downloaded_window_rejects_the_wrong_file(tmp_path, kwargs, message):
    _write_tif(tmp_path / "bad.tif", **kwargs)
    with pytest.raises(eec.EarthEngineError, match=message):
        eec.check_downloaded_window(tmp_path / "bad.tif", 32643)


def _mock_download(content=b"", status=200):
    response = mock.MagicMock(status_code=status, content=content, text=content[:50].decode("latin-1"))
    return mock.patch("requests.get", return_value=response)


def test_download_writes_the_file_only_after_it_passes_the_check(tmp_path):
    good = _write_tif(tmp_path / "source.tif")
    out = tmp_path / "scenes" / "KRB" / "scene.tif"
    with mock.patch.object(eec, "ee", mock.MagicMock()), _mock_download(good):
        eec.download_scene_window(SCENE, KARAMBAR, out)
    with rasterio.open(out) as saved:
        assert saved.descriptions == ("B2", "B3", "B4", "B8", "B11", "SCL")
        assert (saved.read() == 1).all()          # pixel values untouched by the labelling step
    assert not (out.parent / "scene.tif.partial").exists()


@pytest.mark.parametrize("content, status, message", [
    (b"quota exceeded", 429, "HTTP 429"),
    (b"<html>error</html>", 200, "did not return a GeoTIFF"),
])
def test_download_failures_raise_and_leave_no_file(tmp_path, content, status, message):
    out = tmp_path / "scene.tif"
    with mock.patch.object(eec, "ee", mock.MagicMock()), _mock_download(content, status):
        with pytest.raises(eec.EarthEngineError, match=message):
            eec.download_scene_window(SCENE, KARAMBAR, out)
    assert list(tmp_path.iterdir()) == []


def test_a_wrong_shaped_download_is_refused_and_removed(tmp_path):
    three_bands = _write_tif(tmp_path / "source.tif", bands=3)
    (tmp_path / "source.tif").unlink()
    out = tmp_path / "scene.tif"
    with mock.patch.object(eec, "ee", mock.MagicMock()), _mock_download(three_bands):
        with pytest.raises(eec.EarthEngineError, match="3 bands"):
            eec.download_scene_window(SCENE, KARAMBAR, out)
    assert list(tmp_path.iterdir()) == []


def test_an_earth_engine_error_during_download_is_wrapped(tmp_path):
    fake_ee = mock.MagicMock()
    fake_ee.Image.return_value.select.return_value.toUint16.return_value.clip.return_value.getDownloadURL.side_effect = \
        RuntimeError("User memory limit exceeded.")
    with mock.patch.object(eec, "ee", fake_ee):
        with pytest.raises(eec.EarthEngineError, match="User memory limit exceeded"):
            eec.download_scene_window(SCENE, KARAMBAR, tmp_path / "scene.tif")


def test_a_period_already_covered_returns_nothing_without_asking_earth_engine():
    """Found by the radar smoke test, 2026-11-09: since 2026-11-04, until 2026-08-31 made an empty date range,
    which Earth Engine rejects ('Empty date ranges not supported'). Nothing to list is the honest answer."""
    fake_ee = mock.MagicMock()
    with mock.patch.object(eec, "ee", fake_ee):
        assert eec.find_new_scenes(KARAMBAR, date(2026, 11, 4), date(2026, 8, 31)) == []
        assert eec.find_new_s1_scenes(KARAMBAR, date(2026, 11, 4), date(2026, 8, 31)) == []
        assert eec.find_new_scenes(KARAMBAR, date(2026, 8, 31), date(2026, 8, 31)) == []    # since == until: nothing after
    fake_ee.ImageCollection.assert_not_called()


# --- added 2026-11-15: VV-only radar passes ---------------------------------------------------------
def test_radar_download_takes_vh_only_when_the_pass_has_it():
    from sailab.earth_engine_client import bands_present

    assert bands_present(("VV", "VH"), ["VV", "VH", "angle"]) == ("VV", "VH")
    assert bands_present(("VV", "VH"), ["VV", "angle"]) == ("VV",)          # a 2017 "1SSV" pass
    assert bands_present(("VV", "VH", "angle"), ["VV", "angle"]) == ("VV", "angle")


def test_a_pass_without_vv_is_refused():
    import pytest

    from sailab.earth_engine_client import EarthEngineError, bands_present

    with pytest.raises(EarthEngineError):
        bands_present(("VV", "VH"), ["HH", "HV"])
