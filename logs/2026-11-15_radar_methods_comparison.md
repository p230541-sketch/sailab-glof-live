# Radar water measurement: plain Otsu (old) against Edge Otsu (new)

Written by `scripts/compare_radar_methods.py` on 2026-11-15 08:47 UTC. Every number is read from the database.

Edge Otsu (Markert et al. 2020, section 2.3.2) with the paper's numbers: initial cutoff -16.0 dB, edges over 200 m, 1500 m buffer on each side. Both methods use the same 10 degree slope mask and the same refusals. Passes with no stored picture on this machine: 0.

### KRB (median usable optical area 255.14 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 192 | 30 | 19 of 192 (9.9%) | +7.71 ha, 15 |
| Edge Otsu (new) | 222 | 194 | 28 | 17 of 194 (8.8%) | +6.18 ha, 16 |

Share of the usable window the Edge Otsu buffer covered: median 97% (1.0 would be the same as plain Otsu).

### ATS (median usable optical area 106.12 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Edge Otsu (new) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |

Share of the usable window the Edge Otsu buffer covered: median 100% (1.0 would be the same as plain Otsu).

