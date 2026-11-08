"""Tests for sailab.flood_path, matching the Test Case Register."""
from sailab.flood_path import trace_flood_path


def test_TC_FLD_01_the_flood_path_never_goes_uphill():
    """Given a strip of heights 50, 40, 30, 20, 10, starting at the first cell,
    the path visits all 5 cells in order, each not higher than the one before, ending at the last cell."""
    heights = [50, 40, 30, 20, 10]

    path = trace_flood_path(heights)

    assert path == [0, 1, 2, 3, 4]
    visited_heights = [heights[i] for i in path]
    assert all(visited_heights[i] >= visited_heights[i + 1] for i in range(len(visited_heights) - 1)), \
        "the path must never go uphill"
    assert path[-1] == len(heights) - 1, "the path must end at the last cell"


def test_flood_path_stops_at_a_pit():
    """A path that hits a local low point with no lower neighbour stops there rather than climbing out."""
    heights = [50, 30, 10, 20, 5]   # index 2 is a pit: both neighbours (30, 20) are higher

    path = trace_flood_path(heights)

    assert path == [0, 1, 2]


def test_flood_path_continues_across_a_flat_plateau():
    """"Not higher than the one before" (the spec's own wording) permits an equal-height step,
    so a flat plateau must not stop the path. This is a boundary-value test on the <= in the
    step condition: with a strict < there, the path would stop at the plateau instead."""
    heights = [50, 40, 40, 30, 10]   # a plateau between indices 1 and 2

    path = trace_flood_path(heights)

    assert path == [0, 1, 2, 3, 4], "the path must cross the flat section, not stop at it"
