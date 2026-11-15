"""Cleaning a Sentinel-1 radar window before measuring the lake: border noise, speckle and terrain.

The three steps of Mullissa et al. (2021), "Sentinel-1 SAR Backscatter Analysis Ready Data Preparation in
Google Earth Engine", Remote Sensing 13(10), 1954 (sections 2.2 to 2.4). That paper is a technical note: it
names the steps and leaves the details to the authors' published code (github.com/adugnag/gee_s1_ard). This
module is OUR OWN code, written from that paper and that code (read, not copied), and run locally on the
downloaded lake window instead of inside Earth Engine, so every step can be tested and explained.

Input: one radar window in LINEAR power (not dB) with its incidence angle band, as downloaded from
COPERNICUS/S1_GRD_FLOAT (the paper: "all the preprocessing steps require the data to be in linear scale").

  1. Border noise (paper, section 2.2; code: border_noise_correction.py, adopted from Hird et al. 2017):
     keep only pixels whose incidence angle is between 30.63993 and 45.23993 degrees. Outside that range,
     at the edges of the satellite's strip, leftover noise is common.
  2. Speckle filter (paper, section 2.3, "The Refined Lee speckle filter used in this note"; code:
     speckle_filter.py, RefinedLee, after Lemoine): radar pictures are grainy ("speckle"). Refined Lee
     smooths a pixel only with neighbours on the same side of any edge, so shorelines stay sharp.
  3. Terrain correction (paper, section 2.4, Vollrath et al. 2020 with the volume model of Hoekman and Reiche;
     code: terrain_flattening.py): a slope facing the satellite looks brighter and one facing away looks
     darker. The correction divides that effect out, and masks "layover" and "shadow", the places on steep
     slopes the radar cannot see properly.

Our own choices, beyond the paper and its code:
  - The height map is our stored Copernicus 30 m window (data/dem), already on the radar grid. The paper uses
    SRTM by default and says it "may also be substituted by regional ... DEMs".
  - Each picture is filtered on its own (mono-temporal), never with other dates.
  - The code's local variance is Earth Engine's; here it is the population variance (divide by n).
  - Pixels with no data are left out of every local mean and variance.
"""
from __future__ import annotations

from math import pi

import numpy as np

MIN_ANGLE_DEG = 30.63993          # code: maskAngGT30, "mask out angles <= 30.63993"
MAX_ANGLE_DEG = 45.23993          # code: maskAngLT452, "mask out angles >= 45.23993"


# ---------------------------------------------------------------------------
# 1. Border noise
# ---------------------------------------------------------------------------
def border_noise_mask(angle_deg: np.ndarray) -> np.ndarray:
    """True where the pixel is kept: incidence angle strictly between the two limits."""
    return (angle_deg > MIN_ANGLE_DEG) & (angle_deg < MAX_ANGLE_DEG)


# ---------------------------------------------------------------------------
# 2. Refined Lee speckle filter
# ---------------------------------------------------------------------------
def _local_mean_var(img: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean and population variance of each pixel's neighbours, where `weights` (0/1) says which
    neighbours count. NaN pixels are left out. Same layout as an Earth Engine fixed kernel: the centre of
    the weights grid sits on the pixel."""
    from scipy import ndimage

    valid = np.isfinite(img)
    values = np.where(valid, img, 0.0)
    n = ndimage.correlate(valid.astype(float), weights, mode="constant", cval=0.0)
    s = ndimage.correlate(values, weights, mode="constant", cval=0.0)
    s2 = ndimage.correlate(values * values, weights, mode="constant", cval=0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, s / n, np.nan)
        var = np.where(n > 0, s2 / n - mean * mean, np.nan)
    return mean, np.maximum(var, 0.0)


# The 9 sample positions of the code's 7 x 7 sample kernel (1s at rows/columns 1, 3, 5 around centre 3),
# in the row-by-row order Earth Engine's neighborhoodToBands uses: band k = SAMPLE_OFFSETS[k].
SAMPLE_OFFSETS = [(-2, -2), (-2, 0), (-2, 2), (0, -2), (0, 0), (0, 2), (2, -2), (2, 0), (2, 2)]
# The code's two window shapes: "rect" = the centre row and the 3 rows below it; "diag" = the lower-left
# triangle including the diagonal. The 8 directions are these two turned by 0, 90, 180 and 270 degrees.
RECT = np.array([[0] * 7] * 3 + [[1] * 7] * 4, dtype=float)
DIAG = np.tril(np.ones((7, 7)))


def _shifted(grid: np.ndarray, dr: int, dc: int) -> np.ndarray:
    """grid value at (row + dr, col + dc) for every pixel; NaN outside the grid."""
    out = np.full(grid.shape, np.nan)
    rows, cols = grid.shape
    out[max(-dr, 0):rows - max(dr, 0), max(-dc, 0):cols - max(dc, 0)] = \
        grid[max(dr, 0):rows - max(-dr, 0), max(dc, 0):cols - max(-dc, 0)]
    return out


def direction_windows() -> list[np.ndarray]:
    """The 8 directional windows, index 1 to 8 as in the code (index 0 unused):
    1 rect, 2 diag, then for i = 1, 2, 3: 2i+1 = rect turned i times, 2i+2 = diag turned i times.
    Earth Engine's Kernel.rotate turns clockwise for a positive count; np.rot90 with -i does the same."""
    windows = [None, RECT, DIAG]
    for i in range(1, 4):
        windows += [np.rot90(RECT, -i), np.rot90(DIAG, -i)]
    return windows


def edge_directions(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every pixel: which of the 8 directional windows to use (1 to 8) and sigmaV (the speckle level),
    following the code step by step."""
    mean3, var3 = _local_mean_var(img, np.ones((3, 3)))
    s_mean = [_shifted(mean3, dr, dc) for dr, dc in SAMPLE_OFFSETS]      # the 9 sample means
    s_var = [_shifted(var3, dr, dc) for dr, dc in SAMPLE_OFFSETS]
    gradients = np.stack([np.abs(s_mean[1] - s_mean[7]), np.abs(s_mean[6] - s_mean[2]),
                          np.abs(s_mean[3] - s_mean[5]), np.abs(s_mean[0] - s_mean[8])])
    strongest = gradients == np.nanmax(gradients, axis=0)               # the code's gradmask
    first = np.stack([(s_mean[1] - s_mean[4]) > (s_mean[4] - s_mean[7]),
                      (s_mean[6] - s_mean[4]) > (s_mean[4] - s_mean[2]),
                      (s_mean[3] - s_mean[4]) > (s_mean[4] - s_mean[5]),
                      (s_mean[0] - s_mean[4]) > (s_mean[4] - s_mean[8])])
    codes = np.zeros(img.shape)
    for k in range(4):                                                   # direction k+1 or its opposite k+5
        codes += np.where(strongest[k], np.where(first[k], k + 1, k + 5), 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        stats = np.stack([v / (m * m) for v, m in zip(s_var, s_mean)])
    sigma_v = np.nanmean(np.sort(stats, axis=0)[:5], axis=0)            # mean of the 5 smallest
    return codes, sigma_v


def refined_lee(img: np.ndarray) -> np.ndarray:
    """The Refined Lee filter (linear power in, linear power out; NaN stays NaN).
    result = mean + b (pixel - mean), with mean and variance from the pixel's directional window and
    b = varX / var, varX = (var - mean^2 sigmaV) / (sigmaV + 1)  (code: RefinedLee)."""
    import warnings

    with warnings.catch_warnings():          # windows that are all no-data give NaN, which is wanted here
        warnings.simplefilter("ignore", RuntimeWarning)
        codes, sigma_v = edge_directions(img)
    dir_mean = np.full(img.shape, np.nan)
    dir_var = np.full(img.shape, np.nan)
    for code, window in enumerate(direction_windows()):
        if window is None:
            continue
        pick = codes == code
        if pick.any():
            mean, var = _local_mean_var(img, window)
            dir_mean[pick], dir_var[pick] = mean[pick], var[pick]
    with np.errstate(invalid="ignore", divide="ignore"):
        var_x = (dir_var - dir_mean * dir_mean * sigma_v) / (sigma_v + 1.0)
        b = np.where(dir_var > 0, var_x / dir_var, 0.0)
        out = dir_mean + b * (img - dir_mean)
    # Where no window could be chosen (e.g. at the very edge, or two equal strongest gradients giving a code
    # above 8), keep the pixel as it was rather than invent a value.
    keep = ~np.isfinite(out) | (codes < 1) | (codes > 8)
    return np.where(keep & np.isfinite(img), img, np.where(np.isfinite(img), out, np.nan))


# ---------------------------------------------------------------------------
# 3. Terrain correction (volume model) and layover / shadow mask
# ---------------------------------------------------------------------------
def slope_and_aspect(dem: np.ndarray, pixel_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope (radians) and aspect (degrees clockwise from north, the way the slope faces downhill),
    from central differences. Rows go south, columns go east."""
    dz_drow, dz_dcol = np.gradient(dem, pixel_size_m)
    dz_dx, dz_dy = dz_dcol, -dz_drow                     # east and north
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = (np.degrees(np.arctan2(-dz_dx, -dz_dy)) + 360.0) % 360.0
    return slope, aspect


def heading_from_angle(angle_deg: np.ndarray, pixel_size_m: float) -> float:
    """The code's "heading": the mean aspect of the incidence-angle band, worked out the same way as the
    terrain aspect, then put in -180 to 180. (The code calls this the heading and uses it as such.)"""
    _, aspect = slope_and_aspect(np.where(np.isfinite(angle_deg), angle_deg, np.nanmean(angle_deg)), pixel_size_m)
    rad = np.radians(aspect[np.isfinite(aspect)])
    mean = np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360.0   # mean of directions
    return mean - 360.0 if mean > 180.0 else mean


def terrain_flatten(sigma0: np.ndarray, angle_deg: np.ndarray, dem: np.ndarray, pixel_size_m: float,
                    heading_deg: float) -> np.ndarray:
    """Volume-model terrain correction (code: _volumetric_model_SCF and _masking), linear power in and out.
    Pixels in layover or shadow come out as NaN."""
    theta = np.radians(angle_deg)
    slope, aspect = slope_and_aspect(dem, pixel_size_m)
    phi_s = -np.radians(np.where(aspect > 180.0, aspect - 360.0, aspect))     # code: phi_sRad
    phi_r = np.radians(heading_deg) - phi_s                                   # code: phi_rRad
    alpha_r = np.arctan(np.tan(slope) * np.cos(phi_r))                        # slope in the look direction
    gamma0 = sigma0 / np.cos(theta)
    scf = np.tan(pi / 2 - theta + alpha_r) / np.tan(pi / 2 - theta)          # volume model
    visible = (alpha_r < theta) & (alpha_r > -(pi / 2 - theta))              # not layover, not shadow
    return np.where(visible, gamma0 * scf, np.nan)


def to_db(linear: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(linear > 0, 10.0 * np.log10(linear), np.nan)


def clean(vv: np.ndarray, vh: np.ndarray, angle_deg: np.ndarray, dem: np.ndarray, pixel_size_m: float,
          heading_deg: float | None = None):
    """All three steps on one window. Returns (VV dB, VH dB, heading used). NaN = no data, removed as
    border noise, or in layover / shadow. heading_deg should be worked out over the whole scene
    (earth_engine_client.s1_scene_heading); only when it is not given is it worked out from this window,
    which works only if the window's angle band actually changes across it."""
    keep = border_noise_mask(angle_deg) & np.isfinite(vv) & np.isfinite(vh)
    heading = heading_from_angle(angle_deg, pixel_size_m) if heading_deg is None else heading_deg
    out = []
    for band in (vv, vh):
        filtered = refined_lee(np.where(keep, band, np.nan))
        out.append(to_db(terrain_flatten(filtered, angle_deg, dem, pixel_size_m, heading)))
    return out[0], out[1], heading
