# SailAb GLOF — automated lake monitoring (live build)

Final-year project. SailAb GLOF is designed as a five-stage early-warning system for glacial lake
outburst floods (GLOFs) in Pakistan: **Acquisition → Measurement → Risk Scoring → Downstream Analysis
→ Alerting**. This repository is the **live build of the first three stages** for **two lakes**,
running automatically on real Sentinel-2 satellite data.

> **What this is not.** This is a working, automated **monitoring prototype**. It is **not** a
> validated early-warning system, it sends **no alerts**, and it has **never detected a real
> outburst** (neither monitored lake has one on record). Please read [Limitations](#limitations)
> before quoting any number from it.

*Status as of 2026-11-08 (evening). Sections marked ⏳ change as the scheduled runs accumulate.*

---

## What runs automatically

Every night at **23:00 Pakistan time (18:00 UTC)**, GitHub Actions
([`.github/workflows/daily_run.yml`](.github/workflows/daily_run.yml)) does the following with no
human involved:

1. Installs the pinned packages and runs the **full test suite** (171 tests). If any test fails, the
   pipeline does not run, so broken code can never write to the database.
2. Signs in to Google Earth Engine with a **service-account key** stored as an encrypted GitHub
   secret (no browser, no person).
3. For each lake, lists new Sentinel-2 scenes since the newest one already stored, and measures the
   **cloud over the lake itself** (not over the whole 100 km tile), using Sentinel-2's own scene
   classification band and our own counting code.
4. Scenes with more than **10 % cloud over the lake** are **recorded but not downloaded** (this build
   is optical-only; see Limitations).
5. Clear scenes: downloads **only the small lake window** (bands B2, B3, B4, B8, B11 + SCL, 10 m,
   UTM 43N), measures the lake, and stores the measurement.
6. Scores each usable measurement against the lake's own **seasonal baseline** and stores the score.
7. Writes a `run_log` row (start, finish, counts, and the **real error text** if anything failed),
   writes a timestamped log file to `logs/runs/`, and **commits the database and logs back to this
   repository** — also after a failed run, so failures stay visible.

The run history is public: open the **Actions** tab of this repository. Each bot commit
("Automated run: <UTC time> (success|failure)") contains that run's log.

⏳ **Scheduled runs so far: 1** (of the 3 on different days needed).

| Date (UTC) | Trigger | Result |
|---|---|---|
| 2026-11-08 12:00 | manual (setup test) | success, no new scene |
| 2026-11-08 19:01 | manual (after pinning Ubuntu 24.04) | success, no new scene |
| **2026-11-08 21:31** | **schedule** (the 18:00 UTC slot, started 3.5 h late by GitHub) | **success**, 171 tests passed, no new scene since 2026-11-05; bot commit `5872d48`, `run_log` row 6 |

Manual runs do not count as automatic. GitHub can start scheduled runs late or skip them, so the
Actions tab is the record of which ones actually happened.

## What still needs a human

- **Adding a lake** (coordinates, window size, growth limit): `sailab/db.py`, `SEED_LAKES`.
  Changing a stored lake's values is deliberately refused unless done on purpose (see
  `logs/2026-11-08_atro_sar_window_change.log` for the one time this was done, and why).
- **Renewing the Earth Engine key** if it is revoked or expires (the run will fail visibly with the
  error in `run_log`).
- **The historical backfill** (2023-01-01 → 2026-11-05) was **started once by hand**
  (`python scripts/run_once.py --backfill`). It ran the same pipeline code, but it is not an
  automatic run. Every backfilled row has a `downloaded_at` of 2026-11-08.
- **Interpreting the results.** Nothing in this repository decides that a lake is dangerous.

## Explicitly out of scope for this build

- **Downstream Analysis** (flood path, road network) and **Alerting**. The tested code for flood
  path tracing and bridge finding is in `sailab/terrain.py`, `flood_path.py` and `network.py`, but it
  is **not connected** to this pipeline.
- **The trained risk model.** Only the seasonal-baseline fallback (FR-14/FR-18) is used.
- **Radar (Sentinel-1).** Cloudy scenes are recorded, not measured. The known radar failure on steep
  terrain (region growing leaking into mountain shadow: 975.9 ha against a real 237.2 ha in the
  earlier project tests) is unchanged and unaddressed.

---

## The two lakes

| Code | Lake | Centre (lon, lat) | Window radius | Growth limit |
|---|---|---|---|---|
| KRB | Karambar Lake | 73.7053229, 36.880833 | 2500 m | 2500 m |
| ATS | Atro Sar | 73.65037, 36.64458 | 1500 m | 1500 m |

The coordinates are the exact values the project's earlier real results were computed from.
**Atro Sar's window was changed from 800 m to 1500 m on 2026-11-08** because the 800 m export cut the
lake off at the window's edge: the earlier reported **76.51 ha was only the part inside the window**.
On the same 2026-07-18 scene the whole lake measures **105.82 ha** (identical at 1500, 2000 and
2500 m). Evidence: `logs/2026-11-08_step5_atro_sar_radius_check.log`.

## Data source

All imagery is **ESA Copernicus Sentinel-2 Level-2A** surface reflectance, collection
`COPERNICUS/S2_SR_HARMONIZED`, accessed through **Google Earth Engine** with a service account
registered for noncommercial use. Every stored scene is identified by its Earth Engine scene id
(e.g. `20260718T054641_20260718T055712_T43SCA`) and can be re-downloaded by anyone with Earth Engine
access. The SHA-256 of every downloaded file is written to the run log.

The water detection, region growing, area, cloud and snow checks and risk scores are all computed
by this repository's own code, not by Earth Engine.

---

## How a measurement is made (and when it is refused)

Code: `sailab/pipeline.py` → `measure_scene`, using the unchanged, earlier-tested functions in
`sailab/measurement.py`.

1. NDWI per pixel from B3 (green) and B8 (near-infrared); water if NDWI > **0.2**.
2. The lake centre is located from the file's own georeferencing.
3. Water is grown outward from the centre (4-connected), within the lake's growth limit.
4. Area = pixel count × 100 m².

A measurement is recorded as **`insufficient_observation` (never as a zero)** when:

- the centre pixel is not water (e.g. frozen lake);
- the lake touches missing data at the window edge (it may be cut off);
- **cloud or cloud shadow touches the lake** (check D);
- **snow or ice touches the lake, or covers more than half of the lake circle** (check C).

Checks C and D were added after the first backfill showed real errors: a snowfield counted as lake
(462.88 ha for a ~250 ha lake), a frozen lake measured as 0.14 ha, and cloud hiding part of a lake
(87.42 ha instead of ~106). See `logs/2026-11-08_backfill_outliers_true_colour_vs_detected.png`.
They are deliberately **strict**: they also rejected 43 measurements that looked correct (often for
only a few noisy edge pixels). We chose fewer measurements over wrong ones.

## How a risk score is made

Code: `sailab/risk.py` (unchanged) via `sailab/pipeline.py`.

- **Baseline** = mean of the lake's earlier usable measurements in the **same calendar month**;
  **spread** = their sample standard deviation; **score** = (new extent − baseline) / spread.
- Only measurements from **before** the scene's date are used.
- **Check F:** no score unless that month has **at least 5 earlier values from at least 2 different
  years**; otherwise the score is `insufficient_history`. With only 2–3 values the spread is tiny and
  modest changes produced meaningless scores (e.g. −49.6) in the first backfill.
- A score is a **statistical deviation**, not a danger level or a probability.

---

## Current contents of the database (`sailab_glof.db`)

⏳ As of 2026-11-08, after the backfill (run 3) and one manual GitHub run (run 4):

| | Karambar (KRB) | Atro Sar (ATS) |
|---|---|---|
| Scenes recorded (2023-01-05 → 2026-11-05) | 307 | 304 |
| Too cloudy for optical (recorded, not downloaded) | 178 | 179 |
| Measured `ok` | 20 | 25 |
| `insufficient_observation` | 109 | 100 |
| `ok` area range | 198.31 – 257.83 ha | 105.16 – 107.17 ha |
| Risk scores `ok` / `insufficient_history` | 8 / 12 | 11 / 14 |

So **58 % of all scenes (357 of 611) were too cloudy over the lake** for optical measurement — the
cloud problem the project's radar fallback is meant to solve, measured with our own data.

**`run_log` history:**

| Row | What | Result |
|---|---|---|
| 1 | First backfill attempt (by hand) | **Failed** at sign-in: `run_once.py` never signed in to Earth Engine. Bug fixed, test added. Kept as a real failure record. |
| 2 | First backfill (by hand), before checks C/D/F | Completed. Its rows were replaced (see below); the row is kept as history. |
| 3 | Backfill re-run (by hand) with checks C/D/F | Completed: 611 scenes, 254 downloads. **These are the rows in the database now.** |
| 4 | First GitHub Actions run (triggered by hand) | Completed: no new scenes since 2026-11-05. |
| 5 | Second GitHub Actions run (triggered by hand, after pinning the runner to Ubuntu 24.04) | Completed: no new scenes. |
| 6 | **First scheduled run** (GitHub's scheduler, 2026-11-08 21:31 UTC) | Completed: no new scenes. |

The pre-C/D/F database and its 5-band images are archived locally (`data/archive_v1/`, not in this
repository); the comparison is in `logs/2026-11-08_cdf_before_after.md`.

**Downloaded images:** backfill images (~345 MB) are kept on the developer's machine, **not** in this
repository (`data/backfill/` is git-ignored). Each can be re-downloaded by its scene id and checked
against the SHA-256 in `logs/runs/2026-11-08T112314Z_backfill.log`. Images downloaded by the
scheduled runs are committed to `data/scenes/`.

---

## Evidence that the pieces work on real data

| Claim | Evidence |
|---|---|
| Automated downloads match the project's original manual Earth Engine exports **pixel for pixel** (0 differing values: Karambar 1,280,175, Atro Sar 132,845; bands 1-5) | `logs/2026-11-08_item2_live_download_vs_original_final.log`, `logs/2026-11-08_cdf_live_6band_vs_original.log` |
| The original Karambar file still gives **237.22 ha** (reported as 237.2) with the unchanged code | `tests/test_pipeline.py::test_real_karambar_original_file_reproduces_237_2_ha` |
| The original Atro Sar file (76.51 ha) is **cut off** by its window | `tests/test_pipeline.py::test_real_atro_sar_original_file_is_flagged_as_cut_off_by_the_window` |
| Cloud measured over the lake differs from the tile value in many scenes (Atro Sar: 7 of 17 decisions differ) | `logs/2026-11-08_step4_live_find_new_scenes.log` |
| A failed run is recorded, not hidden | `run_log` row 1; `logs/runs/2026-11-08T103538Z_backfill.log` |

**About the tests (171, all passing):** most use small synthetic grids with hand-calculated expected
answers — they prove the algorithms compute correctly, **not** real-world accuracy. Two use the
project's original real GeoTIFFs (`tests/data/`). The Earth Engine tests replace Earth Engine with a
mock (stated in the test file); the real connection is proven only by the live-run logs. The 20
tests inherited from the earlier project pass unchanged.

---

## Limitations

1. **No real outburst has been detected or tested.** Neither lake has a recorded GLOF; the risk
   score has never been checked against a real flood event.
2. **Newly formed lakes cannot be scored** (check F needs earlier same-month years). These are often
   the dangerous ones (e.g. Shisper, formed around 2018–19).
3. **Blind under cloud:** optical only; 58 % of scenes were too cloudy over the lake. Radar is not
   built.
4. **Blind in winter:** frozen or snow-covered lakes are refused (correctly), so there are few or no
   measurements from roughly November to May. Scheduled runs before spring may produce no `ok` area.
5. **Under-detection:** the NDWI cut-off of 0.2 misses real water on some days. Known and **not
   fixed**. Karambar 2025-08-12 (198.31 ha, score −2.96) is very likely this, not a real change.
6. **Strict checks lose good data:** 43 plausible measurements were rejected.
7. **Judgement-call settings:** the 10 % cloud limit was chosen from one month of data; the
   thresholds in checks C, D, F are reasoned choices, not calibrated values.
8. **Sentinel-2's classification can mistake snow for cloud** (seen in real scenes). This only makes
   the pipeline refuse a measurement, never invent one.
9. **The growth limit can cut a lake short without a warning** (seen with Atro Sar at 1200 m before
   the window change).
10. **Measurement accuracy is only roughly known:** Karambar measured about 10 % below its published
    area in the earlier project tests.
11. **GitHub scheduling:** scheduled runs can start late or occasionally be skipped by GitHub.

---

## The web app (local, for demonstration)

`.venv/bin/uvicorn app:app`, then open http://localhost:8000. It needs no internet connection except for
the Live check button.

- **Dashboard** and **Lake Detail**: every number is read from the database (a test checks that the
  reference designs' sample values never appear). `scripts/verify_gui_numbers.py` re-checks every number
  on both screens against independent SQL; the cold run-through result is in
  `logs/2026-11-08_gui_cold_runthrough_numbers.md`.
- **Working copy:** at start-up the app copies `sailab_glof.db` to `.webapp/` and shows which commit it
  came from. It never writes to the published file, so it cannot collide with the nightly bot's commits.
- **Live check:** one button runs the real pipeline for both lakes, writing to the working copy only.
  Tested for real: no new scene (about 10 s), network cut (fails after about 33 s with a plain-language
  error), and a copy rewound to 2026-08-15 (42 scenes found, 12 measured; every row and every file
  identical to the backfill: `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log`).
- **Design previews** (Confirm advisory, Delivery status, Risk threshold): the design's own sample data,
  watermarked, every control disabled. `POST /live/check` is the only route in the app that changes anything.
- The screens next to the reference designs, and why they differ: `docs/comparison/`.
- What to click and say in a demo, including if the live check fails: `docs/DEMO_SCRIPT.md`.

## Repository layout

```
sailab/
  measurement.py  acquisition.py  risk.py     earlier-tested core modules (unchanged)
  terrain.py  flood_path.py  network.py       downstream analysis modules (unchanged, not wired in)
  db.py                    SQLite schema, inserts, history, seed lakes
  earth_engine_client.py   Earth Engine sign-in, scene listing, lake-window cloud, download
  pipeline.py              the run: stages wired together, checks C/D/F, resume, run log
  queries.py               read-only queries behind every number the web app shows
webapp/                    FastAPI + Jinja2 app: pages, offline SVG charts, live check, design previews
app.py                     web app entry point (uvicorn app:app)
scripts/
  run_once.py              entry point (GitHub Actions); --backfill for the one-off historical run
  init_db.py               create the database and seed the two lakes
  verify_gui_numbers.py    check every number on the two real screens against the database
docs/                      reference designs, side-by-side comparison, demo script
tests/                     171 tests; tests/data/ holds the two original real GeoTIFFs
logs/                      verification logs; logs/runs/ has one log per pipeline run
sailab_glof.db             the database (open with DB Browser for SQLite)
```

## Running it yourself

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # no credentials needed
```

A live run needs an Earth Engine service-account key, either in the `EE_SERVICE_ACCOUNT_KEY`
environment variable (the key's JSON text) or at `~/.config/sailab/ee-key.json`:

```bash
.venv/bin/python scripts/run_once.py
```

Never commit the key. The GitHub workflow reads it from the repository secret
`EE_SERVICE_ACCOUNT_KEY`.
