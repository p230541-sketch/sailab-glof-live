"""Tests for sailab.terrain: sink filling and the 2D flood path trace."""
import numpy as np
import pytest
from sailab.terrain import fill_sinks, trace_flood_path_2d


def test_TC_TER_01_a_single_pit_fills_to_its_surrounding_ring():
    """Given a 5x5 grid of height 5, with the centre cell a pit at height 0,
    the centre must rise to 5, since every neighbour around it is already 5
    and the grid edge (all at 5) is a valid exit."""
    dem = np.full((5, 5), 5.0)
    dem[2, 2] = 0.0

    filled = fill_sinks(dem)

    assert filled[2, 2] == pytest.approx(5.0)
    assert np.array_equal(filled[0, :], dem[0, :])  # the edge, already a valid exit, must not move
    assert np.all(filled >= dem)  # filling only ever raises a cell, never lowers one


def test_TC_TER_02_a_pit_fills_only_to_its_own_ring_not_the_far_boundary():
    """Given a pit whose immediate ring is already higher than a low gap further
    away on the true grid edge, the pit only needs to rise to its own ring
    (which already drains fine on its own), not all the way down to the distant
    low gap. This is the behaviour that makes filling local rather than global.

    (First version of this test had the wrong expected value: 3.0, not 8.0.
    I had placed the low gap one cell in from the true edge, so it was not
    itself a free exit and needed filling too. Caught by re-deriving the
    expected value by hand against what the code actually produced, and the
    independent reference-library check below already agreed with the code.)
    """
    dem = np.array([
        [9, 9, 2, 9, 9],   # true boundary row, with a low gap at (0, 2)
        [9, 8, 8, 8, 9],
        [9, 8, 0, 8, 9],   # the pit, with an unbroken ring of 8s around it
        [9, 8, 8, 8, 9],
        [9, 9, 9, 9, 9],
    ], dtype=float)

    filled = fill_sinks(dem)

    assert filled[2, 2] == pytest.approx(8.0)  # rises only to its own ring, which already drains past the gap
    assert filled[0, 2] == pytest.approx(2.0)  # the boundary gap itself must never be touched


def test_fill_sinks_matches_a_trusted_reference_on_random_terrain():
    """Reference check: our fill_sinks should match scikit-image's grayscale
    morphological reconstruction (Vincent, 1993), a standard, independently
    implemented way to compute the same depression-filled surface, across
    several random terrains with several random pits each."""
    from skimage.morphology import reconstruction

    rng = np.random.default_rng(0)
    for trial in range(15):
        size = rng.integers(8, 20)
        dem = rng.uniform(0, 100, size=(size, size))
        n_pits = rng.integers(1, 5)
        for _ in range(n_pits):
            r, c = rng.integers(1, size - 1), rng.integers(1, size - 1)
            dem[r, c] = rng.uniform(-50, 0)  # force a pit well below its neighbours

        seed = dem.copy()
        seed[1:-1, 1:-1] = dem.max() + 1
        reference_filled = reconstruction(seed, dem, method="erosion")

        ours = fill_sinks(dem)
        assert ours == pytest.approx(reference_filled, abs=1e-6), f"trial {trial} (size {size}) disagreed with the reference"


def test_TC_TER_04_a_tie_between_neighbours_picks_the_first_one_found():
    """Given two neighbours of equal, lowest height, the trace must step to
    whichever is found first in the fixed scan order (here, north before
    south), not silently switch to whichever is found last. This is the
    specific behaviour a <= instead of a < in the neighbour comparison would
    break, and the first version of this module did not test it directly."""
    dem = np.array([
        [9, 1, 9],
        [9, 10, 9],
        [9, 1, 9],
    ], dtype=float)

    path = trace_flood_path_2d(dem, start=(1, 1))

    assert path[1] == (0, 1), "north (found first) must be chosen over the tied south neighbour"


def test_TC_TER_05_a_true_pit_with_no_filling_stops_immediately():
    """Given a single interior cell lower than all 8 of its neighbours, with no
    sink filling applied, the trace must stop at that one cell rather than
    step onto a higher neighbour. This isolates the stop condition itself: a
    version with the stop check removed would still move to a neighbour
    (since neighbour selection is unaffected), reaching the grid edge in 2
    steps instead of stopping in 1."""
    dem = np.array([
        [9, 9, 9],
        [9, 1, 9],
        [9, 9, 9],
    ], dtype=float)

    path = trace_flood_path_2d(dem, start=(1, 1))

    assert path == [(1, 1)], "a true pit with every neighbour higher must stop without moving"


def test_TC_TER_06_the_trace_finds_an_exit_two_flat_cells_away():
    """Given a flat strip where the start cell's immediate neighbours are all
    the same height or higher, but a lower exit sits two flat cells further
    along the strip, the trace must cross the flat to reach it rather than
    stopping the moment its own immediate neighbours look tied. This is the
    exact situation that trapped the trace on the real Hassanabad terrain."""
    dem = np.array([
        [9, 9, 9, 9, 9],
        [9, 5, 5, 5, 1],   # the flat (5, 5, 5) with the only exit (1) at the far end
        [9, 9, 9, 9, 9],
    ], dtype=float)

    path = trace_flood_path_2d(dem, start=(1, 1))

    assert path == [(1, 1), (1, 2), (1, 3), (1, 4)]


def test_TC_TER_07_a_flat_with_no_exit_anywhere_still_stops_cleanly():
    """Given a flat of more than one cell where neither cell has any lower
    neighbour at all, the trace must still stop cleanly (not loop, not
    crash, not invent a path), the same as the single-cell pit case."""
    dem = np.array([
        [9, 9, 9, 9],
        [9, 1, 1, 9],   # a two-cell flat, boxed in on every side
        [9, 9, 9, 9],
    ], dtype=float)

    path = trace_flood_path_2d(dem, start=(1, 1))

    assert path == [(1, 1)]


def test_TC_TER_03_the_2D_trace_reaches_the_edge_after_filling():
    """Given the same kind of small pit as TC-TER-01, sitting in the middle of a
    gentle slope, the 2D trace must reach the grid edge once the sink is filled,
    where the unfilled version would have stopped at the pit."""
    dem = np.array([[10.0 - 0.5 * r - 0.3 * c for c in range(10)] for r in range(10)])
    dem[4, 4] = -5.0  # a deep pit interrupting an otherwise smooth downhill slope

    unfilled_path = trace_flood_path_2d(dem, start=(0, 0))
    filled = fill_sinks(dem)
    filled_path = trace_flood_path_2d(filled, start=(0, 0))

    assert unfilled_path[-1] != (9, 9) and len(unfilled_path) <= 5   # the unfilled trace gets stuck near the pit
    r, c = filled_path[-1]
    assert r in (0, 9) or c in (0, 9), "the filled trace must reach the grid edge"
    assert all(filled[filled_path[i]] >= filled[filled_path[i + 1]] for i in range(len(filled_path) - 1))
