# Claims sweep 2 (2026-11-09, about 15:00 UTC)

Every factual claim in `README.md`, `docs/DEMO_SCRIPT.md`, `docs/comparison/README.md`, `docs/LIVE_CHECK_FALLBACK.md`,
and the code comments/log messages that make claims, was checked against a file, a test, the database or GitHub.

## Checked and backed by evidence
| Claim | Evidence |
|---|---|
| Every number in the README database table (scenes, too cloudy, ok/refused, area ranges, scores, dates) | direct SQL on `sailab_glof.db`, all equal |
| 694 measurement rows, 406 usable, 288 refused | SQL: `select sensor, status, count(*) from measurement group by 1,2` |
| 20 inherited tests pass unchanged | `logs/2026-11-07_step1_pytest_baseline.log` (20 passed) |
| Atro Sar 105.82 ha at 1500/2000/2500 m | `logs/2026-11-08_step5_atro_sar_radius_check.log` |
| Karambar 2025-08-12: 198.31 ha, score −2.96 | SQL (−2.9568) |
| 462.88 ha snowfield, 0.14 ha frozen, 87.42 ha cloud | `logs/2026-11-08_cdf_on_outlier_scenes.log` |
| 43 plausible values rejected (12 + 31) | `logs/2026-11-08_cdf_before_after.md` line 18 |
| Atro Sar 7 of 17 cloud decisions differ | `logs/2026-11-08_step4_live_find_new_scenes.log` (7 "differs") |
| 5°/10°/15°/20° give 258.65 / 267.52 / 275.39 / 281.62 ha | `logs/2026-11-09_radar_slope_mask_original_karambar.log` |
| Radar anomalies +50.3 and −7.4 | `logs/2026-11-09_radar_validation.log` lines 54, 57 |
| 29 of 361 radar values clearly wrong (15 % rule); 28 under the earlier hand-set ranges | `logs/2026-11-09_radar_error_count.log`, `logs/2026-11-09_radar_validation.log` line 49-51 |
| Backfill images about 850 MB | `du -sh data/backfill` = 850M |
| POST /live/check is the only route that changes anything | `tests/test_webapp_previews.py` (route test) |
| Live check: 42 scenes found, 12 measured, all identical | `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log` |
| Live check outcomes and timings (11 s, 32 s) | `logs/2026-11-09_gui_live_check_outcomes_evidence.md` |
| Failure messages for usage limit / key / other errors | `tests/test_webapp_live.py::test_failure_explanations_are_chosen_from_the_real_error` |
| "171 tests passed" in scheduled run 6 (closed after this sweep, 15:20 UTC): `171 passed, 1 warning in 6.13s` | `logs/2026-11-08_scheduled_run_6_github_test_step.log`, fetched from GitHub's job-log API (`gh run view --log` had returned nothing) |
| Scheduled runs: 1 | `gh run list` (4 runs; 1 with event "schedule", 2026-11-08 21:31 UTC) |

## Found wrong or unbacked in this sweep, and fixed
1. **`docs/comparison/README.md` said "Radar is not built"** and "Only Sentinel-2 points" (written 8 Nov, before radar).
   Fixed: row rewritten for the current screens; the images are marked as 8 November.
2. **`webapp/main.py` comment said the app has "no POST/PUT/DELETE route at all"**; `POST /live/check` exists. Fixed.
3. **`sailab/pipeline.py` log message said "optical-only build"** for too-cloudy optical scenes. Reworded.
4. **README said "Two" tests use the original real GeoTIFFs**; it is four tests using three files. Fixed.
5. **My previous sweep wrongly said the old "28 of 361" had no evidence file.** It is in
   `logs/2026-11-09_radar_validation.log` (18 + 10, hand-set summer ranges). That sweep searched for the text
   "28 of 361" and missed it. The README now gives both counts and both rules.
6. **694 vs 406 were not defined anywhere in the docs.** README now has a side-by-side table.

## Still not backed from this repository
- **"Karambar measured about 10 % below its published area"**: from the earlier project; marked as such in the README.
- **Scheduled runs 2 and 3**: cannot exist before 2026-11-09 18:00 UTC and 2026-11-10 18:00 UTC.
- **`data/scenes/` commit step**: correct in code, never yet exercised on GitHub (no scheduled run has found a new scene).
