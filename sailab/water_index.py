"""Newer camera water measurement: the SMBWI water index, with an Otsu cutoff.

Su, Xiang, Steffen and others (2024), "A New and Robust Index for Water Body Extraction from Sentinel-2
Imagery", Remote Sensing 16(15), 2749. Equation (1) of the paper:

    SMBWI = B2 + 2.5 B3 - 2 (B8 + B8A + B9) - B11 - B12

where each band is the surface reflectance of that Sentinel-2 band (paper, section 3.1). Why it works
(paper, section 3.1 and Figures 2 to 4): water reflects blue (B2) and green (B3) but almost no
near-infrared (B8, B8A, B9) or short-wave infrared (B11, B12), while snow, glaciers, bare ground,
vegetation and shadows all reflect more of those. Adding blue and green and taking away five infrared
bands leaves water clearly above everything else. B8A and B9 are the bands most other water indices
do not use; the paper chose them to separate water from cloud shadow and dark surfaces.

How the paper turns the index into water / not water: ISODATA clustering (section 3.3.1), with no fixed
cutoff. This project's plan pairs the new index with Otsu's cutoff instead (the "plain Otsu" baseline of
the camera-cutoff row, to be replaced by the optimised Otsu of Che et al. 2025 when that paper is
available). So the water / not-water step here is NOT the paper's; only the index is.

Also here, to separate the two effects: NDWI with the same Otsu cutoff (old index, new cutoff).

Both use pipeline.grow_and_check(), so the lake is grown and checked exactly as the NDWI measurement is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from sailab.measurement import Pixel, otsu_threshold
from sailab.pipeline import (GREEN_BAND_INDEX, NIR_BAND_INDEX, SCL_BAND_INDEX, MeasurementOutcome,
                             grow_and_check)

REFLECTANCE_SCALE = 10_000      # Sentinel-2 surface reflectance is stored as reflectance x 10000
BLUE_BAND_INDEX = 1             # B2 in the stored pictures (bands B2, B3, B4, B8, B11, SCL)
EXTRA_BANDS = ("B8A", "B9", "B11", "B12")   # the separate file made by scripts/download_smbwi_bands.py
METHOD_NDWI_OTSU = "ndwi_otsu"
METHOD_SMBWI_OTSU = "smbwi_otsu"


def smbwi(b2, b3, b8, b8a, b9, b11, b12):
    """paper: equation (1). Inputs are reflectance (0 to about 1), as numbers or numpy arrays."""
    return b2 + 2.5 * b3 - 2.0 * (b8 + b8a + b9) - b11 - b12


def ndwi_grid(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI = (green - nir) / (green + nir) (McFeeters 1996) for a whole grid; NaN where both are 0."""
    total = green + nir
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total == 0, np.nan, (green - nir) / total)


def water_map_by_otsu(index: np.ndarray, valid: np.ndarray) -> tuple[dict, float]:
    """Otsu's cutoff over the valid pixels of the window (measurement.otsu_threshold, unchanged), then
    water = index above the cutoff. Returns the water map in the form grow_and_check() takes, and the cutoff."""
    cutoff = otsu_threshold([float(v) for v in index[valid]])
    water = valid & (index > cutoff)
    rows, cols = index.shape
    return {Pixel(r, c): bool(water[r, c]) for r in range(rows) for c in range(cols)}, cutoff


def _read(path: str | Path, band_indexes) -> list[np.ndarray]:
    import rasterio

    with rasterio.open(path) as src:
        return [src.read(i).astype(float) for i in band_indexes]


def _pixel_size(path: str | Path) -> float:
    import rasterio

    with rasterio.open(path) as src:
        return float(src.res[0])


def measure_ndwi_otsu(stored: str | Path, lake: Mapping[str, Any]) -> MeasurementOutcome:
    """The old index (NDWI) with the new kind of cutoff (Otsu instead of the fixed 0.2)."""
    green, nir, scl = _read(stored, (GREEN_BAND_INDEX, NIR_BAND_INDEX, SCL_BAND_INDEX))
    no_data = (green == 0) & (nir == 0)
    index = ndwi_grid(green, nir)
    is_water, cutoff = water_map_by_otsu(index, ~no_data & np.isfinite(index))
    outcome = grow_and_check(stored, lake, is_water, no_data, scl, _pixel_size(stored), f"NDWI <= Otsu {cutoff:.3f}")
    outcome.cutoff = cutoff
    return outcome


def measure_smbwi_otsu(stored: str | Path, extra: str | Path, lake: Mapping[str, Any]) -> MeasurementOutcome:
    """The new index (SMBWI) with an Otsu cutoff. B2, B3 and B8 come from the stored picture (10 m bands,
    never resampled); B8A, B9, B11 and B12 come from the extra-band file (bicubic, on the same grid)."""
    b2, b3, b8, scl = _read(stored, (BLUE_BAND_INDEX, GREEN_BAND_INDEX, NIR_BAND_INDEX, SCL_BAND_INDEX))
    b8a, b9, b11, b12 = _read(extra, (1, 2, 3, 4))
    if b8a.shape != b2.shape:
        raise ValueError(f"{extra} is {b8a.shape}, not the stored picture's {b2.shape}: not the same grid")
    no_data = ((b3 == 0) & (b8 == 0)) | ((b8a == 0) & (b9 == 0) & (b11 == 0) & (b12 == 0))
    index = smbwi(*(band / REFLECTANCE_SCALE for band in (b2, b3, b8, b8a, b9, b11, b12)))
    is_water, cutoff = water_map_by_otsu(index, ~no_data)
    outcome = grow_and_check(stored, lake, is_water, no_data, scl, _pixel_size(stored), f"SMBWI <= Otsu {cutoff:.3f}")
    outcome.cutoff = cutoff
    return outcome
