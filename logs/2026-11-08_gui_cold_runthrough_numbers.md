checked 2026-11-08T20:20:28+00:00, database commit a6f1cdb

| Screen | Number | Expected on page | Source | Found |
|---|---|---|---|---|
| Dashboard | Lakes monitored | `Lakes monitored 2` | COUNT(lake) | yes |
| Dashboard | Scenes recorded | `Scenes recorded 611` | COUNT(scene) | yes |
| Dashboard | Scene date range | `05 Jan 2023 to 05 Nov 2026` | MIN/MAX(scene.acquired_at) | yes |
| Dashboard | Too cloudy | `58%` | not_downloaded scenes / all scenes | yes |
| Dashboard | Too cloudy count | `357 of 611 scenes` | same | yes |
| Dashboard | Usable measurements | `Usable measurements 45 of 254 downloaded` | measurement.status = ok | yes |
| Dashboard | Last pipeline run | `Last pipeline run 09 Nov 2026, 00:01 PKT` | run_log 5.started_at | yes |
| Dashboard | KRB latest usable | `257.02 ha on 06 Sep 2026, 63 days ago` | newest ok measurement | yes |
| Dashboard | KRB score | `Insufficient history` | newest risk_score | yes |
| Lake Detail | KRB scenes | `Scenes recorded 307 20 usable, 109 refused, 178 too cloudy` | scene + measurement counts | yes |
| Lake Detail | KRB latest usable | `257.02 ha 06 Sep 2026, 63 days ago` | newest ok measurement | yes |
| Lake Detail | KRB settings | `window 2500 m, growth limit 2500 m` | lake row | yes |
| Lake Detail | KRB score scene | `Scene 06 Sep 2026` | newest risk_score | yes |
| Lake Detail | KRB score area | `Measured area 257.02 ha` | its measurement | yes |
| Lake Detail | KRB same-month values | `Earlier September values 3 from 3 years` | ok, same month, earlier | yes |
| Lake Detail | KRB image outline | `25702 px = 257.02 ha` | recomputed from data/backfill/KRB/20260906T054631_20260906T055705_T43SCA.tif | yes |
| Dashboard | ATS latest usable | `105.90 ha on 27 Aug 2026, 73 days ago` | newest ok measurement | yes |
| Dashboard | ATS score | `Deviation −0.96` | newest risk_score | yes |
| Lake Detail | ATS scenes | `Scenes recorded 304 25 usable, 100 refused, 179 too cloudy` | scene + measurement counts | yes |
| Lake Detail | ATS latest usable | `105.90 ha 27 Aug 2026, 73 days ago` | newest ok measurement | yes |
| Lake Detail | ATS settings | `window 1500 m, growth limit 1500 m` | lake row | yes |
| Lake Detail | ATS score scene | `Scene 27 Aug 2026` | newest risk_score | yes |
| Lake Detail | ATS score area | `Measured area 105.90 ha` | its measurement | yes |
| Lake Detail | ATS baseline | `Seasonal baseline 106.35 ha` | risk_score.baseline_ha | yes |
| Lake Detail | ATS deviation | `Deviation score −0.96` | risk_score.deviation_score | yes |
| Lake Detail | ATS same-month values | `Earlier August values 11 from 4 years` | ok, same month, earlier | yes |
| Lake Detail | ATS image outline | `10590 px = 105.90 ha` | recomputed from data/backfill/ATS/20260827T054631_20260827T055705_T43SCA.tif | yes |

27 of 27 checks passed.
