# D8 (old) against D-infinity (new): Shishper valley

Written by `scripts/compare_flow_paths.py` on 2026-11-15 14:01 UTC.
Height map: Copernicus 30 m DEM from the earlier project folder (`D:\University\FYP\data\downstream\shishper\dem.tif`), window 74.5 to 74.72 E, 36.24 to 36.4 N: 576 x 792 cells of 24.9 m x 30.7 m.
Start: the lake cell at 74.56239 E, 36.36060 N (row 142, column 225), from the earlier project's lake position (tools/lakes.mjs).
Both methods run on the same sink-filled grid (Priority Flood). This is a likely path, not a flood simulation: no depth, speed or arrival time.

| | D8 (old) | D-infinity (new) |
|---|---|---|
| Cells on the path | 865 | main line 881 |
| Path length | 28.06 km | main line 27.90 km |
| Path ends at | 74.50101 E, 36.24227 N | 74.49989 E, 36.24199 N |
| Cells reached (at least 1% of the water) | 865 (all of it, one line) | 977 |
| D-infinity cells reached that lie within one cell of the D8 path | - | 861 of 977 |
| Share of the water leaving the window at its edge | 1 (one cell) | 1.0000 |

Run time for both methods: 5 s.

**What this shows.** Where the valley is narrow both methods follow the same line. D8 can only move
in 8 directions, so it zig-zags; D-infinity follows the real slope and spreads the water over
neighbouring cells, which shows a band of ground at risk rather than a one-cell line.

**Our own choices, not from the paper:** the 1% share that counts a cell as reached, the main line
(always the larger share), and the window size.

Map: `2026-11-15_d8_vs_dinf_shishper.png` (black and white).
