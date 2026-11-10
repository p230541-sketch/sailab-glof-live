# GUI live check that found a real new pass (2026-11-10, run by the project owner)

Read afterwards from the GUI's working copy (`.webapp/sailab_glof_working_copy.db`, git-ignored) and
`.webapp/live_checks.json`. The published `sailab_glof.db` was not touched (still 1,053 scenes, run 9).

| Live check | Started (UTC) | Finished (UTC) | Result |
|---|---|---|---|
| run 10 | 07:49:20 | 07:49:41 (21 s) | `new_scenes` |
| run 11 | 07:54:20 | 07:54:29 (9 s) | `no_new_scene` (same pass already recorded by run 10) |

Run 10 recorded one Sentinel-1D pass, `S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D`
(2026-11-10 01:05:41 UTC; one image covers both lakes). It was taken 3 minutes after the nightly bot's run 9
(01:02 UTC) looked, so the bot could not have seen it.

| Scene row (working copy) | Lake | Status | Area | Optical median | Difference | File SHA-256 |
|---|---|---|---|---|---|---|
| 1054 | KRB | ok | 261.14 ha | 255.14 ha | +2.4 % | 5c899ab15164059f3cc4d35845fce8d0b52f27ecf868d41c61786986ddcddcaf |
| 1055 | ATS | ok | 98.05 ha | 106.12 ha | −7.6 % | 3281926f2dec40b880647ecfccb0cba6e009abbd4bf9e69efcd47e17d28ef47b |

Both within the 15 % rule; winter radar, not validated; not scored. Against the previous pass (2026-11-09
13:05 UTC, opposite orbit direction): +1.4 % and +0.9 %, below the median 1.6 % difference between
opposite-direction passes less than 24 h apart (83 Karambar and 72 Atro Sar earlier pairs).
These rows exist only on this laptop; the next scheduled run is expected to record the same pass in the
published database.
