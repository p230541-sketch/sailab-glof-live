"""Tests for sailab.measurement, matching the Test Case Register."""
import math
import pytest
from sailab.measurement import ndwi, classify_water_ndwi, otsu_threshold, region_grow, extent_area_m2, Pixel


def test_TC_MEA_01_water_index_separates_water_from_land():
    """Given four pixels (water, vegetation, rock, snow), only water is above the cutoff."""
    pixels = {
        "water": (0.10, 0.02),
        "vegetation": (0.08, 0.45),
        "rock": (0.20, 0.30),
        "snow": (0.88, 0.75),
    }
    cutoff = 0.2

    values = {name: ndwi(green, nir) for name, (green, nir) in pixels.items()}

    assert values["water"] == pytest.approx(0.667, abs=0.001)
    assert values["vegetation"] == pytest.approx(-0.698, abs=0.001)
    assert values["rock"] == pytest.approx(-0.200, abs=0.001)
    assert values["snow"] == pytest.approx(0.080, abs=0.001)

    is_water = {name: classify_water_ndwi(green, nir, cutoff) for name, (green, nir) in pixels.items()}
    assert is_water == {"water": True, "vegetation": False, "rock": False, "snow": False}


def test_TC_MEA_05_boundary_rule_stops_the_river_leaking_in():
    """Given a 21x21 grid with a 25-pixel lake, a 3-pixel channel and a river column, with a growth limit of 4 pixels,
    growing with the limit keeps only the lake (27 pixels); without it, the river leaks in (49 pixels).

    Layout: lake = a 5x5 block (rows 8-12, cols 8-12) around the centre, 25 pixels.
    Channel = row 10, cols 13-15 (3 pixels), joining the lake's edge to the river.
    River = col 16, every row (21 pixels), crossing the channel at row 10.
    With a 4-pixel (40 m) growth limit from the centre: channel cols 13 and 14 are
    within range (30 m, 40 m) and included; col 15 (50 m) is not, so the river
    column — reachable only through col 15 — is never reached: 25 + 2 = 27.
    Without a limit, growth reaches the full river column: 25 + 3 + 21 = 49.
    """
    grid_size = 21
    centre = Pixel(10, 10)
    lake_radius = 2                               # a 5x5 block of pixels around the centre = 25 pixels
    channel_row = 10
    channel_cols = (13, 14, 15)                    # exactly 3 pixels, as the test case specifies
    river_col = 16
    pixel_size_m = 10.0

    is_water: dict[Pixel, bool] = {}
    for row in range(grid_size):
        for col in range(grid_size):
            in_lake = abs(row - centre.row) <= lake_radius and abs(col - centre.col) <= lake_radius
            in_channel = row == channel_row and col in channel_cols
            in_river_column = col == river_col
            is_water[Pixel(row, col)] = in_lake or in_channel or in_river_column

    lake_centre_m = (centre.row * pixel_size_m, centre.col * pixel_size_m)
    growth_limit_pixels = 4
    max_distance_m = growth_limit_pixels * pixel_size_m

    with_limit = region_grow(is_water, centre, lake_centre_m, pixel_size_m, max_distance_m=max_distance_m)
    without_limit = region_grow(is_water, centre, lake_centre_m, pixel_size_m, max_distance_m=math.inf)

    assert len(with_limit) == 27
    assert Pixel(10, river_col) not in with_limit, "the river must not appear when the limit is respected"

    assert len(without_limit) == 49
    assert Pixel(10, river_col) in without_limit, "without the limit, growth should leak along the channel into the river"

    assert extent_area_m2(with_limit, pixel_size_m) == 27 * pixel_size_m ** 2


def test_otsu_threshold_matches_scikit_image_reference():
    """Reference check (Test Plan, Section 3.4): our Otsu result should match scikit-image's on the same input."""
    import random
    import numpy as np
    from skimage.filters import threshold_otsu

    random.seed(0)
    dark_class = [random.gauss(40, 8) for _ in range(500)]       # water: low radar backscatter
    bright_class = [random.gauss(140, 15) for _ in range(500)]   # land: high radar backscatter
    values = dark_class + bright_class

    ours = otsu_threshold(values, n_bins=256)
    reference = threshold_otsu(np.array(values), nbins=256)

    assert ours == pytest.approx(reference, rel=0.02)
