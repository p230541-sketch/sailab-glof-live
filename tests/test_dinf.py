"""sailab/dinf.py: D-infinity (Tarboton 1997) on small made-up height grids with known answers."""
from __future__ import annotations

import random
from math import atan, cos, pi, sin

import numpy as np
import pytest

from sailab import dinf
from sailab.terrain import fill_sinks


def plane(theta: float, rows=5, cols=5, dx=1.0, dy=1.0) -> np.ndarray:
    """A tilted flat plane that slopes downhill towards angle theta (counter-clockwise from east).
    x grows to the east (columns), y grows to the north (rows go south, so y = -row)."""
    grid = np.zeros((rows, cols))
    for i in range(rows):
        for j in range(cols):
            x, y = j * dx, -i * dy
            grid[i, j] = 100.0 - (cos(theta) * x + sin(theta) * y)
    return grid


# --- equations (1) to (5) on one facet ------------------------------------------------------------
def test_facet_slope_inside_the_facet_matches_equations_1_to_3():
    # e0 = 10, e1 = 9, e2 = 8, d1 = d2 = 1: s1 = 1, s2 = 1, r = atan(1) = pi/4, s = sqrt(2)
    r, s = dinf.facet_flow(10.0, 9.0, 8.0, 1.0, 1.0)
    assert r == pytest.approx(pi / 4) and s == pytest.approx(2 ** 0.5)


def test_direction_outside_the_facet_is_clamped_to_its_edges_equations_4_and_5():
    r, s = dinf.facet_flow(10.0, 9.0, 9.5, 1.0, 1.0)          # s2 < 0 -> r < 0 -> edge to e1
    assert (r, s) == (0.0, 1.0)
    r, s = dinf.facet_flow(10.0, 10.0, 8.0, 1.0, 2.0)         # s1 = 0, s2 = 1 -> r = pi/2 > atan(2) -> edge to e2
    assert r == pytest.approx(atan(2.0)) and s == pytest.approx(2.0 / 5 ** 0.5)


# --- equation (6) and Table 1: the angle of a cell -----------------------------------------------
@pytest.mark.parametrize("dx, dy", [(1.0, 1.0), (24.9, 30.9)])
def test_a_tilted_plane_gives_its_exact_downhill_angle_in_every_facet(dx, dy):
    """On a flat plane every facet is the same plane, so the steepest direction must be the plane's own
    direction, exactly, whichever of the eight facets it falls in. Also on rectangular cells (24.9 m by
    30.9 m, the real Shishper height map's cells)."""
    rng = random.Random(3)
    for _ in range(200):
        theta = rng.uniform(0, 2 * pi)
        angle, slope = dinf.direction_at(plane(theta, dx=dx, dy=dy), 2, 2, dx, dy)
        difference = (angle - theta + pi) % (2 * pi) - pi
        assert abs(difference) < 1e-9
        assert slope == pytest.approx(1.0)                   # the plane drops 1 m per metre


def test_the_eight_main_directions_come_out_as_multiples_of_45_degrees():
    for k in range(8):
        theta = k * pi / 4
        assert dinf.direction_at(plane(theta), 2, 2, 1.0, 1.0)[0] == pytest.approx(theta % (2 * pi), abs=1e-12)


def test_a_cell_lower_than_all_its_neighbours_is_unresolved():
    pit = np.full((3, 3), 5.0)
    pit[1, 1] = 1.0
    assert dinf.direction_at(pit, 1, 1, 1.0, 1.0) == (dinf.UNRESOLVED, 0.0)


def test_a_tie_between_facets_keeps_the_first_one():
    # Due north, the boundary between facets 2 (north, north-east) and 3 (north, north-west): both give
    # the same slope; the paper keeps facet 2, whose direction is pi/2 - 0 = pi/2.
    assert dinf.direction_at(plane(pi / 2), 2, 2, 1.0, 1.0)[0] == pytest.approx(pi / 2)


# --- splitting the water between two neighbours ----------------------------------------------------
def test_flow_along_a_main_direction_goes_to_one_neighbour():
    assert dinf.split_flow(0.0, 1.0, 1.0) == [((0, 1), 1.0)]
    assert dinf.split_flow(pi / 4, 1.0, 1.0) == [((-1, 1), pytest.approx(1.0))]


def test_flow_half_way_between_two_neighbours_is_split_in_half():
    shares = dict(dinf.split_flow(pi / 8, 1.0, 1.0))
    assert shares == {(0, 1): pytest.approx(0.5), (-1, 1): pytest.approx(0.5)}


def test_the_closer_neighbour_gets_more_and_shares_always_add_up_to_one():
    shares = dict(dinf.split_flow(pi / 16, 1.0, 1.0))          # a quarter of the way from east to north-east
    assert shares[(0, 1)] == pytest.approx(0.75) and shares[(-1, 1)] == pytest.approx(0.25)
    for angle in np.linspace(0, 2 * pi, 97):
        assert sum(share for _, share in dinf.split_flow(float(angle), 24.9, 30.9)) == pytest.approx(1.0)


# --- flats, influence and the drawn line -----------------------------------------------------------
def test_a_flat_drains_towards_the_only_exit_without_loops():
    grid = np.full((7, 7), 20.0)                               # a high rim all round ...
    grid[1:6, 1:6] = 10.0                                      # ... around a flat floor at 10 m
    grid[3, 6] = 9.0                                           # with one low gap in the east rim
    angles = dinf.resolve_flats(grid, dinf.flow_angles(grid, 1.0, 1.0), 1.0, 1.0)
    share = dinf.influence(angles, (3, 1), 1.0, 1.0)           # water put in on the west side of the flat
    assert share[3, 6] == pytest.approx(1.0)                   # all of it reaches the exit


def test_influence_keeps_all_the_water_and_spreads_it_on_a_slanted_plane():
    grid = plane(pi / 8, rows=12, cols=12)                     # downhill towards east-north-east
    angles = dinf.flow_angles(grid, 1.0, 1.0)
    share = dinf.influence(angles, (10, 1), 1.0, 1.0)
    edge = np.zeros_like(share, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    assert share[edge].sum() == pytest.approx(1.0)             # nothing is lost or created on the way
    assert (share[edge] > 0.01).sum() >= 3                     # the water spreads over several exit cells


def test_d8_stays_in_one_line_where_d_infinity_spreads():
    from sailab.terrain import trace_flood_path_2d

    grid = plane(pi / 8, rows=12, cols=12)
    d8 = trace_flood_path_2d(grid, (10, 1))
    share = dinf.influence(dinf.flow_angles(grid, 1.0, 1.0), (10, 1), 1.0, 1.0)
    assert len(set(d8)) == len(d8)                             # D8: one cell after another
    assert (share > 0.01).sum() > len(d8)                      # D-infinity: a wider band of cells


def test_main_path_follows_the_larger_share_to_the_edge():
    grid = plane(0.1, rows=6, cols=9)                          # almost due east
    path = dinf.main_path(dinf.flow_angles(grid, 1.0, 1.0), (3, 1), 1.0, 1.0)
    assert path[0] == (3, 1) and path[-1][1] == 8              # ends on the east edge
    assert all(b[1] == a[1] + 1 for a, b in zip(path, path[1:]))


def test_works_after_priority_flood_on_random_terrain():
    rng = np.random.default_rng(5)
    grid = fill_sinks(rng.uniform(0, 50, (25, 25)))
    angles = dinf.resolve_flats(grid, dinf.flow_angles(grid, 1.0, 1.0), 1.0, 1.0)
    share = dinf.influence(angles, (12, 12), 1.0, 1.0)
    edge = np.zeros_like(share, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    assert share[edge].sum() == pytest.approx(1.0)


def test_a_loop_is_reported_not_followed_forever():
    angles = np.full((4, 4), dinf.UNRESOLVED)
    angles[1, 1], angles[1, 2] = 0.0, pi                       # two cells pointing at each other
    with pytest.raises(ValueError):
        dinf.influence(angles, (1, 1), 1.0, 1.0)
