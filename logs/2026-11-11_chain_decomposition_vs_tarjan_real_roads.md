# Chain decomposition against Tarjan on real road files (2026-11-11)

Both bridge-finding methods in `sailab/network.py` were run on three real OpenStreetMap road files from the
earlier project folder (`D:\University\FYP\data\downstream\<valley>\roads.geojson`, not in this repository).
Every point of every road line was used as a junction, and each pair of neighbouring points as one road segment.

| Valley | Road lines | Points | Segments | Chains | Bridges (Tarjan) | Bridges (chains) | Same set |
|---|---|---|---|---|---|---|---|
| Shishper | 406 | 24,077 | 24,156 | 85 | 14,973 | 14,973 | yes |
| Passu | 362 | 18,785 | 18,846 | 72 | 11,363 | 11,363 | yes |
| Attabad | 370 | 21,412 | 21,479 | 79 | 12,917 | 12,917 | yes |

Each run took under 0.05 s.

**What this shows.** The two methods return the identical set of bridges on real networks, as they must.

**What this does not show.** The bridge counts are counts of small segments between neighbouring points, not of
roads: one long dead-end road is hundreds of "bridges" here. A useful list of critical roads needs the points
merged into real junctions first. That step is not written yet.
