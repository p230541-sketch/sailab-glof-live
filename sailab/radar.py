"""Radar (Sentinel-1) lake measurement: Otsu threshold + region growing, with an optional slope mask.

Uses the earlier-tested, unchanged functions otsu_threshold() and region_grow() from measurement.py.
The known real failure (original Karambar SAR file): Otsu over the whole window splits bright mountain
faces from everything else (cut-off -9.5 dB), so the flat valley floor counts as water and the region
floods it: 975.9 ha against a lake of roughly 240-260 ha. Found on 2026-11-09
(logs/2026-11-09_radar_leak_where.png): a slope mask alone does not fix it, because the leak runs across
FLAT valley floor. The fix: drop pixels steeper than a slope limit (lake water is flat) BEFORE Otsu, so
the threshold is computed from flat ground only, where it separates lake (~-20 dB) from valley floor
(~-15 dB). With slope_limit_deg=None the original method, and its failure, are reproduced on purpose.

Slope is computed here from a DEM on the same grid, by hand (central differences), not by a library call.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees, floor, hypot, isfinite
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from sailab.measurement import Pixel, extent_area_m2, otsu_threshold, region_grow


@dataclass
class RadarOutcome:
    status: str                  # 'ok' or 'insufficient_observation'
    extent_ha: float | None
    reason: str
    threshold_db: float | None = None
    masked_steep_px: int = 0
    region: set | None = None    # the grown pixels (for drawing the outline); None when refused before growing


def load_slope(dem_path: str | Path) -> np.ndarray:
    """Slope grid (degrees) from a stored DEM window; DEM no-data becomes NaN (never counted as steep)."""
    import rasterio

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        pixel_size_m = float(src.res[0])
    dem[~np.isfinite(dem)] = np.nan
    return slope_degrees(dem, pixel_size_m)


def slope_degrees(dem: np.ndarray, pixel_size_m: float) -> np.ndarray:
    """Slope of each cell from its four neighbours (central differences; one-sided at the edges)."""
    rows, cols = dem.shape
    out = np.zeros((rows, cols), dtype=float)
    for r in range(rows):
        up, down = max(r - 1, 0), min(r + 1, rows - 1)
        for c in range(cols):
            left, right = max(c - 1, 0), min(c + 1, cols - 1)
            dzdx = (dem[r, right] - dem[r, left]) / ((right - left) * pixel_size_m)
            dzdy = (dem[down, c] - dem[up, c]) / ((down - up) * pixel_size_m)
            out[r, c] = degrees(atan(hypot(dzdx, dzdy)))
    return out


def measure_radar_scene(path: str | Path, lake: Mapping[str, Any], slope: np.ndarray | None = None,
                        slope_limit_deg: float | None = None) -> RadarOutcome:
    """VV backscatter (dB) -> (optional) drop pixels steeper than slope_limit_deg -> Otsu threshold over
    the remaining pixels -> darker pixels are water candidates -> region grown from the lake centre.

    Refuses (insufficient_observation, never a zero) when the centre is outside the window, the centre is
    not a water candidate, or the grown region touches no-data (the lake may be cut off).
    """
    import rasterio

    from sailab.pipeline import lake_centre_in_pixels   # same georeferenced centre as the optical path

    with rasterio.open(path) as src:
        names = list(src.descriptions)
        band = names.index("VV") + 1 if "VV" in names else 1
        vv = src.read(band).astype(float)
        pixel_size_m = float(src.res[0])
    rows, cols = vv.shape
    no_data = ~np.isfinite(vv)
    usable = ~no_data
    masked = 0
    if slope_limit_deg is not None:
        if slope is None or slope.shape != vv.shape:
            raise ValueError("a slope grid of the same shape is needed for the slope mask")
        steep = slope > slope_limit_deg            # NaN slope (DEM edge) is not counted as steep
        masked = int((usable & steep).sum())
        usable &= ~steep
    values = [float(v) for v in vv[usable].ravel()]
    if not values:
        return RadarOutcome("insufficient_observation", None, "no valid radar pixels in the window")
    threshold = otsu_threshold(values)             # over flat pixels only when the slope mask is on
    return grow_below_threshold(path, lake, vv, usable, no_data, threshold, masked, pixel_size_m)


def read_vv(path: str | Path) -> tuple[np.ndarray, float]:
    """The VV band (dB) of a stored radar window, and its pixel size in metres."""
    import rasterio

    with rasterio.open(path) as src:
        names = list(src.descriptions)
        band = names.index("VV") + 1 if "VV" in names else 1
        return src.read(band).astype(float), float(src.res[0])


def grow_below_threshold(path: str | Path, lake: Mapping[str, Any], vv: np.ndarray, usable: np.ndarray,
                         no_data: np.ndarray, threshold: float, masked: int, pixel_size_m: float,
                         candidate: np.ndarray | None = None) -> RadarOutcome:
    """The part of a radar measurement that does not depend on how the cutoff was chosen: pixels darker
    than the cutoff are water candidates, the lake is grown from its centre, and the result is refused if it
    touches missing data. Shared by plain Otsu (above), Edge Otsu (sailab/radar_edge_otsu.py) and block Otsu
    (sailab/radar_block_otsu.py). `candidate` is for a method with a different cutoff in different parts of
    the window; `threshold` is then the cutoff at the lake centre, used in the messages."""
    from sailab.pipeline import lake_centre_in_pixels   # same georeferenced centre as the optical path

    rows, cols = vv.shape
    if candidate is None:
        candidate = usable & (vv < threshold)

    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(row_f), floor(col_f))
    if not (0 <= seed.row < rows and 0 <= seed.col < cols):
        return RadarOutcome("insufficient_observation", None, f"lake centre {seed} is outside the window", threshold, masked)
    if not candidate[seed.row, seed.col]:
        return RadarOutcome("insufficient_observation", None,
                            f"centre pixel {seed} is not below the Otsu threshold {threshold:.2f} dB", threshold, masked)
    is_water = {Pixel(r, c): bool(candidate[r, c]) for r in range(rows) for c in range(cols)}
    region = region_grow(is_water, seed, (row_f * pixel_size_m, col_f * pixel_size_m), pixel_size_m,
                         float(lake["growth_distance_limit_m"]))
    touching = sum(1 for p in region for r, c in ((p.row - 1, p.col), (p.row + 1, p.col), (p.row, p.col - 1), (p.row, p.col + 1))
                   if 0 <= r < rows and 0 <= c < cols and no_data[r, c])
    if touching:
        return RadarOutcome("insufficient_observation", None,
                            f"lake region ({len(region)} px) borders no-data pixels; it may be cut off", threshold, masked, region)
    return RadarOutcome("ok", extent_area_m2(region, pixel_size_m) / 10_000,
                        f"{len(region)} px below {threshold:.2f} dB connected to the centre", threshold, masked, region)
