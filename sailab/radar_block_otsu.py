"""Self-adaptive block Otsu for radar water mapping.

Tan, Tang, Liu and others (2023), "A Self-Adaptive Thresholding Approach for Automatic Water Extraction
Using Sentinel-1 SAR Imagery Based on OTSU Algorithm and Distance Block", Remote Sensing 15(10), 2690,
sections 2.3.2 and 2.3.3. "paper:" notes point at the equation used.

The problem it solves. Sentinel-1 looks sideways, so the same water gets darker the further it is from the
satellite's track ("near range" to "far range"). Over a whole 250 km scene one Otsu cutoff cannot fit both
sides. So the picture is cut into strips parallel to the track, and neighbouring strips are merged only
while merging makes water and land easier to tell apart.

The steps:
  1. Distance image (paper, equation 1): the column number rotated by (90 deg - orbital inclination), so
     that pixels on the same line parallel to the orbit have the same distance.
  2. Cut into strips of `block` pixels, from near range to far range.
  3. From the first strip: Otsu cutoff, then the Jeffries-Matusita (JM) distance between the water and
     non-water pixels it gives (equations 2 and 3; 0 = no separation, 2 = perfect). Merge with the next
     strip and do it again; keep merging while JM goes up, otherwise close this group and start a new one.
  4. Overall JM (equation 4) = the pixel-weighted mean JM of all groups.
  5. Try block = k x 250 pixels for k = 1, 2, ... while k x 250 is not greater than half the number of
     columns; keep the block size with the highest overall JM.
  Each group keeps its own cutoff; a pixel is water when it is darker than its group's cutoff.

Ours, not the paper's (it gives none of these):
  - The orbital inclination of Sentinel-1, 98.18 degrees (ESA's published orbit figure).
  - Which side is near range. Sentinel-1 looks to the right of its track, so on an ascending pass (moving
    north) near range is the west side, and on a descending pass (moving south) the east side. The pass
    direction is taken from the time: over these lakes descending passes are at about 01:05 UTC and
    ascending passes at about 13:05 UTC (every stored pass is at one of those two times).
  - When no block size passes the paper's test (the window is narrower than 2 x 250 pixels), the whole
    window is one group, which is the same as plain Otsu. The paper does not cover so small an image.
  - The slope mask of sailab/radar.py is applied first, as for the other radar methods.
"""
from __future__ import annotations

from math import cos, exp, log, radians, sin
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from sailab.measurement import otsu_threshold
from sailab.radar import RadarOutcome, grow_below_threshold, read_vv

ORBITAL_INCLINATION_DEG = 98.18     # Sentinel-1 (ESA); the paper uses "the orbital inclination" without a number
PATCH_LONG_PX = 250                 # paper: "patch long is defined as 250 pixels"
METHOD = "block_otsu"


def jm_distance(water: np.ndarray, land: np.ndarray) -> float:
    """paper: equations (2) and (3). B = (m1 - m2)^2 / (4 (s1^2 + s2^2)) + 1/2 ln((s1^2 + s2^2) / (2 s1 s2)),
    j = 2 (1 - e^-B). 0 when either class has fewer than 2 pixels or no spread (the formula needs both)."""
    if water.size < 2 or land.size < 2:
        return 0.0
    m1, m2 = float(water.mean()), float(land.mean())
    s1, s2 = float(water.std()), float(land.std())
    if s1 == 0 or s2 == 0:
        return 0.0
    b = (m1 - m2) ** 2 / (4 * (s1 ** 2 + s2 ** 2)) + 0.5 * log((s1 ** 2 + s2 ** 2) / (2 * s1 * s2))
    return 2 * (1 - exp(-b))


def distance_image(rows: int, cols: int, ascending: bool) -> np.ndarray:
    """paper: equation (1). The column number rotated by (90 - inclination) degrees, so lines of equal
    distance run parallel to the track. Larger = further from the track (far range)."""
    angle = radians(90.0 - ORBITAL_INCLINATION_DEG)            # about -8.18 degrees
    r = np.arange(rows)[:, None].astype(float)
    c = np.arange(cols)[None, :].astype(float)
    across = c * cos(angle) + r * sin(angle)                   # grows towards the east
    return across - across.min() if ascending else across.max() - across


def _split(vv: np.ndarray, usable: np.ndarray, pixels: np.ndarray) -> tuple[float | None, float]:
    """Otsu cutoff over the usable pixels in `pixels`, and the JM distance of the split it gives."""
    values = vv[pixels & usable]
    if values.size < 2:
        return None, 0.0
    cutoff = otsu_threshold([float(v) for v in values])
    return cutoff, jm_distance(values[values < cutoff], values[values >= cutoff])


def adaptive_groups(vv: np.ndarray, usable: np.ndarray, distance: np.ndarray, block: int):
    """Steps 2 and 3 for one block size. Returns [(pixels of the group, cutoff, JM)] and the overall JM (eq. 4)."""
    strip = (distance // block).astype(int)
    order = [s for s in range(int(strip.max()) + 1) if (usable & (strip == s)).any()]
    groups = []
    k = 0
    while k < len(order):
        members = strip == order[k]
        cutoff, jm = _split(vv, usable, members)
        k += 1
        while k < len(order):                                  # keep merging while separability goes up
            trial = members | (strip == order[k])
            trial_cutoff, trial_jm = _split(vv, usable, trial)
            if trial_jm > jm:
                members, cutoff, jm = trial, trial_cutoff, trial_jm
                k += 1
            else:
                break
        groups.append((members, cutoff, jm))
    total = int(usable.sum())
    overall = sum(jm * int((members & usable).sum()) for members, _, jm in groups) / max(total, 1)
    return groups, overall


def block_otsu(vv: np.ndarray, usable: np.ndarray, ascending: bool) -> tuple[np.ndarray, int | None, float]:
    """Step 5: the best block size. Returns a cutoff for every pixel (NaN where none), the chosen block size
    (None when the window is too narrow for any, see the module note) and the overall JM."""
    rows, cols = vv.shape
    distance = distance_image(rows, cols, ascending)
    sizes = [k * PATCH_LONG_PX for k in range(1, cols) if k * PATCH_LONG_PX <= cols / 2]
    best = None
    for size in sizes:
        groups, overall = adaptive_groups(vv, usable, distance, size)
        if best is None or overall > best[2]:
            best = (groups, size, overall)
    if best is None:                                           # narrower than 2 x 250 px: one group
        cutoff, jm = _split(vv, usable, np.ones_like(usable))
        best = ([(np.ones_like(usable), cutoff, jm)], None, jm)
    cutoffs = np.full(vv.shape, np.nan)
    for members, cutoff, _ in best[0]:
        if cutoff is not None:
            cutoffs[members] = cutoff
    return cutoffs, best[1], best[2]


def is_ascending(acquired_at: str) -> bool:
    """Ascending passes over these lakes are in the afternoon (about 13:05 UTC), descending ones at about
    01:05 UTC. See the module note; this is our rule, not the paper's."""
    return int(acquired_at[11:13]) >= 12


def measure_radar_block_otsu(path: str | Path, lake: Mapping[str, Any], slope: np.ndarray, slope_limit_deg: float,
                             acquired_at: str) -> tuple[RadarOutcome, int | None]:
    """The radar measurement with block Otsu cutoffs; slope mask, growing and refusals as in sailab/radar.py.
    Returns the outcome and the chosen block size (None = the whole window was one group)."""
    vv, pixel_size_m = read_vv(path)
    no_data = ~np.isfinite(vv)
    usable = ~no_data
    if slope.shape != vv.shape:
        raise ValueError("a slope grid of the same shape is needed for the slope mask")
    steep = slope > slope_limit_deg
    masked = int((usable & steep).sum())
    usable &= ~steep
    if not usable.any():
        return RadarOutcome("insufficient_observation", None, "no valid radar pixels in the window"), None
    cutoffs, size, _ = block_otsu(vv, usable, is_ascending(acquired_at))
    from sailab.pipeline import lake_centre_in_pixels

    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    r, c = int(row_f), int(col_f)
    centre_cutoff = float(cutoffs[r, c]) if 0 <= r < vv.shape[0] and 0 <= c < vv.shape[1] else float(np.nanmedian(cutoffs))
    candidate = usable & np.isfinite(cutoffs) & (vv < np.nan_to_num(cutoffs, nan=-np.inf))
    return grow_below_threshold(path, lake, vv, usable, no_data, centre_cutoff, masked, pixel_size_m,
                                candidate=candidate), size
