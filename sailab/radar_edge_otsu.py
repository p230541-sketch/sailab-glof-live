"""Edge Otsu: a better place to take Otsu's histogram from, for radar water mapping.

Markert, Markert, Mayer and others (2020), "Comparing Sentinel-1 Surface Water Mapping Algorithms and
Radiometric Terrain Correction Processing in Southeast Asia Utilizing Google Earth Engine", Remote Sensing
12(15), 2469, section 2.3.2. "paper:" notes quote the steps and numbers used.

The problem it solves. Otsu's method finds the cutoff that best splits a histogram into two groups, and it
only works well when the histogram really has two groups (water and land) of reasonable size. Over a
whole window that is mostly land, the water group is small and the cutoff drifts. Edge Otsu builds the
histogram only from pixels NEAR the shoreline, where water and land are present in similar amounts.

The steps (paper, section 2.3.2):
  1. "an initial segmentation threshold to create a binary image": dB below -16 = maybe water.
  2. "extract edges ... using a Canny edge filter": the edges of that binary image.
  3. "only edge features over 200 m in length are considered to be valid water edges".
  4. "The extracted edges were then buffered by 3000 m (1500 m on either side)".
  5. "the dB values within the buffered edges were used to construct the histogram ... calculate a
     threshold using Otsu's method and applied to the entire image where dB values less than the
     threshold are water".

Two things here are ours, not the paper's:
  - Step 2 on a binary (two-value) image: the edge of a binary image is simply where a "maybe water" pixel
    touches a "not water" pixel, so that boundary is taken directly instead of running a full Canny filter
    (Canny exists to find edges in grey images; on a two-value image it marks the same boundary).
  - The slope mask (pixels steeper than the limit removed first) is kept, as in sailab/radar.py, because
    it is what stopped the flat valley floor leaking into the lake on these mountain lakes.

Note on scale: the paper worked on 0.1-degree tiles (about 11 km). The lake windows here are 3 to 5 km
wide, so a 1500 m buffer around the shore covers much of the window. The paper's numbers are used as they
are; the comparison script reports how much of the window the buffer covered.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from sailab.measurement import otsu_threshold
from sailab.radar import RadarOutcome, grow_below_threshold, read_vv

INITIAL_THRESHOLD_DB = -16.0     # paper: "we provided the initial threshold as -16 dB"
MIN_EDGE_LENGTH_M = 200.0        # paper: "only edge features over 200 m in length"
BUFFER_M = 1500.0                # paper: "buffered by 3000 m (1500 m on either side)"
METHOD = "edge_otsu"


def binary_edges(maybe_water: np.ndarray, usable: np.ndarray) -> np.ndarray:
    """Pixels of the "maybe water" class that touch a usable "not water" pixel (4 neighbours)."""
    rows, cols = maybe_water.shape
    edge = np.zeros_like(maybe_water, dtype=bool)
    land = usable & ~maybe_water
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shifted = np.zeros_like(land)
        shifted[max(dr, 0):rows + min(dr, 0), max(dc, 0):cols + min(dc, 0)] = \
            land[max(-dr, 0):rows + min(-dr, 0), max(-dc, 0):cols + min(-dc, 0)]
        edge |= maybe_water & usable & shifted
    return edge


def long_edges(edge: np.ndarray, pixel_size_m: float, min_length_m: float = MIN_EDGE_LENGTH_M) -> np.ndarray:
    """Keep only edge pieces longer than min_length_m. A piece is a group of edge pixels touching each other
    (8 neighbours); its length is counted as pixels x pixel size, a simple estimate along the edge."""
    from scipy import ndimage

    labels, count = ndimage.label(edge, structure=np.ones((3, 3), dtype=int))
    if count == 0:
        return np.zeros_like(edge)
    sizes = np.bincount(labels.ravel())
    keep = sizes * pixel_size_m > min_length_m
    keep[0] = False                                  # label 0 is "not an edge"
    return keep[labels]


def buffer_around(mask: np.ndarray, pixel_size_m: float, distance_m: float = BUFFER_M) -> np.ndarray:
    """Every pixel within distance_m of a True pixel (straight-line distance between pixel centres)."""
    from scipy import ndimage

    if not mask.any():
        return np.zeros_like(mask)
    return ndimage.distance_transform_edt(~mask) * pixel_size_m <= distance_m


def edge_otsu_threshold(vv: np.ndarray, usable: np.ndarray, pixel_size_m: float) -> tuple[float | None, float]:
    """The Edge Otsu cutoff (dB), or None when no edge longer than the minimum exists. Also returns the
    share of usable pixels that the buffer covered (1.0 = the whole window, i.e. plain Otsu)."""
    maybe_water = usable & (vv < INITIAL_THRESHOLD_DB)                      # step 1
    edges = long_edges(binary_edges(maybe_water, usable), pixel_size_m)     # steps 2 and 3
    if not edges.any():
        return None, 0.0
    sample = usable & buffer_around(edges, pixel_size_m)                    # step 4
    covered = float(sample.sum()) / max(int(usable.sum()), 1)
    return otsu_threshold([float(v) for v in vv[sample]]), covered          # step 5


def measure_radar_edge_otsu(path: str | Path, lake: Mapping[str, Any], slope: np.ndarray,
                            slope_limit_deg: float) -> tuple[RadarOutcome, float]:
    """The radar measurement with the Edge Otsu cutoff instead of plain Otsu; everything else (slope mask,
    growing from the centre, refusing a lake that touches missing data) is the same as sailab/radar.py.
    Returns the outcome and the share of the window the buffer covered."""
    vv, pixel_size_m = read_vv(path)
    no_data = ~np.isfinite(vv)
    usable = ~no_data
    if slope.shape != vv.shape:
        raise ValueError("a slope grid of the same shape is needed for the slope mask")
    steep = slope > slope_limit_deg
    masked = int((usable & steep).sum())
    usable &= ~steep
    if not usable.any():
        return RadarOutcome("insufficient_observation", None, "no valid radar pixels in the window"), 0.0
    threshold, covered = edge_otsu_threshold(vv, usable, pixel_size_m)
    if threshold is None:
        return RadarOutcome("insufficient_observation", None,
                            f"no water edge longer than {MIN_EDGE_LENGTH_M:.0f} m at {INITIAL_THRESHOLD_DB} dB",
                            None, masked), 0.0
    return grow_below_threshold(path, lake, vv, usable, no_data, threshold, masked, pixel_size_m), covered
