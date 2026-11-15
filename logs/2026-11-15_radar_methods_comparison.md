# Radar water measurement: plain Otsu (old) against Edge Otsu, block Otsu and cleaned radar (new)

Written by `scripts/compare_radar_methods.py` on 2026-11-15 14:27 UTC. Every number is read from the database.

Edge Otsu (Markert et al. 2020, section 2.3.2) with the paper's numbers: initial cutoff -16.0 dB, edges over 200 m, 1500 m buffer on each side. Block Otsu (Tan et al. 2023) with the paper's 250-pixel patch. Cleaned radar: border noise removal, Refined Lee speckle filter and volume-model terrain correction (sailab/s1_clean.py, our own code after Mullissa et al. 2021); layover and shadow pixels become no data. All methods use the same 10 degree slope mask and the same refusals. Passes with no stored picture on this machine: 0.

### KRB (median usable optical area 255.14 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 192 | 30 | 19 of 192 (9.9%) | +7.71 ha, 15 |
| Edge Otsu (new) | 222 | 194 | 28 | 17 of 194 (8.8%) | +6.18 ha, 16 |
| Block Otsu (new) | 222 | 186 | 36 | 11 of 186 (5.9%) | +7.57 ha, 15 |
| Cleaned radar, plain Otsu | 222 | 186 | 36 | 13 of 186 (7.0%) | +7.23 ha, 15 |
| Cleaned radar, block Otsu | 222 | 186 | 36 | 13 of 186 (7.0%) | +7.18 ha, 15 |

Share of the usable window the Edge Otsu buffer covered: median 97% (1.0 would be the same as plain Otsu).
Block size chosen by block Otsu: 250 px: 222 passes.

### ATS (median usable optical area 106.12 ha)

| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | Radar minus optical within 3 days: median, pairs |
|---|---|---|---|---|---|
| Plain Otsu (old) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Edge Otsu (new) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Block Otsu (new) | 222 | 173 | 49 | 10 of 173 (5.8%) | -6.83 ha, 21 |
| Cleaned radar, plain Otsu | 222 | 179 | 43 | 13 of 179 (7.3%) | -6.59 ha, 21 |
| Cleaned radar, block Otsu | 222 | 179 | 43 | 13 of 179 (7.3%) | -6.59 ha, 21 |

Share of the usable window the Edge Otsu buffer covered: median 100% (1.0 would be the same as plain Otsu).
Block size chosen by block Otsu: ; whole window as one group (narrower than 2 x 250 px, same as plain Otsu): 222 passes.


**Cleaned radar, full run (all 444 passes cleaned).** Karambar: 13 clearly wrong values instead of 19 with
plain Otsu, but block Otsu without cleaning is still lower (11). Atro Sar: cleaning measures 6 more passes
(179 instead of 173) but has 3 more clearly wrong values (13 instead of 10). So cleaning helps at Karambar
and does not at Atro Sar; block Otsu alone remains the best radar method on these two lakes. Cleaning adds
nothing to block Otsu at either lake (identical counts).
