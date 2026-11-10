# Lake centre coordinates checked against the Hi-MAG glacial lake inventory (2026-11-11)

**What was checked.** The two lake centres in `sailab/db.py` (`SEED_LAKES`) had no cited source. They are the
values the project's earlier results were computed from, and they are **not changed** here. This note only
checks them against an independent, published lake inventory.

**The inventory.** HMA Glacial Lake Inventory (Hi-MAG), Version 2.0 (September 2020). Key Laboratory of Digital
Earth Science, Aerospace Information Research Institute, Chinese Academy of Sciences. Authors as listed in the
dataset's own metadata file: Fang Chen, Meimei Zhang, Huadong Guo, Simon Allen, Jeffrey S. Kargel, Umesh K.
Haritashya, C. Scott Watson. Annual glacial lake outlines, 2008 to 2017, from Landsat at 30 m.
(Citation details are copied from `Hi-MAG_metadata.docx` shipped with the dataset; the journal reference for the
dataset is not in that file and is not given here.)

**How.** For each of our centres, the nearest lake in the Hi-MAG table clipped to northern Pakistan (1,339 lakes,
`himag_pakistan_lakes.csv`, built from the Hi-MAG shapefiles by the earlier project's `tools/himag.mjs`) was
found by straight-line distance between our centre and the Hi-MAG lake's own point.

| Our lake | Our centre (lon, lat) | Nearest Hi-MAG lake | Hi-MAG point (lon, lat) | Distance | Hi-MAG type | Hi-MAG area 2017 | Next nearest Hi-MAG lake |
|---|---|---|---|---|---|---|---|
| Karambar (KRB) | 73.7053229, 36.880833 | GL073703E36879N | 73.70467, 36.87964 | 0.144 km | proglacial lake | 2.48619 km² (248.6 ha) | 1.81 km away, 0.018 km² |
| Atro Sar (ATS) | 73.65037, 36.64458 | GL073645E36644N | 73.64581, 36.64446 | 0.408 km | proglacial lake | 0.98234 km² (98.2 ha) | 1.235 km away, 0.010 km² |

**What this shows.** Each centre lies within a few hundred metres of the point of one large Hi-MAG lake, and the
next nearest Hi-MAG lake is tiny and over a kilometre away, so there is no doubt which lake each centre means.
Our own 2023 to 2026 optical areas (Karambar 198 to 258 ha, Atro Sar 105 to 107 ha) are the same size of lake as
the Hi-MAG 2017 areas.

**What this does not show.** The centres were not taken from Hi-MAG, so Hi-MAG is a check, not the origin. The
distance is to the Hi-MAG point, not to the shoreline. The Hi-MAG areas are from 2017 and 30 m Landsat, so they
are not expected to equal our 10 m Sentinel-2 areas.
