# GUI Days 3-5: every number on Dashboard and Lake Detail traced to its database source

Real database, independent SQL (not webapp code). Today = date of the check (UTC).

checked_at 2026-11-08T20:00:08+00:00 against sailab_glof.db (commit e2a8ba4)
| Screen | Number | Shown as | Source | Found on page |
|---|---|---|---|---|
| Dashboard | Lakes monitored | `Lakes monitored 2` | `SELECT COUNT(*) FROM lake` | ✅ |
| Dashboard | Scenes recorded | `Scenes recorded 611` | `SELECT COUNT(*) FROM scene` | ✅ |
| Dashboard | Scene date range | `05 Jan 2023 to 05 Nov 2026` | `MIN/MAX(scene.acquired_at)` | ✅ |
| Dashboard | Too cloudy % | `58%` | scene rows with `file_path LIKE 'not_downloaded/%'` ÷ all scenes | ✅ |
| Dashboard | Too cloudy count | `357 of 611 scenes` | same | ✅ |
| Dashboard | Usable measurements | `Usable measurements 45 of 254 downloaded` | `measurement.status='ok'` ÷ all measurement rows | ✅ |
| Dashboard | KRB latest usable | `257.02 ha on 06 Sep 2026, 63 days ago` | newest `measurement` row with status ok for lake 1, joined to its `scene.acquired_at` | ✅ |
| Dashboard | KRB score chip | `Insufficient history` | newest `risk_score` row for lake 1 (by scene date) | ✅ |
| Lake Detail | KRB scenes recorded | `Scenes recorded 307 20 usable, 109 refused, 178 too cloudy` | scene ⟕ measurement counts for this lake | ✅ |
| Lake Detail | KRB latest usable area | `257.02 ha 06 Sep 2026, 63 days ago` | as on the dashboard | ✅ |
| Lake Detail | KRB latest scene | `Latest scene 05 Nov 2026` | `MAX(scene.acquired_at)` for this lake | ✅ |
| Lake Detail | KRB settings | `window 2500 m, growth limit 2500 m` | `lake` row | ✅ |
| Lake Detail | KRB score: scene | `Scene 06 Sep 2026` | newest `risk_score` → its scene | ✅ |
| Lake Detail | KRB score: measured area | `Measured area 257.02 ha` | its `measurement.extent_ha` | ✅ |
| Lake Detail | KRB score: earlier same-month values | `Earlier September values 3 from 3 years` | ok measurements in the same month, before the scene | ✅ |
| Lake Detail | KRB image outline | `25702 px = 257.02 ha` | recomputed from `data/backfill/KRB/20260906T054631_20260906T055705_T43SCA.tif`; stored `257.02 ha` | ✅ |
| Dashboard | ATS latest usable | `105.90 ha on 27 Aug 2026, 73 days ago` | newest `measurement` row with status ok for lake 2, joined to its `scene.acquired_at` | ✅ |
| Dashboard | ATS score chip | `Deviation −0.96` | newest `risk_score` row for lake 2 (by scene date) | ✅ |
| Lake Detail | ATS scenes recorded | `Scenes recorded 304 25 usable, 100 refused, 179 too cloudy` | scene ⟕ measurement counts for this lake | ✅ |
| Lake Detail | ATS latest usable area | `105.90 ha 27 Aug 2026, 73 days ago` | as on the dashboard | ✅ |
| Lake Detail | ATS latest scene | `Latest scene 05 Nov 2026` | `MAX(scene.acquired_at)` for this lake | ✅ |
| Lake Detail | ATS settings | `window 1500 m, growth limit 1500 m` | `lake` row | ✅ |
| Lake Detail | ATS score: scene | `Scene 27 Aug 2026` | newest `risk_score` → its scene | ✅ |
| Lake Detail | ATS score: measured area | `Measured area 105.90 ha` | its `measurement.extent_ha` | ✅ |
| Lake Detail | ATS score: baseline | `Seasonal baseline 106.35 ha` | `risk_score.baseline_ha` | ✅ |
| Lake Detail | ATS score: deviation | `Deviation score −0.96` | `risk_score.deviation_score` | ✅ |
| Lake Detail | ATS score: earlier same-month values | `Earlier August values 11 from 4 years` | ok measurements in the same month, before the scene | ✅ |
| Lake Detail | ATS image outline | `10590 px = 105.90 ha` | recomputed from `data/backfill/ATS/20260827T054631_20260827T055705_T43SCA.tif`; stored `105.90 ha` | ✅ |

RESULT: every number found on the page and matched to its database source

Last pipeline run: re-checked precisely (the first check matched a date elsewhere on the page): expected `Last pipeline run 09 Nov 2026, 00:01 PKT` from run_log 5 started_at 2026-11-08T19:01:52+00:00: FOUND.
