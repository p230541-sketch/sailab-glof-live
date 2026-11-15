"""D-infinity flow direction (the newer method; the D8 trace in terrain.py stays as the baseline).

Tarboton (1997), "A new method for the determination of flow directions and upslope areas in grid digital
elevation models", Water Resources Research 33(2), 309-319. Read from the author's own copy
(hydrology.usu.edu/dtarb/96wr03137.pdf). "paper:" notes point at the equation or table used.

The idea in plain words. D8 sends all water from a cell to ONE of its 8 neighbours, so water can only
move in 8 directions (every 45 degrees). Real slopes point any way. D-infinity finds the true downhill
direction as an angle between 0 and 2*pi, then splits the water between the TWO neighbours on either
side of that angle, more to the one the angle points closer to. So a flood path can spread, and is not
forced into 45-degree zig-zags.

How the angle is found (paper, Figure 2 and Table 1): around each cell, eight triangles ("facets") are
formed, each from the cell, one side neighbour and one corner neighbour. On each triangle the downhill
slope is a flat plane, so its steepest direction is exact. The steepest of the eight wins.

Grid layout used here (the paper's own): e[i, j] with i = row, counted from the top (north), and j = column,
counted from the left (west). So e[i, j+1] is the east neighbour and e[i-1, j] the north neighbour.
Angles are counter-clockwise from east, as in the paper: 0 = east, pi/2 = north, pi = west, 3*pi/2 = south.
"""
from __future__ import annotations

from collections import deque
from math import atan, atan2, hypot, pi

import numpy as np

UNRESOLVED = -1.0      # paper: "a flow direction angle of -1 is used to flag the pixel as unresolved"

# paper: Table 1. For each facet k = 1..8: the (row, column) offsets of e1 (the side neighbour) and
# e2 (the corner neighbour), and the constants ac and af of equation (6).
FACETS = (
    # (e1 offset, e2 offset, ac, af)
    ((0, +1), (-1, +1), 0, +1),    # facet 1: east,  north-east
    ((-1, 0), (-1, +1), 1, -1),    # facet 2: north, north-east
    ((-1, 0), (-1, -1), 1, +1),    # facet 3: north, north-west
    ((0, -1), (-1, -1), 2, -1),    # facet 4: west,  north-west
    ((0, -1), (+1, -1), 2, +1),    # facet 5: west,  south-west
    ((+1, 0), (+1, -1), 3, -1),    # facet 6: south, south-west
    ((+1, 0), (+1, +1), 3, +1),    # facet 7: south, south-east
    ((0, +1), (+1, +1), 4, -1),    # facet 8: east,  south-east
)


def facet_distances(e1_offset: tuple[int, int], dx: float, dy: float) -> tuple[float, float]:
    """d1 = distance from the centre to e1, d2 = distance from e1 to e2 (paper, Figure 3).
    The paper draws square cells; for rectangular cells (dx east-west, dy north-south) the side
    neighbour is dx away when it is east or west, and dy away when it is north or south."""
    return (dx, dy) if e1_offset[0] == 0 else (dy, dx)


def facet_flow(e0: float, e1: float, e2: float, d1: float, d2: float) -> tuple[float, float]:
    """The steepest downhill direction r (inside the facet) and its slope s, on one facet.
    paper: equations (1) to (5)."""
    s1 = (e0 - e1) / d1                                   # (1)
    s2 = (e1 - e2) / d2                                   # (2)
    r = atan2(s2, s1)                                     # (3) r = tan^-1(s2 / s1)
    s = hypot(s1, s2)                                     # (3) s = (s1^2 + s2^2)^(1/2)
    edge = atan(d2 / d1)
    if r < 0:                                             # (4) steepest direction is outside the facet,
        r, s = 0.0, s1                                    #     so take the edge towards e1
    elif r > edge:                                        # (5) or the edge towards e2
        r, s = edge, (e0 - e2) / hypot(d1, d2)
    return r, s


def direction_at(dem: np.ndarray, i: int, j: int, dx: float, dy: float) -> tuple[float, float]:
    """The D-infinity angle and slope of one interior cell. paper: equation (6), facet order 1 to 8,
    "in the case of ties ... picks the first one". (UNRESOLVED, 0) when no facet slopes downhill."""
    best_s, best = 0.0, None
    for (o1, o2, ac, af) in FACETS:
        d1, d2 = facet_distances(o1, dx, dy)
        r, s = facet_flow(dem[i, j], dem[i + o1[0], j + o1[1]], dem[i + o2[0], j + o2[1]], d1, d2)
        if s > best_s:                                    # strictly greater: a tie keeps the first facet
            best_s, best = s, (r, ac, af)
    if best is None:
        return UNRESOLVED, 0.0
    r, ac, af = best
    return (af * r + ac * pi / 2) % (2 * pi), best_s      # (6) rg = af * r' + ac * pi / 2


def flow_angles(dem: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """The D-infinity angle of every cell. Cells on the grid edge are left UNRESOLVED: water that
    reaches the edge leaves the area we have data for (as in the D8 trace)."""
    rows, cols = dem.shape
    angles = np.full((rows, cols), UNRESOLVED)
    for i in range(1, rows - 1):
        for j in range(1, cols - 1):
            angles[i, j] = direction_at(dem, i, j, dx, dy)[0]
    return angles


# The eight neighbours in counter-clockwise order from east, as (row offset, column offset).
NEIGHBOURS_CCW = ((0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1))


def neighbour_angles(dx: float, dy: float) -> list[float]:
    """The direct angle from a cell's centre to each neighbour's centre, counter-clockwise from east.
    With square cells these are 0, pi/4, pi/2, ... ; with rectangular cells the diagonals move."""
    diagonal = atan2(dy, dx)
    return [0.0, diagonal, pi / 2, pi - diagonal, pi, pi + diagonal, 3 * pi / 2, 2 * pi - diagonal]


def split_flow(angle: float, dx: float, dy: float) -> list[tuple[tuple[int, int], float]]:
    """Which neighbours a cell drains to, and what share of its water each gets.

    paper (Calculation of Upslope Areas): the flow "all drains to one neighbor (if the angle falls along a
    cardinal or diagonal direction) or ... is proportioned between these two neighbor pixels according to
    how close the flow direction angle is to the direct angle to those pixels". The paper says this in
    words only; here "how close" is measured linearly in angle, so half-way between gives half each.
    """
    directs = neighbour_angles(dx, dy) + [2 * pi]
    for k in range(8):
        low, high = directs[k], directs[k + 1]
        if low <= angle <= high:
            to_high = (angle - low) / (high - low)
            shares = [(NEIGHBOURS_CCW[k], 1.0 - to_high), (NEIGHBOURS_CCW[(k + 1) % 8], to_high)]
            return [(offset, share) for offset, share in shares if share > 1e-12]
    raise ValueError(f"angle {angle} is not between 0 and 2*pi")


def resolve_flats(dem: np.ndarray, angles: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """paper: "Unresolved flow directions are resolved iteratively by making them flow toward a neighbor
    of equal elevation that has a flow direction resolved." Run on a sink-filled grid, every flat drains
    this way towards a cell that has a real downhill direction, so no loops can form.

    Done here as one breadth-first sweep outwards from the resolved cells, which gives the same result
    as repeating the rule until nothing changes, in a single pass. Grid-edge cells stay unresolved (exits).
    """
    rows, cols = dem.shape
    out = angles.copy()
    directs = neighbour_angles(dx, dy)
    queue = deque((i, j) for i in range(rows) for j in range(cols) if out[i, j] != UNRESOLVED
                  or i in (0, rows - 1) or j in (0, cols - 1))
    done = {cell for cell in queue}
    while queue:
        i, j = queue.popleft()
        for k, (di, dj) in enumerate(NEIGHBOURS_CCW):
            ni, nj = i + di, j + dj
            if 0 < ni < rows - 1 and 0 < nj < cols - 1 and (ni, nj) not in done and dem[ni, nj] == dem[i, j]:
                out[ni, nj] = (directs[k] + pi) % (2 * pi)    # point back at the resolved neighbour (i, j)
                done.add((ni, nj))
                queue.append((ni, nj))
    return out


def influence(angles: np.ndarray, start: tuple[int, int], dx: float, dy: float) -> np.ndarray:
    """paper (Illustrative Examples): the influence function I(x, x0), "where flow from pixel x0 goes and
    how it is dispersed". Here x0 = start, which puts in 1.0 (all of its water); every other cell gets the
    share of that water that passes through it. The paper computes it with its recursive upslope-area
    procedure; here the same shares are pushed downhill in order (a cell is passed on only once all the
    water coming into it has arrived), which needs no recursion on a large grid.

    Water reaching a grid-edge cell, or a cell that is still UNRESOLVED, stops there.
    """
    rows, cols = angles.shape

    def receivers(cell):
        i, j = cell
        if angles[i, j] == UNRESOLVED:
            return []
        out = []
        for (di, dj), share in split_flow(angles[i, j], dx, dy):
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols:
                out.append(((ni, nj), share))
        return out

    # 1. Every cell the water can reach, and how many reached cells drain into each one.
    incoming = {start: 0}
    stack = [start]
    while stack:
        cell = stack.pop()
        for target, _ in receivers(cell):
            if target not in incoming:
                incoming[target] = 0
                stack.append(target)
            incoming[target] += 1
    if incoming[start] != 0:
        raise ValueError("the flow directions contain a loop back to the start cell")
    # 2. Push the water down, a cell at a time, once everything flowing into it has arrived.
    share_here = np.zeros((rows, cols))
    share_here[start] = 1.0
    ready = deque([start])
    while ready:
        cell = ready.popleft()
        for target, share in receivers(cell):
            share_here[target] += share_here[cell] * share
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if any(count != 0 for count in incoming.values()):
        raise ValueError("the flow directions contain a loop; run on a sink-filled grid with flats resolved")
    return share_here


def main_path(angles: np.ndarray, start: tuple[int, int], dx: float, dy: float) -> list[tuple[int, int]]:
    """One line to draw next to the D8 path: from start, always step to the neighbour that gets the larger
    share. This line is OUR choice for drawing; the paper's result is the spread-out influence map."""
    rows, cols = angles.shape
    path, seen = [start], {start}
    i, j = start
    while angles[i, j] != UNRESOLVED:
        (di, dj), _ = max(split_flow(angles[i, j], dx, dy), key=lambda pair: pair[1])
        i, j = i + di, j + dj
        if (i, j) in seen or not (0 <= i < rows and 0 <= j < cols):
            break
        path.append((i, j))
        seen.add((i, j))
    return path
