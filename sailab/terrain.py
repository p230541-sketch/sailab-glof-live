"""Sink filling and D8 flow tracing over a real 2D height grid (FR-20, FR-21).

This is the real two-dimensional version the SRS and Algorithm Design slide
describe, building on the 1D simplification in flood_path.py. Real elevation
data has small pits almost everywhere (measurement noise, tiny real
depressions); trace_flood_path() alone stops at the very first one, as shown
on the real Hassanabad transect. Filling the sinks first, as the design
always said to do, is what makes a trace able to reach the valley floor.
"""
from __future__ import annotations
import heapq
import numpy as np

_NEIGHBOURS_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def fill_sinks(dem: np.ndarray) -> np.ndarray:
    """Raise every interior pit to the height of its lowest escape route to the grid edge.

    Hand-rolled priority-flood (Barnes, Lehman and Mulla, 2014): start a
    min-priority queue from every edge cell at its real height (the edge is
    always a valid exit), then repeatedly pop the lowest known cell and push
    its unfilled neighbours in at max(neighbour's real height, the popped
    cell's height). A cell can never be pushed in lower than the cell that
    reached it, so nothing is ever filled below the lowest path out.
    """
    rows, cols = dem.shape
    filled = np.full((rows, cols), np.inf, dtype=float)
    visited = np.zeros((rows, cols), dtype=bool)
    heap: list[tuple[float, int, int]] = []

    for r in range(rows):
        for c in range(cols):
            if r == 0 or r == rows - 1 or c == 0 or c == cols - 1:
                filled[r, c] = dem[r, c]
                visited[r, c] = True
                heapq.heappush(heap, (dem[r, c], r, c))

    while heap:
        height, r, c = heapq.heappop(heap)
        for dr, dc in _NEIGHBOURS_8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc]:
                visited[nr, nc] = True
                filled[nr, nc] = max(dem[nr, nc], height)
                heapq.heappush(heap, (filled[nr, nc], nr, nc))

    return filled


def trace_flood_path_2d(filled_dem: np.ndarray, start: tuple[int, int]) -> list[tuple[int, int]]:
    """Follow the steepest of up to 8 neighbours downhill from `start` until the grid edge.

    Requires a sink-filled grid (see fill_sinks). A simple greedy walk can
    still box itself in on a flat plateau that filling created, even though
    an exit from that flat genuinely exists, if the walk's own path happens
    to cut it off from the exit. When that happens, this searches the
    connected flat area (every cell at the same filled height, reachable
    without climbing) for the nearest point that does have a lower
    unvisited neighbour, and routes there before continuing the greedy walk.
    Only stops for good when no such point exists anywhere on the flat.
    """
    rows, cols = filled_dem.shape
    path = [start]
    current = start
    seen = {start}

    while True:
        r, c = current
        if r == 0 or r == rows - 1 or c == 0 or c == cols - 1:
            break  # reached the edge of the data we have

        best = _steepest_unvisited_neighbour(filled_dem, current, seen)
        if best is not None and filled_dem[best] < filled_dem[r, c]:
            current = best
            path.append(current)
            seen.add(current)
            continue

        detour = _find_flat_exit(filled_dem, current, seen)
        if detour is None:
            break  # genuinely trapped: no exit anywhere on this connected flat
        for cell in detour:
            path.append(cell)
            seen.add(cell)
        current = detour[-1]

    return path


def _steepest_unvisited_neighbour(dem: np.ndarray, cell: tuple[int, int], seen: set) -> tuple[int, int] | None:
    r, c = cell
    best = None
    for dr, dc in _NEIGHBOURS_8:
        nr, nc = r + dr, c + dc
        if 0 <= nr < dem.shape[0] and 0 <= nc < dem.shape[1] and (nr, nc) not in seen:
            if best is None or dem[nr, nc] < dem[best]:
                best = (nr, nc)
    return best


def _find_flat_exit(dem: np.ndarray, start: tuple[int, int], seen: set) -> list[tuple[int, int]] | None:
    """Breadth-first search across the connected flat at `start`'s own height,
    returning the path to the nearest cell on it with an unvisited, strictly
    lower neighbour (that neighbour itself is not included; the main loop
    steps onto it next). Never crosses into a flat at a different height.
    None if the whole connected flat has no such exit."""
    rows, cols = dem.shape
    level = dem[start]
    frontier = [start]
    came_from = {start: None}

    while frontier:
        next_frontier = []
        for cell in frontier:
            r, c = cell
            for dr, dc in _NEIGHBOURS_8:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                neighbour = (nr, nc)
                if dem[nr, nc] < level and neighbour not in seen:
                    path = [cell]
                    node = cell
                    while came_from[node] is not None:
                        node = came_from[node]
                        path.append(node)
                    path.reverse()
                    return path[1:] if len(path) > 1 else [cell]
                if dem[nr, nc] == level and neighbour not in came_from and neighbour not in seen:
                    came_from[neighbour] = cell
                    next_frontier.append(neighbour)
        frontier = next_frontier

    return None
