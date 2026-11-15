"""sailab/radar_edge_otsu.py (Markert et al. 2020, Edge Otsu) on small made-up radar grids."""
from __future__ import annotations

import numpy as np
import pytest

from sailab import radar_edge_otsu as eo


def test_edges_are_the_water_pixels_that_touch_land():
    maybe_water = np.zeros((5, 5), dtype=bool)
    maybe_water[1:4, 1:4] = True                       # a 3 x 3 square
    edges = eo.binary_edges(maybe_water, np.ones((5, 5), dtype=bool))
    expected = maybe_water.copy()
    expected[2, 2] = False                             # only the middle pixel has water on all four sides
    assert (edges == expected).all()


def test_no_edge_against_pixels_without_data():
    maybe_water = np.zeros((3, 3), dtype=bool)
    maybe_water[:, 0] = True
    usable = np.ones((3, 3), dtype=bool)
    usable[:, 1] = False                               # the column next to the water has no data
    assert not eo.binary_edges(maybe_water, usable).any()


def test_short_edges_are_dropped_and_long_ones_kept():
    edge = np.zeros((10, 40), dtype=bool)
    edge[2, 0:25] = True                               # 25 pixels x 10 m = 250 m  > 200 m: kept
    edge[7, 0:15] = True                               # 15 pixels x 10 m = 150 m <= 200 m: dropped
    kept = eo.long_edges(edge, 10.0)
    assert kept[2, 0:25].all() and not kept[7].any()


def test_an_edge_of_exactly_200_m_is_not_over_200_m():
    edge = np.zeros((3, 30), dtype=bool)
    edge[1, 0:20] = True                               # 20 x 10 m = 200 m: the paper says "over 200 m"
    assert not eo.long_edges(edge, 10.0).any()


def test_buffer_reaches_1500_m_and_no_further():
    mask = np.zeros((1, 400), dtype=bool)
    mask[0, 0] = True
    buffered = eo.buffer_around(mask, 10.0)
    assert buffered[0, 150] and not buffered[0, 151]   # 150 pixels x 10 m = 1500 m


def _scene(water_db=-22.0, land_db=-8.0, size=200, lake=slice(80, 120)):
    vv = np.full((size, size), land_db)
    vv[lake, lake] = water_db
    rng = np.random.default_rng(0)
    return vv + rng.normal(0, 0.5, vv.shape)


def test_cutoff_falls_between_water_and_land():
    vv = _scene()
    cutoff, covered = eo.edge_otsu_threshold(vv, np.ones(vv.shape, dtype=bool), 10.0)
    assert -22.0 < cutoff < -8.0
    assert 0 < covered <= 1.0


def test_histogram_is_taken_near_the_shore_only():
    """A huge window with a small lake: the 1500 m buffer covers only part of it."""
    vv = _scene(size=600, lake=slice(290, 310))
    _, covered = eo.edge_otsu_threshold(vv, np.ones(vv.shape, dtype=bool), 10.0)
    assert covered < 0.5


def test_no_dark_area_means_no_edge_and_no_cutoff():
    vv = np.full((50, 50), -8.0)
    assert eo.edge_otsu_threshold(vv, np.ones(vv.shape, dtype=bool), 10.0) == (None, 0.0)


def test_the_papers_numbers_are_used():
    assert (eo.INITIAL_THRESHOLD_DB, eo.MIN_EDGE_LENGTH_M, eo.BUFFER_M) == (-16.0, 200.0, 1500.0)
