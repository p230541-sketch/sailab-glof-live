# Radar water measurement: plain Otsu (old) against Edge Otsu and block Otsu (new)

Written by `scripts/compare_radar_methods.py` on 2026-11-15 09:52 UTC. Every number is read from the database.

Edge Otsu (Markert et al. 2020, section 2.3.2) with the paper's numbers: initial cutoff -16.0 dB, edges over 200 m, 1500 m buffer on each side. Block Otsu (Tan et al. 2023) with the paper's 250-pixel patch. All three use the same 10 degree slope mask and the same refusals. Passes with no stored picture on this machine: 0.

### KRB (median usable optical area 255.14 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 192 | 30 | 19 of 192 (9.9%) | +7.71 ha, 15 |
| Edge Otsu (new) | 222 | 194 | 28 | 17 of 194 (8.8%) | +6.18 ha, 16 |
| Block Otsu (new) | 222 | 186 | 36 | 11 of 186 (5.9%) | +7.57 ha, 15 |

Share of the usable window the Edge Otsu buffer covered: median 97% (1.0 would be the same as plain Otsu).
Block size chosen by block Otsu: 250 px: 222 passes.

### ATS (median usable optical area 106.12 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Edge Otsu (new) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Block Otsu (new) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |

Share of the usable window the Edge Otsu buffer covered: median 100% (1.0 would be the same as plain Otsu).
Block size chosen by block Otsu: ; whole window as one group (narrower than 2 x 250 px, same as plain Otsu): 222 passes.

**Karambar, plain Otsu to block Otsu, pass by pass** (read from the database after the run above):
4 clearly wrong values became correct, 4 clearly wrong values became refusals, 2 correct values became
refusals, 11 values are wrong with both methods, and no value became newly wrong. So block Otsu removes
8 of the 19 wrong values at a cost of 2 good ones.

**Why Atro Sar does not change.** Block Otsu needs a window at least 2 x 250 pixels wide to try any strip
size (the paper's rule); the Atro Sar window is narrower, so the whole window is one group, which is
plain Otsu. Edge Otsu's 1500 m buffer covers the whole Atro Sar window for the same reason. Both papers
were written for whole satellite scenes (tens to hundreds of km), not 3 km lake windows.
