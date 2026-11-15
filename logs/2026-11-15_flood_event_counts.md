# Past floods usable for the risk model: counts after every filter

Written by `scripts/count_flood_events.py` on 2026-11-15 14:01 UTC, from these files:
- Global database (Lützow, Veh, Korup 2023), `glofdatabase_v4-2.ods`, High Mountain Asia sheets only
- High Mountain Asia database (Shrestha, Steiner and others 2023), `HMAGLOFDB.csv` (release v1.3.0)

Filters, in this order: event year 2016 or later; exact day known; lake coordinates to at least 3 decimal places (about 100 m); dammed by moraine or ice.

### Global database

| Step | Floods left | of which in Pakistan | Removed by this step |
|---|---|---|---|
| all records | 1398 | 158 | - |
| after 2015 | 409 | 18 | 989 |
| exact date | 39 | 13 | 370 |
| exact location | 39 | 13 | 0 |
| moraine or ice dammed | 28 | 9 | 11 |

### High Mountain Asia database

| Step | Floods left | of which in Pakistan | Removed by this step |
|---|---|---|---|
| all records | 768 | 151 | - |
| after 2015 | 61 | 18 | 707 |
| exact date | 53 | 18 | 8 |
| exact location | 49 | 17 | 4 |
| moraine or ice dammed | 35 | 12 | 14 |

### Both databases together

A flood is counted once when both databases have it on the same day for lakes within 2 km.

- Usable in the global database: **28**
- Usable in the High Mountain Asia database: **35**
- In both: **14**
- **Usable floods, counted once: 49**
- of which in Pakistan (never used for training): **16**
- **Left for training, outside Pakistan: 33**
- Dam type of the usable floods: {'ice': 20, 'moraine': 29}
- Countries: {'Pakistan': 16, 'China': 13, 'Kyrgyzstan': 6, 'Nepal': 5, 'India': 4, 'Afghanistan': 2, 'Bhutan': 2, 'Kazakhstan': 1}

**What this means for a trained model.** These are counts of flood events, not of training rows. A model
also needs each lake's area history from before its flood, which has to be measured from satellite
pictures first; that step has not been done.
