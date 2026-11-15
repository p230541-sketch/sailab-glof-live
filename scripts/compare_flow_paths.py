"""D8 (old) against D-infinity (new) on one real valley: Shishper lake above Hassanabad, Hunza.

    python scripts/compare_flow_paths.py

Steps:
  1. Read the Copernicus 30 m height map of the valley (from the earlier project's folder, outside this
     repository) and cut a window around the lake and the valley below it.
  2. Fill the sinks with Priority Flood (sailab/terrain.py, Barnes et al. 2014, unchanged).
  3. Old: the D8 path from the lake (sailab/terrain.py, unchanged).
  4. New: D-infinity directions, flats resolved, and the influence map from the same lake cell
     (sailab/dinf.py, Tarboton 1997).
  5. Write the numbers to logs/<date>_d8_vs_dinf_shishper.md and a black and white map to
     logs/<date>_d8_vs_dinf_shishper.png.

This is a LIKELY PATH, not a flood simulation: no water depth, no speed, no arrival time.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from math import cos, hypot, log10, radians
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import dinf  # noqa: E402
from sailab.terrain import fill_sinks, trace_flood_path_2d  # noqa: E402

DEM_FILE = Path(r"D:\University\FYP\data\downstream\shishper\dem.tif")
# The lake position the earlier project used (tools/lakes.mjs: "visual (S2 2019-05-06, lake at max extent)").
LAKE_LON, LAKE_LAT = 74.5623, 36.3607
WINDOW = (74.50, 74.72, 36.24, 36.40)        # west, east, south, north: the lake and the valley below it
SPREAD_SHARE = 0.01                          # a cell counts as "reached" when at least 1% of the water passes it
METRES_PER_DEGREE_LAT = 110_574.0            # the same figures sailab/flood_events.py uses
METRES_PER_DEGREE_LON_AT_EQUATOR = 111_320.0


def read_window():
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(DEM_FILE) as src:
        window = from_bounds(*WINDOW[:1], WINDOW[2], WINDOW[1], WINDOW[3], transform=src.transform)
        window = window.round_offsets().round_lengths()
        dem = src.read(1, window=window).astype(float)
        transform = src.window_transform(window)
        res_lon, res_lat = src.res
    centre_lat = (WINDOW[2] + WINDOW[3]) / 2
    dx = res_lon * METRES_PER_DEGREE_LON_AT_EQUATOR * cos(radians(centre_lat))   # cell width, metres
    dy = res_lat * METRES_PER_DEGREE_LAT                                           # cell height, metres
    col, row = ~transform * (LAKE_LON, LAKE_LAT)
    return dem, transform, dx, dy, (int(row), int(col))


def path_length_m(path, dx, dy):
    return sum(hypot((b[1] - a[1]) * dx, (b[0] - a[0]) * dy) for a, b in zip(path, path[1:]))


def draw(dem, d8_path, share, dinf_line, out_png):
    """Black and white: grey terrain (darker = lower), the D-infinity spread as black dots whose density
    shows the share of water, the D8 path as a solid black line, the D-infinity main line as a white line
    with a black edge."""
    from PIL import Image, ImageDraw

    low, high = np.percentile(dem, 2), np.percentile(dem, 98)
    grey = np.clip((dem - low) / (high - low), 0, 1) * 120 + 120          # 120 (low) to 240 (high)
    image = Image.fromarray(grey.astype(np.uint8), "L").convert("RGB")
    scale = 2
    image = image.resize((image.width * scale, image.height * scale), Image.NEAREST)
    pen = ImageDraw.Draw(image)
    rng = np.random.default_rng(0)
    for (i, j) in zip(*np.nonzero(share >= SPREAD_SHARE)):
        # density of dots grows with the share: 1% -> sparse, 100% -> solid
        if rng.random() < 0.25 + 0.75 * (log10(share[i, j]) + 2) / 2:
            pen.point((j * scale + 1, i * scale + 1), fill=(0, 0, 0))
    to_xy = lambda cells: [(c * scale + scale / 2, r * scale + scale / 2) for r, c in cells]   # noqa: E731
    pen.line(to_xy(dinf_line), fill=(0, 0, 0), width=5)
    pen.line(to_xy(dinf_line), fill=(255, 255, 255), width=2)
    pen.line(to_xy(d8_path), fill=(0, 0, 0), width=2)
    r, c = d8_path[0]
    pen.ellipse((c * scale - 6, r * scale - 6, c * scale + 6, r * scale + 6), outline=(0, 0, 0), width=2)
    pen.rectangle((8, 8, 420, 74), fill=(255, 255, 255), outline=(0, 0, 0))
    pen.text((16, 14), "Shishper valley: D8 (old) vs D-infinity (new)", fill=(0, 0, 0))
    pen.text((16, 32), "black line = D8 path; white line = D-inf main line", fill=(0, 0, 0))
    pen.text((16, 50), f"dots = D-inf spread (at least {SPREAD_SHARE:.0%} of the water); circle = lake", fill=(0, 0, 0))
    image.save(out_png)


def main() -> int:
    started = time.time()
    dem, transform, dx, dy, lake = read_window()
    filled = fill_sinks(dem)
    d8 = trace_flood_path_2d(filled, lake)
    angles = dinf.resolve_flats(filled, dinf.flow_angles(filled, dx, dy), dx, dy)
    share = dinf.influence(angles, lake, dx, dy)
    line = dinf.main_path(angles, lake, dx, dy)
    elapsed = time.time() - started

    reached = share >= SPREAD_SHARE
    d8_cells = set(d8)
    near_d8 = np.zeros_like(reached)
    for r, c in d8:
        near_d8[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2] = True
    rows, cols = dem.shape
    exit_share = share[0, :].sum() + share[-1, :].sum() + share[1:-1, 0].sum() + share[1:-1, -1].sum()
    lake_lonlat = transform * (lake[1] + 0.5, lake[0] + 0.5)
    end_d8 = transform * (d8[-1][1] + 0.5, d8[-1][0] + 0.5)
    end_line = transform * (line[-1][1] + 0.5, line[-1][0] + 0.5)
    stamp = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    out_png = REPO / "logs" / f"{stamp}_d8_vs_dinf_shishper.png"
    draw(dem, d8, share, line, out_png)
    lines = [
        "# D8 (old) against D-infinity (new): Shishper valley",
        "",
        f"Written by `scripts/compare_flow_paths.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
        f"Height map: Copernicus 30 m DEM from the earlier project folder (`{DEM_FILE}`), window "
        f"{WINDOW[0]} to {WINDOW[1]} E, {WINDOW[2]} to {WINDOW[3]} N: {rows} x {cols} cells of {dx:.1f} m x {dy:.1f} m.",
        f"Start: the lake cell at {lake_lonlat[0]:.5f} E, {lake_lonlat[1]:.5f} N (row {lake[0]}, column {lake[1]}), "
        "from the earlier project's lake position (tools/lakes.mjs).",
        "Both methods run on the same sink-filled grid (Priority Flood). This is a likely path, not a flood "
        "simulation: no depth, speed or arrival time.",
        "",
        "| | D8 (old) | D-infinity (new) |",
        "|---|---|---|",
        f"| Cells on the path | {len(d8)} | main line {len(line)} |",
        f"| Path length | {path_length_m(d8, dx, dy) / 1000:.2f} km | main line {path_length_m(line, dx, dy) / 1000:.2f} km |",
        f"| Path ends at | {end_d8[0]:.5f} E, {end_d8[1]:.5f} N | {end_line[0]:.5f} E, {end_line[1]:.5f} N |",
        f"| Cells reached (at least {SPREAD_SHARE:.0%} of the water) | {len(d8_cells)} (all of it, one line) | {int(reached.sum())} |",
        f"| D-infinity cells reached that lie within one cell of the D8 path | - | {int((reached & near_d8).sum())} of {int(reached.sum())} |",
        f"| Share of the water leaving the window at its edge | 1 (one cell) | {exit_share:.4f} |",
        "",
        f"Run time for both methods: {elapsed:.0f} s.",
        "",
        "**What this shows.** Where the valley is narrow both methods follow the same line. D8 can only move",
        "in 8 directions, so it zig-zags; D-infinity follows the real slope and spreads the water over",
        "neighbouring cells, which shows a band of ground at risk rather than a one-cell line.",
        "",
        "**Our own choices, not from the paper:** the 1% share that counts a cell as reached, the main line",
        "(always the larger share), and the window size.",
        "",
        f"Map: `{out_png.name}` (black and white).",
    ]
    out_md = REPO / "logs" / f"{stamp}_d8_vs_dinf_shishper.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[8:15]))
    print(f"Written: {out_md}\nWritten: {out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
