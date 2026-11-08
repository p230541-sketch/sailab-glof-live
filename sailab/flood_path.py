"""Flood path tracing (FR-21): follow the steepest downhill neighbour from the lake outlet.

A simplified, one-dimensional version of the D8 trace used on the full DEM
(d02_structures.py / the Algorithm Design slide): at each step, move to
whichever neighbouring cell is lower, and stop at the end of the strip or
when no lower neighbour exists. The real pipeline runs this over a 2D height
grid with eight neighbours instead of two; the stopping rule and the
never-uphill guarantee are identical, which is what TC-FLD-01 checks.
"""
from __future__ import annotations


def trace_flood_path(heights: list[float]) -> list[int]:
    """Indices of the cells visited, starting at index 0, each step going to a lower or equal neighbour.

    Stops when the path reaches the last cell, or when neither neighbour is
    lower than the current cell (a pit, which a full DEM trace would have
    removed by sink filling before this step runs).
    """
    if not heights:
        return []

    path = [0]
    current = 0
    while current < len(heights) - 1:
        if heights[current + 1] <= heights[current]:
            current += 1
            path.append(current)
        else:
            break  # the only forward neighbour is uphill; a real DEM trace would also check sideways cells
    return path
