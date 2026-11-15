"""sailab/s1_clean.py (radar cleaning after Mullissa et al. 2021) on small made-up grids with known answers."""
from __future__ import annotations

from math import cos, pi, radians, tan

import numpy as np
import pytest

from sailab import s1_clean as sc


# --- 1. border noise ---------------------------------------------------------------------------------
def test_border_noise_keeps_only_angles_strictly_inside_the_limits():
    angles = np.array([30.0, 30.63993, 30.7, 40.0, 45.2, 45.23993, 46.0])
    assert sc.border_noise_mask(angles).tolist() == [False, False, True, True, True, False, False]


# --- 2. Refined Lee ----------------------------------------------------------------------------------
def test_a_flat_picture_comes_out_unchanged():
    img = np.full((15, 15), 0.05)
    assert np.allclose(sc.refined_lee(img), 0.05)


def test_speckle_is_reduced_on_an_even_surface():
    rng = np.random.default_rng(0)
    img = 0.05 * rng.exponential(1.0, (60, 60))          # speckle: exponential around a true value of 0.05
    out = sc.refined_lee(img)
    inner = (slice(8, -8), slice(8, -8))
    assert out[inner].std() < 0.6 * img[inner].std()
    assert out[inner].mean() == pytest.approx(img[inner].mean(), rel=0.1)


def test_a_sharp_shoreline_stays_sharp():
    """Dark water on the left, bright land on the right, with speckle: the filter must not smear water
    across the shore (that is the point of using only the half-window on the pixel's own side)."""
    rng = np.random.default_rng(1)
    truth = np.where(np.arange(40)[None, :] < 20, 0.005, 0.2) * np.ones((40, 40))
    img = truth * rng.exponential(1.0, truth.shape)
    out = sc.refined_lee(img)
    water_next_to_shore = out[5:35, 18].mean()
    land_next_to_shore = out[5:35, 21].mean()
    assert water_next_to_shore < 0.05 < land_next_to_shore


def test_no_data_stays_no_data_and_does_not_leak():
    img = np.full((20, 20), 0.05)
    img[:, :5] = np.nan
    out = sc.refined_lee(img)
    assert np.isnan(out[:, :5]).all()
    assert np.allclose(out[:, 5:], 0.05)


def test_the_eight_windows_are_the_codes_shapes():
    windows = sc.direction_windows()
    assert windows[1].sum() == 28 and windows[1][3:].all() and not windows[1][:3].any()
    assert windows[2].sum() == 28 and windows[2][6, 0] == 1 and windows[2][0, 6] == 0
    assert all(w.sum() == 28 for w in windows[1:])
    assert len({w.tobytes() for w in windows[1:]}) == 8                 # all different


# --- 3. terrain correction -----------------------------------------------------------------------------
def test_flat_ground_only_turns_sigma_into_gamma():
    """No slope: the correction factor is 1, so gamma0 = sigma0 / cos(theta)."""
    sigma0 = np.full((5, 5), 0.1)
    angle = np.full((5, 5), 40.0)
    out = sc.terrain_flatten(sigma0, angle, np.full((5, 5), 3000.0), 10.0, heading_deg=-170.0)
    assert np.allclose(out, 0.1 / cos(radians(40.0)))


def test_volume_model_factor_worked_by_hand():
    """The code's formula, scf = tan(90 - theta + alpha_r) / tan(90 - theta), checked on a plane.
    Ground rising 10 degrees to the east has aspect 270 (faces west), so phi_s = -(270 - 360) = +90 degrees;
    with heading 90, phi_r = 90 - 90 = 0 and alpha_r = atan(tan(10) * cos(0)) = +10 degrees."""
    theta, alpha_r = radians(40.0), radians(10.0)
    expected = tan(pi / 2 - theta + alpha_r) / tan(pi / 2 - theta)
    dem = np.fromfunction(lambda r, c: 1000 + tan(radians(10.0)) * c * 10.0, (7, 7))
    out = sc.terrain_flatten(np.full((7, 7), 0.1), np.full((7, 7), 40.0), dem, 10.0, heading_deg=90.0)
    assert out[3, 3] == pytest.approx(0.1 / cos(theta) * expected, rel=1e-6)
    # Turning the heading round (-90) gives alpha_r = -10 degrees: the factor goes below 1 instead.
    out = sc.terrain_flatten(np.full((7, 7), 0.1), np.full((7, 7), 40.0), dem, 10.0, heading_deg=-90.0)
    below = tan(pi / 2 - theta - alpha_r) / tan(pi / 2 - theta)
    assert below < 1 and out[3, 3] == pytest.approx(0.1 / cos(theta) * below, rel=1e-6)


def test_layover_and_shadow_are_masked():
    theta = 40.0
    steep_up = np.fromfunction(lambda r, c: 1000 + tan(radians(60.0)) * c * 10.0, (7, 7))
    out = sc.terrain_flatten(np.full((7, 7), 0.1), np.full((7, 7), theta), steep_up, 10.0, heading_deg=-90.0)
    assert np.isnan(out[3, 3])                              # 60 degree slope facing the radar: layover
    out = sc.terrain_flatten(np.full((7, 7), 0.1), np.full((7, 7), theta), steep_up, 10.0, heading_deg=90.0)
    assert np.isnan(out[3, 3])                              # facing away, steeper than 90 - 40: shadow


def test_aspect_points_the_way_the_slope_faces():
    rises_east = np.fromfunction(lambda r, c: c * 1.0, (5, 5))
    rises_north = np.fromfunction(lambda r, c: -r * 1.0, (5, 5))
    assert sc.slope_and_aspect(rises_east, 1.0)[1][2, 2] == pytest.approx(270.0)    # faces west
    assert sc.slope_and_aspect(rises_north, 1.0)[1][2, 2] == pytest.approx(180.0)   # faces south


def test_heading_is_between_minus_180_and_180():
    angle = np.fromfunction(lambda r, c: 35.0 + 0.001 * c, (20, 20))   # grows to the east
    h = sc.heading_from_angle(angle, 10.0)
    assert -180.0 <= h <= 180.0
    assert h == pytest.approx(-90.0, abs=1.0)                           # faces west, as aspect is defined


def test_db_conversion():
    assert sc.to_db(np.array([0.1, 1.0])).tolist() == pytest.approx([-10.0, 0.0])
    assert np.isnan(sc.to_db(np.array([0.0]))[0])
