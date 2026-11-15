"""sailab/radar_block_otsu.py (Tan et al. 2023) on small made-up radar grids with known answers."""
from __future__ import annotations

from math import exp, log

import numpy as np
import pytest

from sailab import radar_block_otsu as bo


# --- equations (2) and (3) --------------------------------------------------------------------------
def test_jm_distance_matches_equations_2_and_3_worked_by_hand():
    water = np.array([-22.0, -20.0])        # mean -21, std 1
    land = np.array([-10.0, -6.0])          # mean -8,  std 2
    b = (-21 + 8) ** 2 / (4 * (1 + 4)) + 0.5 * log((1 + 4) / (2 * 1 * 2))
    assert bo.jm_distance(water, land) == pytest.approx(2 * (1 - exp(-b)))


def test_jm_is_near_2_for_well_separated_classes_and_near_0_for_mixed_ones():
    rng = np.random.default_rng(1)
    assert bo.jm_distance(rng.normal(-22, 1, 500), rng.normal(-8, 1, 500)) > 1.99
    assert bo.jm_distance(rng.normal(-10, 1, 500), rng.normal(-10.1, 1, 500)) < 0.05


def test_jm_is_zero_when_a_class_is_too_small_or_flat():
    assert bo.jm_distance(np.array([-20.0]), np.array([-8.0, -9.0])) == 0.0
    assert bo.jm_distance(np.array([-20.0, -20.0]), np.array([-8.0, -9.0])) == 0.0


# --- equation (1): the distance image ---------------------------------------------------------------
def test_distance_grows_from_near_to_far_range_and_flips_with_the_pass_direction():
    ascending = bo.distance_image(3, 50, ascending=True)
    descending = bo.distance_image(3, 50, ascending=False)
    assert ascending[1, 0] < ascending[1, -1]               # ascending: near range is the west side
    assert descending[1, 0] > descending[1, -1]             # descending: near range is the east side
    assert ascending.min() == 0 and descending.min() == 0


def test_lines_of_equal_distance_lean_by_90_minus_the_inclination():
    d = bo.distance_image(100, 100, ascending=True)
    # Going one row down changes the distance by sin(90 - 98.18 degrees), about -0.142 pixels.
    assert d[1, 0] - d[0, 0] == pytest.approx(-0.1423, abs=1e-3)


def test_pass_direction_from_the_time():
    assert bo.is_ascending("2026-11-09T13:05:00+00:00")
    assert not bo.is_ascending("2026-11-10T01:05:41+00:00")


# --- steps 2 to 5 ------------------------------------------------------------------------------------
def _two_sided(cols=1000, rows=40):
    """Water is darker on the near side than on the far side, as in a real side-looking radar scene:
    near half water -24 / land -12, far half water -18 / land -6. One cutoff cannot fit both halves."""
    rng = np.random.default_rng(2)
    vv = np.empty((rows, cols))
    half = cols // 2
    vv[:, :half] = np.where(rng.random((rows, half)) < 0.3, -24.0, -12.0)
    vv[:, half:] = np.where(rng.random((rows, cols - half)) < 0.3, -18.0, -6.0)
    return vv + rng.normal(0, 0.7, vv.shape)


def test_each_side_gets_its_own_cutoff():
    vv = _two_sided()
    cutoffs, size, overall = bo.block_otsu(vv, np.ones(vv.shape, dtype=bool), ascending=True)
    near, far = float(np.nanmedian(cutoffs[:, :400])), float(np.nanmedian(cutoffs[:, 600:]))
    assert -24 < near < -12 and -18 < far < -6
    assert far > near                                       # the far side's cutoff is higher
    assert size is not None and size % bo.PATCH_LONG_PX == 0
    assert overall > 1.5


def test_strips_merge_only_when_separability_goes_strictly_up():
    """paper: "If j(i+1) > j(i), the merge operation will be repeated; otherwise, it will be the final
    classification result." Four strips that each separate perfectly (JM = 2, the maximum) cannot go up
    by merging, so they stay four groups."""
    vv = np.tile(np.where(np.arange(1000) % 2 == 0, -22.0, -8.0), (20, 1))   # two exact values, no noise
    groups, overall = bo.adaptive_groups(vv, np.ones(vv.shape, dtype=bool), bo.distance_image(20, 1000, True), 250)
    assert all(jm == pytest.approx(2.0) or jm == 0.0 for _, _, jm in groups)
    assert len(groups) >= 4


def test_a_strip_that_separates_badly_on_its_own_is_merged_with_its_neighbour():
    """The first strip holds almost no water, so its own split is poor; adding the next strip, which has
    plenty of water at the same level, gives a clearer split, so the two are merged."""
    rng = np.random.default_rng(4)
    vv = rng.normal(-8.0, 1.0, (20, 1000))
    vv[:, 260:480] = rng.normal(-22.0, 1.0, (20, 220))                      # water only in the second strip
    vv[0, 10] = -22.0                                                        # one dark pixel in the first strip
    groups, _ = bo.adaptive_groups(vv, np.ones(vv.shape, dtype=bool), bo.distance_image(20, 1000, True), 250)
    first_group = groups[0][0]
    assert first_group[:, 0].all() and first_group[:, 300].all()            # strips 1 and 2 are in one group


def test_a_window_narrower_than_two_patches_is_one_group_like_plain_otsu():
    from sailab.measurement import otsu_threshold

    vv = _two_sided(cols=300)
    usable = np.ones(vv.shape, dtype=bool)
    cutoffs, size, _ = bo.block_otsu(vv, usable, ascending=True)
    assert size is None
    assert np.allclose(cutoffs, otsu_threshold([float(v) for v in vv.ravel()]))


def test_the_papers_patch_size_is_used():
    assert bo.PATCH_LONG_PX == 250
