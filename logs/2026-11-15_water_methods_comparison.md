# Camera water measurement: old method against the newer ones

Written by `scripts/compare_water_methods.py` on 2026-11-15 08:55 UTC. Every number is read from the database.

- **NDWI, cutoff 0.2 (old):** the stored measurement.
- **NDWI, Otsu cutoff:** the old index with Otsu's cutoff, to show the effect of the cutoff alone.
- **SMBWI, Otsu cutoff (new):** Su et al. (2024), equation (1), with Otsu's cutoff. The paper itself
  separates water with ISODATA clustering; the Otsu cutoff is this project's choice (plain Otsu, the
  baseline of the camera-cutoff row).

Every method uses the same lake growing and the same refusal checks (cut off by the window, cloud,
snow), so a refusal means the same thing for each.

Run: {'ndwi_otsu measured': 254, 'smbwi_otsu measured': 254}

### ATS

| Method | Scenes measured | Usable (ok) | Refused | Median area of usable (ha) | Range (ha) | Camera minus radar within 3 days: median, pairs |
|---|---|---|---|---|---|---|
| NDWI, cutoff 0.2 (old) | 125 | 25 | 100 | 106.12 | 105.16 to 107.17 | +6.83 ha, 21 |
| NDWI, Otsu cutoff | 125 | 25 | 100 | 105.23 | 104.80 to 106.52 | +5.66 ha, 21 |
| SMBWI, Otsu cutoff (new) | 125 | 25 | 100 | 110.76 | 108.03 to 114.76 | +11.26 ha, 21 |

On the 25 scenes where both the old method and SMBWI give an area, SMBWI is +4.6% different from the old area (median; range +1.6% to +8.1%).
Scenes the old method refused but SMBWI measured: 0. Scenes the old method measured but SMBWI refused: 0.

### KRB

| Method | Scenes measured | Usable (ok) | Refused | Median area of usable (ha) | Range (ha) | Camera minus radar within 3 days: median, pairs |
|---|---|---|---|---|---|---|
| NDWI, cutoff 0.2 (old) | 129 | 20 | 109 | 255.14 | 198.31 to 257.83 | -7.71 ha, 15 |
| NDWI, Otsu cutoff | 129 | 20 | 109 | 257.30 | 198.89 to 259.13 | -6.45 ha, 13 |
| SMBWI, Otsu cutoff (new) | 129 | 0 | 129 | - | - | - |
Scenes the old method refused but SMBWI measured: 0. Scenes the old method measured but SMBWI refused: 20.

**Why SMBWI refuses every Karambar scene.** Otsu's cutoff over the whole Karambar window falls far
below the water values (about -0.75 to -0.81 on the scenes checked), because the largest split in that
window's SMBWI histogram is between snow or bright ground and everything else, not between water and
land. Rock and ground then count as water, the grown lake reaches the edge of the window (about 550 ha
against a 257 ha lake) and the existing check refuses it as possibly cut off. No wrong area was saved.
This is the same failure the plain-Otsu radar method had before its slope mask. The paper itself uses
ISODATA clustering, and the project plan pairs SMBWI with an optimised Otsu (Che et al. 2025), which is
not yet implemented (the paper is not available here). So SMBWI with plain Otsu is not usable at
Karambar, and this table should not be read as SMBWI failing in general.

**At Atro Sar** SMBWI measures every scene NDWI measures, but reads larger (median +4.6%). Its
agreement with radar is worse than NDWI's. One possible cause, untested: B9 is a 60 m band, and
resampling it to 10 m blurs the shoreline, so shore pixels can look like water.

Graph: `2026-11-15_water_methods_area.png` (black and white).
