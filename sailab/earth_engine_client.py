"""Automatic, non-interactive connection to Google Earth Engine (Acquisition stage, FR-01 to FR-05).

Everything real in this project up to now was a person running a script in the
Earth Engine Code Editor and exporting the result by hand. This module does the
same job from Python with no person involved: it signs in with a service-account
key (no browser), lists new Sentinel-2 scenes over a lake, and works out how
cloudy each scene is *over that lake*, not over the whole 100 km tile.

Why lake-window cloud, not the tile's CLOUDY_PIXEL_PERCENTAGE: the tile value
describes ~10,000 km2; a lake window is a few km2. A 94%-cloud tile can still
have a clear lake, and a 12%-cloud tile can have its one cloud sitting on the
lake. choose_sensor() (FR-05) should decide on what is over the lake.

The cloud count itself is our own code (lake_cloud_percent below), working on
the raw Scene Classification (SCL) pixels Sentinel-2 ships with each scene.
Earth Engine is only used to fetch those pixels, not to do the counting.

Failure policy: any Earth Engine, auth, quota or network problem is raised as
EarthEngineError. Nothing here ever returns an empty list to cover a failure;
an empty list means Earth Engine genuinely answered "no scenes".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import ceil, floor
from pathlib import Path
from typing import Any, Mapping

import ee
import numpy as np

COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# Sentinel-2 Scene Classification (SCL) classes, from the ESA Sentinel-2 L2A product definition.
SCL_NO_DATA = 0
SCL_CLOUD_SHADOW = 3
SCL_CLOUD_MEDIUM_PROBABILITY = 8
SCL_CLOUD_HIGH_PROBABILITY = 9
SCL_THIN_CIRRUS = 10
# Counted as "cloud" over the lake. Cloud shadow is included on purpose: a shadow
# is dark in near-infrared, so it can look like water to NDWI and inflate the extent.
CLOUD_SCL_CLASSES = (SCL_CLOUD_SHADOW, SCL_CLOUD_MEDIUM_PROBABILITY, SCL_CLOUD_HIGH_PROBABILITY, SCL_THIN_CIRRUS)

SCL_PIXEL_SIZE_M = 20.0
# Sentinel-2 tile origins are whole multiples of 60 m in UTM, so snapping our
# window's corner to 60 m keeps it on the same pixel grid as the 10, 20 and 60 m bands.
S2_GRID_ALIGNMENT_M = 60.0

DEFAULT_KEY_FILE = Path("~/.config/sailab/ee-key.json").expanduser()


class EarthEngineError(RuntimeError):
    """Any failure talking to Earth Engine: auth, quota, network, or a bad response."""


@dataclass(frozen=True)
class SceneInfo:
    scene_id: str                    # Earth Engine system:index, e.g. 20261021T054849_20261021T054910_T43SCA
    lake_code: str
    acquired_at: str                 # ISO-8601 UTC datetime of the satellite pass
    tile_cloud_percent: float | None  # CLOUDY_PIXEL_PERCENTAGE, whole tile (Sentinel-2 only; None for radar)
    lake_cloud_percent: float | None  # our own count over the lake window; None if the window had no valid pixels
    source: str = "sentinel-2"


@dataclass(frozen=True)
class WindowGrid:
    """A north-up pixel grid in UTM, centred on a lake, aligned to the Sentinel-2 grid."""
    epsg: int
    x0: float                 # easting of the top-left corner (m)
    y0: float                 # northing of the top-left corner (m)
    pixel_size_m: float
    width: int
    height: int
    centre_row: float         # the lake centre's position in pixel units (fractional)
    centre_col: float

    def as_ee_grid(self) -> dict[str, Any]:
        return {
            "dimensions": {"width": self.width, "height": self.height},
            "affineTransform": {
                "scaleX": self.pixel_size_m, "shearX": 0, "translateX": self.x0,
                "shearY": 0, "scaleY": -self.pixel_size_m, "translateY": self.y0,
            },
            "crsCode": f"EPSG:{self.epsg}",
        }


# ---------------------------------------------------------------------------
# Pure helpers (no network): fully unit-tested
# ---------------------------------------------------------------------------
def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the WGS 84 / UTM zone containing a point (326zz north, 327zz south)."""
    zone = int(floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def window_grid(epsg: int, centre_easting: float, centre_northing: float, radius_m: float,
                pixel_size_m: float, alignment_m: float = S2_GRID_ALIGNMENT_M) -> WindowGrid:
    """The smallest aligned square window that fully contains a circle of radius_m around the centre."""
    x0 = floor((centre_easting - radius_m) / alignment_m) * alignment_m
    y0 = ceil((centre_northing + radius_m) / alignment_m) * alignment_m
    width = ceil((centre_easting + radius_m - x0) / pixel_size_m)
    height = ceil((y0 - (centre_northing - radius_m)) / pixel_size_m)
    return WindowGrid(
        epsg=epsg, x0=x0, y0=y0, pixel_size_m=pixel_size_m, width=width, height=height,
        centre_row=(y0 - centre_northing) / pixel_size_m,
        centre_col=(centre_easting - x0) / pixel_size_m,
    )


def inside_radius_mask(grid: WindowGrid, radius_m: float) -> np.ndarray:
    """True for every pixel whose centre is within radius_m of the lake centre."""
    rows = np.arange(grid.height)[:, None] + 0.5
    cols = np.arange(grid.width)[None, :] + 0.5
    distance_m = np.hypot((rows - grid.centre_row) * grid.pixel_size_m, (cols - grid.centre_col) * grid.pixel_size_m)
    return distance_m <= radius_m


def lake_cloud_percent(scl: np.ndarray, grid: WindowGrid, radius_m: float) -> float | None:
    """Percentage of valid SCL pixels inside the lake circle that are cloud or cloud shadow.

    No-data pixels (outside the satellite's swath) are left out of both the top
    and the bottom of the fraction. If no valid pixel is left, returns None,
    which choose_sensor() already treats as unusable (falls back to radar).
    """
    if scl.shape != (grid.height, grid.width):
        raise ValueError(f"SCL array shape {scl.shape} does not match grid {(grid.height, grid.width)}")
    inside = inside_radius_mask(grid, radius_m)
    valid = inside & (scl != SCL_NO_DATA)
    valid_count = int(valid.sum())
    if valid_count == 0:
        return None
    cloudy_count = int((valid & np.isin(scl, CLOUD_SCL_CLASSES)).sum())
    return 100.0 * cloudy_count / valid_count


def query_dates(since_date: date, until_date: date) -> tuple[str, str]:
    """Earth Engine's filterDate is [start, end). Scenes strictly after since_date, up to and including until_date."""
    return (since_date + timedelta(days=1)).isoformat(), (until_date + timedelta(days=1)).isoformat()


def _ms_to_iso(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def initialize(key_json: str | None = None) -> str:
    """Sign in to Earth Engine with a service-account key. Returns the service-account email.

    Key source, in order: the key_json argument; the EE_SERVICE_ACCOUNT_KEY
    environment variable holding the key's JSON text (how GitHub Actions passes
    a secret); the file named by EE_SERVICE_ACCOUNT_KEY_FILE; ~/.config/sailab/ee-key.json.
    """
    if key_json is None:
        key_json = os.environ.get("EE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        key_file = Path(os.environ.get("EE_SERVICE_ACCOUNT_KEY_FILE", DEFAULT_KEY_FILE)).expanduser()
        if not key_file.is_file():
            raise EarthEngineError(f"no service-account key: EE_SERVICE_ACCOUNT_KEY is unset and {key_file} does not exist")
        key_json = key_file.read_text()
    try:
        key = json.loads(key_json)
        email, project = key["client_email"], key["project_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EarthEngineError(f"service-account key is not valid JSON with client_email and project_id: {exc}") from exc
    try:
        credentials = ee.ServiceAccountCredentials(email, key_data=key_json)
        ee.Initialize(credentials, project=project)
    except Exception as exc:
        raise EarthEngineError(f"Earth Engine sign-in failed for {email}: {type(exc).__name__}: {exc}") from exc
    return email


# ---------------------------------------------------------------------------
# Earth Engine calls (need a live connection; only their wiring is unit-tested)
# ---------------------------------------------------------------------------
def lake_aoi(lake: Mapping[str, Any]) -> "ee.Geometry":
    """Circle of boundary_radius_m around the lake's recorded centre."""
    return ee.Geometry.Point([lake["centre_lon"], lake["centre_lat"]]).buffer(lake["boundary_radius_m"])


def _list_scene_metadata(aoi: "ee.Geometry", start: str, end: str) -> list[dict[str, Any]]:
    collection = ee.ImageCollection(COLLECTION).filterBounds(aoi).filterDate(start, end).sort("system:time_start")
    features = collection.map(
        lambda image: ee.Feature(None, {
            "scene_id": image.get("system:index"),
            "time_start": image.get("system:time_start"),
            "tile_cloud_percent": image.get("CLOUDY_PIXEL_PERCENTAGE"),
        })
    ).getInfo()
    if not isinstance(features, dict) or "features" not in features:
        raise EarthEngineError(f"unexpected response listing scenes: {str(features)[:200]}")
    return [feature["properties"] for feature in features["features"]]


def _centre_in_utm(lake: Mapping[str, Any], epsg: int) -> tuple[float, float]:
    point = ee.Geometry.Point([lake["centre_lon"], lake["centre_lat"]])
    easting, northing = point.transform(f"EPSG:{epsg}", 0.001).coordinates().getInfo()
    return float(easting), float(northing)


def _fetch_scl(scene_id: str, grid: WindowGrid) -> np.ndarray:
    image = ee.Image(f"{COLLECTION}/{scene_id}").select("SCL")
    pixels = ee.data.computePixels({"expression": image, "fileFormat": "NUMPY_NDARRAY", "grid": grid.as_ee_grid()})
    return np.asarray(pixels["SCL"])


def find_new_scenes(lake: Mapping[str, Any], since_date: date, until_date: date | None = None) -> list[SceneInfo]:
    """List (never download) Sentinel-2 scenes over the lake acquired after since_date.

    For each scene, also measures cloud over the lake window from its SCL band.
    Raises EarthEngineError on any failure; [] only when there are genuinely no scenes.
    """
    until_date = until_date or datetime.now(timezone.utc).date()
    start, end = query_dates(since_date, until_date)
    if start >= end:
        return []          # the whole period is already covered: genuinely nothing to list (Earth Engine rejects empty ranges)
    radius_m = float(lake["boundary_radius_m"])
    try:
        rows = _list_scene_metadata(lake_aoi(lake), start, end)
        if not rows:
            return []
        epsg = utm_epsg(lake["centre_lon"], lake["centre_lat"])
        easting, northing = _centre_in_utm(lake, epsg)
        grid = window_grid(epsg, easting, northing, radius_m, SCL_PIXEL_SIZE_M)
        scenes = []
        for row in rows:
            scl = _fetch_scl(row["scene_id"], grid)
            scenes.append(SceneInfo(
                scene_id=row["scene_id"],
                lake_code=lake["code"],
                acquired_at=_ms_to_iso(row["time_start"]),
                tile_cloud_percent=float(row["tile_cloud_percent"]),
                lake_cloud_percent=lake_cloud_percent(scl, grid, radius_m),
            ))
        return scenes
    except EarthEngineError:
        raise
    except Exception as exc:
        raise EarthEngineError(f"find_new_scenes failed for lake {lake['code']}: {type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Download (FR-03): the small lake window only, never a whole tile
# ---------------------------------------------------------------------------
# The exact pattern of the project's manual Code Editor exports (verbatim from them):
#   aoi = ee.Geometry.Point([lon, lat]).buffer(radius).bounds()
#   image.select(['B2', 'B3', 'B4', 'B8', 'B11']).clip(aoi), scale 10
# The manual exports set no CRS; their files turned out to be EPSG:32643 (checked
# with GDAL). Here the UTM zone is set explicitly so the grid can never drift.
# Band 6, SCL (Sentinel-2's own scene classification: cloud, shadow, snow/ice...), was added on
# 2026-11-08 for the snow/ice and cloud-touching-the-lake checks in pipeline.measure_scene. It is a
# 20 m band, delivered on the same 10 m grid. Bands 1-5 are unchanged from the manual export.
MANUAL_EXPORT_BANDS = ("B2", "B3", "B4", "B8", "B11")
DOWNLOAD_BANDS = MANUAL_EXPORT_BANDS + ("SCL",)
DOWNLOAD_SCALE_M = 10
DOWNLOAD_TIMEOUT_S = 120


def export_region(lake: Mapping[str, Any]) -> "ee.Geometry":
    """The bounding square of a circle of boundary_radius_m around the lake centre (the manual-export AOI)."""
    return ee.Geometry.Point([lake["centre_lon"], lake["centre_lat"]]).buffer(lake["boundary_radius_m"]).bounds()


def download_params(lake: Mapping[str, Any], region: Any) -> dict[str, Any]:
    return {
        "bands": list(DOWNLOAD_BANDS),
        "region": region,
        "scale": DOWNLOAD_SCALE_M,
        "crs": f"EPSG:{utm_epsg(lake['centre_lon'], lake['centre_lat'])}",
        "format": "GEO_TIFF",
    }


def check_downloaded_window(path: Path, expected_epsg: int, bands: tuple[str, ...] | None = None) -> None:
    """Refuse a file that is not the 10 m, UTM GeoTIFF with the bands we asked for, rather than measuring it anyway."""
    bands = bands or DOWNLOAD_BANDS
    import rasterio  # imported here so the rest of this module works without GDAL installed

    with rasterio.open(path) as src:
        problems = []
        if src.crs is None or src.crs.to_epsg() != expected_epsg:
            problems.append(f"crs {src.crs} != EPSG:{expected_epsg}")
        if tuple(round(r, 6) for r in src.res) != (float(DOWNLOAD_SCALE_M),) * 2:
            problems.append(f"pixel size {src.res} != {DOWNLOAD_SCALE_M} m")
        if src.count != len(bands):
            problems.append(f"{src.count} bands != {len(bands)}")
        if src.width < 2 or src.height < 2:
            problems.append(f"window only {src.width}x{src.height} px")
    if problems:
        raise EarthEngineError(f"downloaded file {path} is not the expected window: " + "; ".join(problems))


def _label_bands(path: Path, bands: tuple[str, ...] | None = None) -> None:
    """Write the band names into the file (Earth Engine's download leaves them blank), so the file
    documents itself the same way the manual exports did. The order is the order requested."""
    import rasterio

    with rasterio.open(path, "r+") as dst:
        for index, name in enumerate(bands or DOWNLOAD_BANDS, start=1):
            dst.set_band_description(index, name)


def download_scene_window(scene_info: SceneInfo, lake: Mapping[str, Any], out_path: str | Path) -> None:
    """Download the lake window of one scene as a local GeoTIFF (bands B2 B3 B4 B8 B11 SCL, 10 m, UTM).

    Writes to a temporary file first and only renames it to out_path once the
    whole file has arrived and passed check_downloaded_window(), so a crash or
    a bad response can never leave a half-written file that looks real.
    """
    import requests

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + ".partial")
    try:
        # toUint16: SCL is stored as uint8 and the reflectance bands as uint16; one common type keeps the
        # GeoTIFF simple. It does not change any value (the reflectance bands are already uint16).
        image = ee.Image(f"{COLLECTION}/{scene_info.scene_id}").select(list(DOWNLOAD_BANDS)).toUint16()
        region = export_region(lake)
        url = image.clip(region).getDownloadURL(download_params(lake, region))
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S)
        if response.status_code != 200:
            raise EarthEngineError(f"download HTTP {response.status_code}: {response.text[:300]}")
        if not response.content.startswith((b"II*\x00", b"MM\x00*")):
            raise EarthEngineError(f"download did not return a GeoTIFF (first bytes {response.content[:16]!r})")
        partial.write_bytes(response.content)
        check_downloaded_window(partial, utm_epsg(lake["centre_lon"], lake["centre_lat"]))
        _label_bands(partial)
        partial.replace(out_path)
    except EarthEngineError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise EarthEngineError(
            f"download_scene_window failed for {scene_info.scene_id} ({lake['code']}): {type(exc).__name__}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Elevation (for the radar slope mask) and Sentinel-1 radar scenes
# ---------------------------------------------------------------------------
DEM_COLLECTION = "COPERNICUS/DEM/GLO30_2024_1"   # Copernicus 30 m DEM, 2024 release (GLO30 is deprecated)
S1_COLLECTION = "COPERNICUS/S1_GRD"


def download_dem_window(lake: Mapping[str, Any], out_path: str | Path) -> None:
    """Elevation for the lake window, on the same 10 m UTM grid as the optical and radar windows
    (bilinear resampling of the 30 m DEM). Static: downloaded once per lake."""
    import requests

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tiles = ee.ImageCollection(DEM_COLLECTION).select("DEM")
        dem = tiles.mosaic().setDefaultProjection(tiles.first().projection()).resample("bilinear").toFloat()
        region = export_region(lake)
        params = {**download_params(lake, region), "bands": ["DEM"]}
        response = requests.get(dem.clip(region).getDownloadURL(params), timeout=DOWNLOAD_TIMEOUT_S)
        if response.status_code != 200 or not response.content.startswith((b"II*\x00", b"MM\x00*")):
            raise EarthEngineError(f"DEM download failed: HTTP {response.status_code}: {response.text[:200]}")
        out_path.write_bytes(response.content)
    except EarthEngineError:
        raise
    except Exception as exc:
        raise EarthEngineError(f"download_dem_window failed for {lake['code']}: {type(exc).__name__}: {exc}") from exc

S1_BANDS = ("VV", "VH")          # backscatter in dB, as delivered by COPERNICUS/S1_GRD


def find_new_s1_scenes(lake: Mapping[str, Any], since_date: date, until_date: date | None = None) -> list[SceneInfo]:
    """List (never download) Sentinel-1 IW scenes with VV over the lake acquired after since_date.
    Radar sees through cloud, so there is no cloud check. Raises EarthEngineError on any failure."""
    until_date = until_date or datetime.now(timezone.utc).date()
    start, end = query_dates(since_date, until_date)
    if start >= end:
        return []          # the whole period is already covered (Earth Engine rejects empty date ranges)
    try:
        collection = (ee.ImageCollection(S1_COLLECTION).filterBounds(lake_aoi(lake)).filterDate(start, end)
                      .filter(ee.Filter.eq("instrumentMode", "IW"))
                      .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                      .sort("system:time_start"))
        features = collection.map(lambda image: ee.Feature(None, {
            "scene_id": image.get("system:index"), "time_start": image.get("system:time_start")})).getInfo()
        if not isinstance(features, dict) or "features" not in features:
            raise EarthEngineError(f"unexpected response listing radar scenes: {str(features)[:200]}")
        return [SceneInfo(scene_id=f["properties"]["scene_id"], lake_code=lake["code"],
                          acquired_at=_ms_to_iso(f["properties"]["time_start"]), tile_cloud_percent=None,
                          lake_cloud_percent=None, source="sentinel-1") for f in features["features"]]
    except EarthEngineError:
        raise
    except Exception as exc:
        raise EarthEngineError(f"find_new_s1_scenes failed for lake {lake['code']}: {type(exc).__name__}: {exc}") from exc


def download_s1_window(scene_info: SceneInfo, lake: Mapping[str, Any], out_path: str | Path) -> None:
    """The lake window of one Sentinel-1 scene (VV, VH in dB, float32), on the same 10 m UTM grid as the
    optical window. Same temporary-file-then-check pattern as download_scene_window()."""
    import requests

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + ".partial")
    try:
        image = ee.Image(f"{S1_COLLECTION}/{scene_info.scene_id}").select(list(S1_BANDS)).toFloat()
        region = export_region(lake)
        url = image.clip(region).getDownloadURL({**download_params(lake, region), "bands": list(S1_BANDS)})
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S)
        if response.status_code != 200:
            raise EarthEngineError(f"radar download HTTP {response.status_code}: {response.text[:300]}")
        if not response.content.startswith((b"II*\x00", b"MM\x00*")):
            raise EarthEngineError(f"radar download did not return a GeoTIFF (first bytes {response.content[:16]!r})")
        partial.write_bytes(response.content)
        check_downloaded_window(partial, utm_epsg(lake["centre_lon"], lake["centre_lat"]), S1_BANDS)
        _label_bands(partial, S1_BANDS)
        partial.replace(out_path)
    except EarthEngineError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise EarthEngineError(
            f"download_s1_window failed for {scene_info.scene_id} ({lake['code']}): {type(exc).__name__}: {exc}") from exc
