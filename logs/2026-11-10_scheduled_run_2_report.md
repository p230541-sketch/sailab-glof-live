# Scheduled run 2 (GitHub run 42732745979, pipeline run 9), checked 2026-11-10 07:40 UTC

Source: `gh run list`, `gh run view --json jobs`, the job log from
`gh api repos/rayannkhn/sailab-glof-live/actions/jobs/129554539971/logs`, and the bot commit 69378dc
(`git fetch`; database read from `git show 69378dc:sailab_glof.db`, nothing pulled into the working tree).

## The run
| Item | Value |
|---|---|
| Event | `schedule` (second scheduled run; the first was 42525620352, 2026-11-08 21:31 UTC) |
| Cron slot | 2026-11-09 18:00 UTC; GitHub started it 2026-11-10 01:01:47 UTC (about 7 h late, GitHub's scheduler delay) |
| Job | run-pipeline 129554539971, 01:01:50 to 01:02:43 UTC, conclusion success, every step success |
| Test step | `216 passed, 1 warning in 8.51s` (warning: Starlette httpx deprecation) |
| Pipeline | run 9: 2 lakes, 2 scenes recorded, 2 downloaded, 2 measurements, 0 risk scores, errors None |
| Bot commit | 69378dc "Automated run: 2026-11-10T01:02:39Z (success)", SailAb GLOF Bot, 4 files: sailab_glof.db, 2 GeoTIFFs, logs/runs/2026-11-10T010231Z.log |
| run_log row | `9 | 2026-11-10T01:02:31+00:00 | 2026-11-10T01:02:39+00:00 | 2 | 2 | (no error)` |

## What it found
- Optical: one Sentinel-2 scene per lake after 2026-11-04 (20261105T055021), already recorded, skipped. No new optical scene.
- Radar: new Sentinel-1D pass on 2026-11-09 for both lakes (the gap after 28 Oct is closed):

| Lake | Scene row | Area | Threshold | Optical median (n) | Difference | 15 % error rule |
|---|---|---|---|---|---|---|
| KRB | 1052 | 257.55 ha (25,755 px) | −18.45 dB | 255.14 ha (20) | +0.9 % | within |
| ATS | 1053 | 97.14 ha (9,714 px) | −15.54 dB | 106.12 ha (25) | −8.5 % | within |

Both are not risk-scored (SCORE_RADAR is off). They are November (winter) radar values, which are not validated;
"within 15 %" only means they do not count as clearly wrong by the stated rule.

## Files checked
SHA-256 of the committed GeoTIFFs equals the hash in the run log:
- KRB `S1D_..._3D25.tif` 67aae047305f2525c366a2d38e50bbeaa0f9774e3aa1bb525de8d1011d5a5d77
- ATS `S1D_..._443A.tif` 1b5c5a9a772ea5d5a959353a02180ee2916e50b7b810f3fc8db303ac7e4ea256

This is the first run on GitHub that downloaded scenes, so the `data/scenes/` commit step has now been exercised
(claims sweep 2 listed it as never exercised).

## Database totals after run 9
1,053 scenes (was 1,051), 696 measurement rows (was 694), 408 usable (was 406), 45 risk scores (unchanged).

## Job log, pipeline section (verbatim)
2026-11-10 01:02:31,707 INFO run_once: mode: scheduled/normal, data dir: /home/runner/work/sailab-glof-live/sailab-glof-live/data/scenes
2026-11-10 01:02:31,907 INFO sailab.pipeline: run 9 started
2026-11-10 01:02:33,013 INFO sailab.pipeline: signed in to Earth Engine as sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com
2026-11-10 01:02:34,185 INFO sailab.pipeline: KRB: 1 scenes listed after 2026-11-04
2026-11-10 01:02:34,186 INFO sailab.pipeline: KRB 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
2026-11-10 01:02:34,443 INFO sailab.pipeline: KRB: 2 radar scenes listed after 2026-10-27
2026-11-10 01:02:34,802 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261028T130519_20261028T130544_005216_009E76_3B4B: already recorded, skipped
2026-11-10 01:02:36,362 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261109T130519_20261109T130544_005391_00A47E_3D25: downloaded data/scenes/KRB/S1D_IW_GRDH_1SDV_20261109T130519_20261109T130544_005391_00A47E_3D25.tif sha256=67aae047305f2525c366a2d38e50bbeaa0f9774e3aa1bb525de8d1011d5a5d77
2026-11-10 01:02:36,796 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261109T130519_20261109T130544_005391_00A47E_3D25: radar ok 257.55 (25755 px below -18.45 dB connected to the centre)
2026-11-10 01:02:36,797 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261109T130519_20261109T130544_005391_00A47E_3D25: radar not risk-scored (SCORE_RADAR is off: snowmelt errors, see pipeline.py)
2026-11-10 01:02:37,797 INFO sailab.pipeline: ATS: 1 scenes listed after 2026-11-04
2026-11-10 01:02:37,798 INFO sailab.pipeline: ATS 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
2026-11-10 01:02:38,225 INFO sailab.pipeline: ATS: 2 radar scenes listed after 2026-10-27
2026-11-10 01:02:38,328 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261028T130454_20261028T130519_005216_009E76_6D2E: already recorded, skipped
2026-11-10 01:02:39,398 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261109T130454_20261109T130519_005391_00A47E_443A: downloaded data/scenes/ATS/S1D_IW_GRDH_1SDV_20261109T130454_20261109T130519_005391_00A47E_443A.tif sha256=1b5c5a9a772ea5d5a959353a02180ee2916e50b7b810f3fc8db303ac7e4ea256
2026-11-10 01:02:39,535 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261109T130454_20261109T130519_005391_00A47E_443A: radar ok 97.14 (9714 px below -15.54 dB connected to the centre)
2026-11-10 01:02:39,535 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261109T130454_20261109T130519_005391_00A47E_443A: radar not risk-scored (SCORE_RADAR is off: snowmelt errors, see pipeline.py)
2026-11-10 01:02:39,537 INFO sailab.pipeline: run 9 finished: RunResult(run_id=9, lakes_processed=2, scenes_recorded=2, scenes_downloaded=2, measurements=2, risk_scores=0, errors=None, notes=[])
2026-11-10 01:02:39,537 INFO run_once: summary: run_id=9 lakes=2 scenes_recorded=2 downloaded=2 measurements=2 risk_scores=0
2026-11-10 01:02:39,537 INFO run_once: run OK
