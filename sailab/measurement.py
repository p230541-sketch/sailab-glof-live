"""Measurement core: turns a satellite scene into a lake-extent measurement.

Covers three of the five pipeline stages' algorithms, as described in the SRS and
Test Plan (Section 3): the water index (FR-06), the radar threshold (FR-07), and
boundary-limited region growing (FR-08). Each function is deliberately written as
its own small algorithm, not as a single call into an image-processing library,
so the steps match the ones shown on the Algorithm Design slide.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from math import hypot


# ---------------------------------------------------------------------------
# FR-06: water index for Sentinel-2 optical scenes
# ---------------------------------------------------------------------------
def ndwi(green: float, near_infrared: float) -> float | None:
    """Normalized Difference Water Index for one pixel (McFeeters, 1996).

    NDWI = (green - near_infrared) / (green + near_infrared)

    Returns None (no data) when green + near_infrared is zero, since the
    ratio is undefined there rather than silently returning zero.
    """
    denominator = green + near_infrared
    if denominator == 0:
        return None
    return (green - near_infrared) / denominator


def classify_water_ndwi(green: float, near_infrared: float, cutoff: float = 0.2) -> bool:
    """A pixel is water if its NDWI is above the cutoff (a project setting, not a built-in default)."""
    value = ndwi(green, near_infrared)
    return value is not None and value > cutoff


# ---------------------------------------------------------------------------
# FR-07: Otsu threshold for Sentinel-1 radar scenes
# ---------------------------------------------------------------------------
def otsu_threshold(values: list[float], n_bins: int = 256) -> float:
    """Pick the cutoff that best separates two classes in a list of radar values.

    Implements Otsu's method directly (Otsu, 1979): build a histogram, then for
    every possible cutoff compute the between-class variance, and keep the
    cutoff with the largest variance. Water is the darker class (below the cutoff).
    """
    if not values:
        raise ValueError("otsu_threshold needs at least one value")
    lowest, highest = min(values), max(values)
    if lowest == highest:
        return lowest

    bin_width = (highest - lowest) / n_bins
    histogram = [0] * n_bins
    for value in values:
        bin_index = min(int((value - lowest) / bin_width), n_bins - 1)
        histogram[bin_index] += 1

    total_pixels = len(values)
    total_sum = sum(i * count for i, count in enumerate(histogram))

    best_cutoff_bin = 0
    best_between_class_variance = -1.0
    background_count, background_sum = 0, 0.0

    for bin_index, count in enumerate(histogram):
        background_count += count
        if background_count == 0:
            continue
        foreground_count = total_pixels - background_count
        if foreground_count == 0:
            break
        background_sum += bin_index * count
        foreground_sum = total_sum - background_sum
        background_mean = background_sum / background_count
        foreground_mean = foreground_sum / foreground_count

        between_class_variance = (
            background_count * foreground_count * (background_mean - foreground_mean) ** 2
        )
        if between_class_variance > best_between_class_variance:
            best_between_class_variance = between_class_variance
            best_cutoff_bin = bin_index

    return lowest + (best_cutoff_bin + 0.5) * bin_width


# ---------------------------------------------------------------------------
# FR-08: boundary-limited region growing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pixel:
    row: int
    col: int


def region_grow(
    is_water: dict[Pixel, bool],
    start: Pixel,
    lake_centre_m: tuple[float, float],
    pixel_size_m: float,
    max_distance_m: float,
) -> set[Pixel]:
    """Grow the lake region from its centre, 4-connected, staying water and within the distance limit.

    This is the rule behind FR-08: without the distance limit, the grown region
    can leak out of the lake along a connected river (see TC-MEA-05). The
    boundary check is what stops that leak.
    """
    visited: set[Pixel] = set()
    queue: deque[Pixel] = deque([start])
    visited.add(start)

    while queue:
        current = queue.popleft()
        for neighbour in _four_connected_neighbours(current):
            if neighbour in visited:
                continue
            if not is_water.get(neighbour, False):
                continue
            if not _within_distance(neighbour, lake_centre_m, pixel_size_m, max_distance_m):
                continue
            visited.add(neighbour)
            queue.append(neighbour)

    return visited


def extent_area_m2(region: set[Pixel], pixel_size_m: float) -> float:
    """Area = pixel count x pixel area (FR-08's final step)."""
    return len(region) * (pixel_size_m ** 2)


def _four_connected_neighbours(p: Pixel) -> list[Pixel]:
    return [Pixel(p.row - 1, p.col), Pixel(p.row + 1, p.col), Pixel(p.row, p.col - 1), Pixel(p.row, p.col + 1)]


def _within_distance(p: Pixel, centre_m: tuple[float, float], pixel_size_m: float, max_distance_m: float) -> bool:
    pixel_m = (p.row * pixel_size_m, p.col * pixel_size_m)
    distance = hypot(pixel_m[0] - centre_m[0], pixel_m[1] - centre_m[1])
    return distance <= max_distance_m
