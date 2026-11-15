# Critical roads below Shishper lake (Sugiura and Kurauchi 2023)

Written by `scripts/critical_roads_shishper.py` on 2026-11-15 10:05 UTC.
Roads: 644 junction-to-junction roads from OpenStreetMap (580 junctions); 6 road ends leave the mapped area and are used as the places help comes from.
Bridges found by Tarjan's method in the whole road graph: 321.

LEC = how many roads must ALL be lost before the village is cut off from every road leaving the area.
LEC 1 = a single road is enough; each critical set then holds one road.

| Village | LEC | Smallest road sets that cut it off | Sets with a road on the flood path | Nearest junction |
|---|---|---|---|---|
| village 1 | 1 | 1 | 0 | 288 m |
| village 2 | 3 | 23 | 3 | 112 m |
| Sheraz | 3 | 15 | 2 | 208 m |
| Mayoon | 1 | 9 | 0 | 95 m |
| Murtazabad | 1 | 3 | 0 | 313 m |
| village 6 | 1 | 1 | 0 | 25 m |
| Ahmadabad | 1 | 5 | 0 | 63 m |
| Altit | 1 | 2 | 0 | 88 m |
| Salamanbad | 0 | 0 | 0 | 151 m |
| Khanabad | 1 | 4 | 0 | 129 m |
| Gulmet Nagar | 1 | 2 | 0 | 78 m |
| Pisan | 1 | 2 | 0 | 434 m |
| Minapin | 1 | 4 | 0 | 42 m |
| Hakucher Nagar | 3 | 616 | 352 | 787 m |
| village 15 | 1 | 1 | 0 | 200 m |
| Askurdass Nagar | 1 | 1 | 0 | 791 m |
| Shayar Nagar | 2 | 3 | 2 | 532 m |
| Sumayar Nagar | 1 | 2 | 0 | 116 m |
| Fiazabad Hunza | 1 | 3 | 0 | 702 m |
| Nasirabad Hindi | 2 | 61 | 0 | 24 m |
| Hussinabad | 1 | 13 | 0 | 55 m |
| Baltit | 1 | 1 | 0 | 114 m |
| village 23 | 1 | 5 | 0 | 60 m |
| village 24 | 2 | 1 | 0 | 243 m |
| Tongdass Jafarabad | 1 | 2 | 0 | 188 m |
| Nilt | 1 | 1 | 0 | 171 m |
| Thol Nagar | 1 | 1 | 0 | 81 m |
| Masot Thol Nagar | 2 | 86 | 0 | 39 m |
| Miachar Nagar | 1 | 7 | 0 | 126 m |
| Dodimal Nagar | 1 | 9 | 0 | 929 m |
| Phakar | 1 | 1 | 0 | 1375 m |
| Hasanabad | 1 | 1 | 0 | 88 m |
| Garelth | 2 | 8 | 0 | 77 m |
| village 34 | 2 | 2 | 0 | 159 m |
| village 35 | 1 | 2 | 0 | 64 m |
| village 36 | 1 | 3 | 0 | 204 m |
| village 37 | 2 | 35 | 0 | 211 m |
| village 38 | 1 | 1 | 0 | 248 m |
| village 39 | 1 | 1 | 0 | 105 m |
| village 40 | 1 | 4 | 0 | 68 m |
| village 41 | 1 | 8 | 0 | 485 m |
| village 42 | 1 | 7 | 0 | 80 m |
| village 43 | 1 | 8 | 0 | 149 m |
| village 44 | 1 | 9 | 0 | 87 m |
| Duikar | 1 | 4 | 0 | 163 m |
| Shiskin | 1 | 10 | 0 | 1400 m |
| Dorkhan | 2 | 1 | 0 | 37 m |
| village 48 | 1 | 5 | 0 | 525 m |
| village 49 | 1 | 5 | 0 | 756 m |
| village 50 | 2 | 15 | 0 | 110 m |

### Sets that include a road on the likely flood path

- **village 2** (LEC 3): trunk (OSM 27223423) [on flood path] + Aliabad Karimabad Road (OSM 36920468) + trunk (OSM 651792496); trunk (OSM 27223423) [on flood path] + Aliabad Karimabad Road (OSM 36920468) + trunk (OSM 651792496); trunk (OSM 27223423) [on flood path] + trunk (OSM 651792496) + Aliabad Karimabad Road (OSM 36920468)
- **Sheraz** (LEC 3): trunk (OSM 27223423) [on flood path] + Aliabad Karimabad Road (OSM 36920468) + trunk (OSM 651792496); trunk (OSM 27223423) [on flood path] + Aliabad Karimabad Road (OSM 36920468) + trunk (OSM 651792496)
- **Hakucher Nagar** (LEC 3): trunk (OSM 651792496) + trunk (OSM 27223388) + unclassified (OSM 651792493) [on flood path]; unclassified (OSM 651792494) [on flood path] + trunk (OSM 27223388) + trunk (OSM 651792496); trunk (OSM 27223388) + trunk (OSM 651792496) + unclassified (OSM 651792493) [on flood path]; unclassified (OSM 651792494) [on flood path] + trunk (OSM 27223388) + trunk (OSM 651792496); trunk (OSM 27223388) + unclassified (OSM 651792493) [on flood path] + trunk (OSM 651792496); unclassified (OSM 651792494) [on flood path] + trunk (OSM 27223388) + trunk (OSM 651792496); trunk (OSM 27223423) [on flood path] + trunk (OSM 27223388) + secondary (OSM 651792489); trunk (OSM 27223423) [on flood path] + trunk (OSM 27223388) + secondary (OSM 651792489); trunk (OSM 27223423) [on flood path] + trunk (OSM 27223388) + unclassified (OSM 651792493) [on flood path]; trunk (OSM 27223423) [on flood path] + unclassified (OSM
- **Shayar Nagar** (LEC 2): unclassified (OSM 651792494) [on flood path] + secondary (OSM 651792489); secondary (OSM 651792489) + unclassified (OSM 651792493) [on flood path]

This is a likely path, not a flood simulation: a road on the path may or may not be damaged.
